import matplotlib.pyplot as plt
import pandas as pd

#%%

df = pd.read_csv('sync_stats.csv')

#%%
for key in df.keys():
    if key.startswith('removed_nodes_'):
        df[key] *= -1

def cumulate(col):
    out = []
    total = 0.0
    for v in col:
        total += v
        out.append(total)
    return out

x_axis = df['slot']
positive_keys = [key for key in df.keys() if key.startswith('added_nodes_')]
negative_keys = [key for key in df.keys() if key.startswith('removed_nodes_')]

positives = [cumulate(df[key]) for key in positive_keys]
negatives = [cumulate(df[key]) for key in negative_keys]

_prev = positive_keys
positive_keys = sorted(positive_keys, key=lambda key: max(positives[_prev.index(key)]))
positives = [positives[_prev.index(key)] for key in positive_keys]

_prev = negative_keys
negative_keys = sorted(negative_keys, key=lambda key: -min(negatives[_prev.index(key)]))
negatives = [negatives[_prev.index(key)] for key in negative_keys]


#%%
fig = plt.figure(figsize=(10,20))
ax = fig.add_subplot(1, 1, 1)

#%%
ax.stackplot(x_axis, *positives, colors=[(0.3 + 0.2*(i%2), 1.0, 0.3 + 0.2*(i%2)) for i in range(len(negatives))])
ax.stackplot(x_axis, *negatives, colors=[(1.0, 0.3 + 0.2*(i%2), 0.3 + 0.2*(i%2)) for i in range(len(negatives))])

ax.plot([],[],color='g', label='Added', linewidth=5)
ax.plot([],[],color='r', label='Removed', linewidth=5)
ax.legend(loc=2)

# ax.set_yscale('symlog')

ax.minorticks_on()

# Customize the major grid
ax.grid(which='major', linestyle='-', linewidth='0.3', color='black')
# Customize the minor grid
ax.grid(which='minor', linestyle=':', linewidth='0.5', color='black')

#%%
loc_x = x_axis.argmax()
tot_y = 0
for i, key in enumerate(positive_keys):
    prev_y = tot_y
    tot_y += positives[i][-1]
    ax.text(loc_x, (prev_y + tot_y) // 2, key.split('_nodes_')[-1])

tot_y = 0
for i, key in enumerate(negative_keys):
    prev_y = tot_y
    tot_y += negatives[i][-1]
    ax.text(loc_x, (prev_y + tot_y) // 2, key.split('_nodes_')[-1])

#%%
print("done")

plt.xlabel('Slot')
plt.ylabel('Number of merkle nodes')
plt.title('Removed/Added nodes over time')
fig.show()


