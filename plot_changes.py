import matplotlib.pyplot as plt
import pandas as pd

#%%

df = pd.read_csv('sync_stats.csv')

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
positives = [cumulate(df[key]) for key in df.keys() if key.startswith('added_nodes_')]
negatives = [cumulate(df[key]) for key in df.keys() if key.startswith('removed_nodes_')]

#%%
plt.figure(figsize=(20,10))

#%%
plt.stackplot(x_axis, *positives, colors=[(0.3 + 0.2*(i%2), 1.0, 0.3 + 0.2*(i%2)) for i in range(len(negatives))])
plt.stackplot(x_axis, *negatives, colors=[(1.0, 0.3 + 0.2*(i%2), 0.3 + 0.2*(i%2)) for i in range(len(negatives))])

plt.plot([],[],color='g', label='Added', linewidth=5)
plt.plot([],[],color='r', label='Removed', linewidth=5)
plt.legend(loc=2)

plt.minorticks_on()

# Customize the major grid
plt.grid(which='major', linestyle='-', linewidth='0.3', color='black')
# Customize the minor grid
plt.grid(which='minor', linestyle=':', linewidth='0.5', color='black')

#%%
print("done")

plt.xlabel('Slot')
plt.ylabel('Number of merkle nodes')
plt.title('Removed/Added nodes over time')
plt.show()

