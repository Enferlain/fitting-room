import ctypes, ctypes.util, glob
paths = glob.glob("/usr/lib/wsl/lib/libcuda.so*") + [ctypes.util.find_library("cuda") or "libcuda.so.1"]
cuda = ctypes.CDLL(paths[0])
assert cuda.cuInit(0) == 0
n = ctypes.c_int(); cuda.cuDeviceGetCount(ctypes.byref(n))
for i in range(n.value):
    d = ctypes.c_int(); cuda.cuDeviceGet(ctypes.byref(d), i)
    name = ctypes.create_string_buffer(100); cuda.cuDeviceGetName(name, 100, d)
    print(i, name.value.decode())
