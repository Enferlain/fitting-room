#include <dlfcn.h>
#include <stdio.h>

int main(void)
{
    void *cuda = dlopen("libcuda.so.1", RTLD_NOW | RTLD_LOCAL);
    if (!cuda) {
        fprintf(stderr, "%s\n", dlerror());
        return 1;
    }
    int (*init)(unsigned) = dlsym(cuda, "cuInit");
    int (*count_devices)(int *) = dlsym(cuda, "cuDeviceGetCount");
    int (*get_device)(int *, int) = dlsym(cuda, "cuDeviceGet");
    int (*get_name)(char *, int, int) = dlsym(cuda, "cuDeviceGetName");
    int count;
    if (!init || !count_devices || !get_device || !get_name ||
        init(0) || count_devices(&count)) {
        fputs("Could not enumerate CUDA devices\n", stderr);
        return 1;
    }
    for (int i = 0; i < count; i++) {
        int device;
        char name[128];
        if (get_device(&device, i) || get_name(name, sizeof name, device))
            return 1;
        printf("%d %s\n", i, name);
    }
    dlclose(cuda);
    return 0;
}
