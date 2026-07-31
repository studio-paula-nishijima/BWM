import numpy as np

x = np.fromfile("old.raw", dtype=np.int16)
y = np.fromfile("new.raw", dtype=np.int16)

print("old")
print("mean")
print(np.mean(x))
print("std")
print(np.std(x))

print("new")
print("mean")
print(np.mean(y))
print("std")
print(np.std(y))
