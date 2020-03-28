from typing import NewType, Optional, List, Dict, Iterable, Generic, TypeVar, Protocol, Generator
from fast_spec import Epoch, Slot, Root, compute_epoch_at_slot

ProtoNodeIndex = NewType('ProtoNodeIndex', int)

T = TypeVar('T')


class BlockNode(Generic[T]):
    slot: Slot
    root: Root
    data: T

    def __init__(self, slot: Slot, root: Root, data: T):
        self.slot = slot
        self.root = root
        self.data = data


class ProtoNode(Generic[T]):
    block: BlockNode
    parent: Optional[ProtoNodeIndex]
    justified_epoch: Epoch
    finalized_epoch: Epoch
    weight: int
    best_child: Optional[ProtoNodeIndex]
    best_descendant: Optional[ProtoNodeIndex]

    def __init__(self, block: BlockNode, parent: Optional[ProtoNodeIndex],
                 justified_epoch: Epoch, finalized_epoch: Epoch):
        self.block = block
        self.parent = parent
        self.justified_epoch = justified_epoch
        self.finalized_epoch = finalized_epoch
        self.weight = 0
        self.best_child = None
        self.best_descendant = None


class BlockSink(Protocol[T]):
    def on_pruned_block(self, node: ProtoNode[T], canonical: bool):
        """
        When a block is not part of fork-choice anymore.
        If canonical, it is finalized. If not canonical, it is orphaned.
        """
        ...


class ProtoArray(Generic[T]):
    _block_sink: BlockSink
    _index_offset: ProtoNodeIndex
    _finalized_root: Root
    justified_epoch: Epoch
    finalized_epoch: Epoch
    nodes: List[ProtoNode[T]]
    indices: Dict[Root, ProtoNodeIndex]

    def __init__(self, justified_epoch: Epoch,
                 finalized_block: BlockNode[T], block_sink: BlockSink):
        self._block_sink = block_sink
        self._index_offset = ProtoNodeIndex(0)
        self.justified_epoch = justified_epoch
        finalized_epoch = compute_epoch_at_slot(finalized_block.slot)
        self.finalized_epoch = finalized_epoch
        finalized_node = ProtoNode[T](
            block=finalized_block,
            parent=None,
            justified_epoch=justified_epoch,
            finalized_epoch=finalized_epoch,
        )
        self.nodes = [finalized_node]
        self.indices = {finalized_block.root: ProtoNodeIndex(0)}

    def _get_node(self, index: ProtoNodeIndex) -> ProtoNode[T]:
        if index < self._index_offset:
            raise IndexError(f"Minimum proto-array index is {self._index_offset}")
        i = index - self._index_offset
        if i > len(self.nodes):
            raise IndexError(f"Maximum proto-array index is {self._index_offset + len(self.nodes)}")
        return self.nodes[i]

    def canonical_chain(self, anchor_root: Root) -> Generator[BlockNode]:
        """From head back to anchor root (including the anchor itself)"""
        index: Optional[ProtoNodeIndex] = self.indices[self.find_head(anchor_root).root]  # KeyError if unknown root
        while index is not None and index >= self._index_offset:
            node = self._get_node(index)
            yield node.block
            if node.block.root == anchor_root:
                break
            index = node.parent

    def apply_score_changes(self, deltas: Iterable[int], justified_epoch: Epoch, finalized_epoch: Epoch):
        """
        Iterate backwards through the array, touching all nodes and their parents and potentially
        the best-child of each parent.

        The structure of the `self.nodes` array ensures that the child of each node is always
        touched before its parent.

        For each node, the following is done:

        - Update the node's weight with the corresponding delta (can be negative).
        - Back-propagate each node's delta to its parents delta.
        - Compare the current node with the parents best-child, updating it if the current node
        should become the best child.
        - If required, update the parents best-descendant with the current node or its best-descendant.
        """
        deltas = list(deltas)  # Copy, during back-prop the contents are mutated.
        assert len(deltas) == len(self.nodes) == len(self.indices)

        if justified_epoch != self.justified_epoch or finalized_epoch != self.finalized_epoch:
            self.justified_epoch = justified_epoch
            self.finalized_epoch = finalized_epoch

        # Iterate backwards through all indices in `self.nodes`.
        for node_index, node in zip(range(self._index_offset+len(self.nodes)-1, self._index_offset-1, -1), self.nodes):

            node_delta = deltas[node_index]

            # Apply the delta to the node.
            node.weight = node.weight + node_delta

            # If the node has a parent, try to update its best-child and best-descendant.
            if node.parent is not None:
                # Back-propagate the nodes delta to its parent.
                deltas[node.parent] += node_delta

                self._maybe_update_best_child_and_descendant(node.parent, node_index)

    def on_block(self, block: BlockNode[T], parent_opt: Optional[Root],
                 justified_epoch: Epoch, finalized_epoch: Epoch):
        """
        Register a block with the fork choice.

        It is only sane to supply a `None` parent for the genesis block.
        """
        # If the block is already known, simply ignore it.
        if block.root in self.indices:
            return

        node_index = ProtoNodeIndex(self._index_offset + len(self.nodes))

        parent_index = None if parent_opt is None else self.indices.get(parent_opt, default=None)

        node = ProtoNode[T](block, parent_index, justified_epoch, finalized_epoch)

        self.indices[block.root] = node_index
        self.nodes.append(node)

        if node.parent is not None:
            self._maybe_update_best_child_and_descendant(node.parent, node_index)

    def find_head(self, anchor_root: Root) -> BlockNode:
        """
        Finds the head, starting from the anchor_root subtree. (justified_root for regular fork-choice)

        Follows the best-descendant links to find the best-block (i.e., head-block).

        The result of this function is not guaranteed to be accurate if `on_block` has
        been called without a subsequent `apply_score_changes` call. This is because
        `on_block` does not attempt to walk backwards through the tree and update the
        best-child/best-descendant links.
        """
        anchor_index = self.indices.get(anchor_root)  # Key error if not there

        anchor_node = self._get_node(anchor_index)
        best_descendant_index = anchor_node.best_descendant
        if best_descendant_index is None:
            best_descendant_index = anchor_index

        best_node = self._get_node(best_descendant_index)

        # Perform a sanity check that the node is indeed valid to be the head.
        assert self._node_is_viable_for_head(best_node)

        return best_node.block

    def on_prune(self, anchor_root: Root):
        """
        Update the tree with new finalization information (or alternatively another trusted root)
        """
        anchor_index = self.indices[anchor_root]  # KeyError if unknown root
        if anchor_index == self._index_offset:
            return  # nothing to do

        assert anchor_index > self._index_offset

        best_index = self.indices[self.find_head(anchor_root).root]

        # Remove the `self.indices` key/values for all the to-be-deleted nodes.
        # And send the nodes to the block sink.
        for idx, node in zip(range(self._index_offset, anchor_index), self.nodes):
            canonical = node.best_descendant == best_index
            self._block_sink.on_pruned_block(node, canonical)
            root = self.nodes[idx].block.root
            del self.indices[root]

        # Drop all the nodes prior to finalization.
        self.nodes = list(self.nodes[anchor_index-self._index_offset:])

    def _maybe_update_best_child_and_descendant(self, parent_index: ProtoNodeIndex, child_index: ProtoNodeIndex):
        """
        Observe the parent at `parent_index` with respect to the child at `child_index` and
        potentially modify the `parent.best_child` and `parent.best_descendant` values.

        There are four outcomes:

        - The child is already the best child but it's now invalid due to a FFG change and should be removed.
        - The child is already the best child and the parent is updated with the new best-descendant.
        - The child is not the best child but becomes the best child.
        - The child is not the best child and does not become the best child.
        """
        child = self._get_node(child_index)
        parent = self._get_node(parent_index)

        child_leads_to_viable_head = self._node_leads_to_viable_head(child)

        # The three options that we may set the `parent.best_child` and `parent.best_descendant` to.

        def change_to_none():
            parent.best_child = None
            parent.best_descendant = None

        def change_to_child():
            parent.best_child = child_index
            if child.best_descendant is None:
                parent.best_descendant = child_index
            else:
                parent.best_descendant = child.best_descendant

        def no_change():
            pass

        if parent.best_child is not None:
            if parent.best_child == child_index:
                if not child_leads_to_viable_head:
                    # If the child is already the best-child of the parent but it's not viable for the head, remove it.
                    change_to_none()
                else:
                    # If the child is the best-child already, set it again to ensure that the
                    # best-descendant of the parent is updated.
                    change_to_child()
            else:
                best_child = self._get_node(parent.best_child)
                best_child_leads_to_viable_head = self._node_leads_to_viable_head(best_child)

                if child_leads_to_viable_head and (not best_child_leads_to_viable_head):
                    # The child leads to a viable head, but the current best-child doesn't.
                    change_to_child()
                elif (not child_leads_to_viable_head) and best_child_leads_to_viable_head:
                    # The best child leads to a viable head, but the child doesn't.
                    no_change()
                elif child.weight == best_child.weight:
                    # Tie-breaker of equal weights by root.
                    if child.block.root >= best_child.block.root:
                        change_to_child()
                    else:
                        no_change()
                else:
                    # Choose the winner by weight.
                    if child.weight >= best_child.weight:
                        change_to_child()
                    else:
                        no_change()
        else:
            if child_leads_to_viable_head:
                # There is no current best-child and the child is viable.
                change_to_child()
            else:
                # There is no current best-child but the child is not viable.
                no_change()

    def _node_leads_to_viable_head(self, node: ProtoNode[T]) -> bool:
        """Indicates if the node itself is viable for the head, or if it's best descendant is viable for the head."""
        if node.best_descendant is not None:
            best_descendant = self._get_node(node.best_descendant)
            return self._node_is_viable_for_head(best_descendant)
        else:
            return self._node_is_viable_for_head(node)

    def _node_is_viable_for_head(self, node: ProtoNode[T]) -> bool:
        """
        This is the equivalent to the `filter_block_tree` function in the eth2 spec:

        https://github.com/ethereum/eth2.0-specs/blob/v0.10.0/specs/phase0/fork-choice.md#filter_block_tree

        Any node that has a different finalized or justified epoch should not be viable for the head.
        """
        return (node.justified_epoch == self.justified_epoch or self.justified_epoch == 0) and\
               (node.finalized_epoch == self.finalized_epoch or self.finalized_epoch == 0)
