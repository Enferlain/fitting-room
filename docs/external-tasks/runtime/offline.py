"""Launch a command with UNIX sockets enabled and other socket families denied."""
import ctypes as ct
import errno
import os
import socket
import sys

class Argument(ct.Structure):
    _fields_ = [("arg", ct.c_uint), ("op", ct.c_uint),
                ("datum_a", ct.c_uint64), ("datum_b", ct.c_uint64)]

library = ct.CDLL("libseccomp.so.2")
library.seccomp_init.argtypes = [ct.c_uint32]
library.seccomp_init.restype = ct.c_void_p
library.seccomp_syscall_resolve_name.argtypes = [ct.c_char_p]
library.seccomp_rule_add_array.argtypes = [ct.c_void_p, ct.c_uint32, ct.c_int, ct.c_uint, ct.POINTER(Argument)]
library.seccomp_load.argtypes = [ct.c_void_p]
library.seccomp_release.argtypes = [ct.c_void_p]
context = library.seccomp_init(0x7FFF0000)
if not context:
    raise RuntimeError("could not initialize network filter")
try:
    deny = 0x00050000 | errno.EPERM
    for name in (b"socket", b"socketpair"):
        number = library.seccomp_syscall_resolve_name(name)
        if number < 0 or library.seccomp_rule_add_array(
            context, deny, number, 1, ct.byref(Argument(0, 1, socket.AF_UNIX, 0))
        ):
            raise RuntimeError(f"could not deny non-UNIX sockets for {name!r}")
    for name in (b"io_uring_setup", b"io_uring_enter", b"io_uring_register"):
        number = library.seccomp_syscall_resolve_name(name)
        if number >= 0 and library.seccomp_rule_add_array(context, deny, number, 0, None):
            raise RuntimeError(f"could not filter {name!r}")
    if library.seccomp_load(context):
        raise RuntimeError("could not load network filter")
finally:
    library.seccomp_release(context)
os.execvp(sys.argv[1], sys.argv[1:])
