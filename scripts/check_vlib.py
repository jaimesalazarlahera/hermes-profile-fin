import os
import sys

# List packages in the venv site-packages
print("sys.executable:", sys.executable)
try:
    import site
    print("site.getsitepackages:", site.getsitepackages())
    ps = site.getsitepackages()[0]
    names = sorted(os.listdir(ps))
    print("num packages:", len(names))
    for n in names:
        print(" -", n)
except Exception as e:
    print("ERR site:", e)
