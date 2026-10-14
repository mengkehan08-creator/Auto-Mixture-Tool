"""Shared memory helpers for multiprocessing (avoids re-reading large metadata per worker)."""

import multiprocessing as mp
import multiprocessing.shared_memory

import numpy as np


def _load_shm_open():
    """Load POSIX shm_open across both new and old glibc layouts."""
    import ctypes

    errors = []
    for library_name in ("libc.so.6", "librt.so.1"):
        try:
            library = ctypes.CDLL(library_name, use_errno=True)
            shm_open = library.shm_open
        except (AttributeError, OSError) as exc:
            errors.append(f"{library_name}: {exc}")
            continue
        shm_open.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_uint]
        shm_open.restype = ctypes.c_int
        return shm_open
    raise OSError("unable to load shm_open (" + "; ".join(errors) + ")")


class SharedArrayInfo:
    """Descriptor for a numpy array in shared memory — pickle-safe for mp."""

    def __init__(self, name: str, shape: tuple, dtype: str, nbytes: int):
        self.name = name
        self.shape = shape
        self.dtype = dtype
        self.nbytes = nbytes


def ndarray_to_shared(arr: np.ndarray, prefix: str) -> SharedArrayInfo:
    """Copy numpy array into shared memory, return descriptor."""
    shm = mp.shared_memory.SharedMemory(create=True, size=arr.nbytes, name=f"{prefix}_shm")
    shared = np.ndarray(arr.shape, dtype=arr.dtype, buffer=shm.buf)
    np.copyto(shared, arr)
    info = SharedArrayInfo(name=shm.name, shape=arr.shape, dtype=str(arr.dtype), nbytes=arr.nbytes)
    shm.close()
    return info


def shared_to_ndarray(info: SharedArrayInfo) -> np.ndarray:
    """Map shared memory back to numpy array (zero-copy read-only view).

    Uses ctypes shm_open + mmap.mmap + os.close(fd) to attach. Python 3.13+
    SharedMemory.close() also munmaps _mmap, which would segfault the view.
    Here os.close(fd) closes the fd but the mmap object (held by the returned
    ndarray's base) retains the mapping until the ndarray is GC'd.
    """
    import ctypes, mmap, os

    shm_open = _load_shm_open()
    posix_name = info.name if info.name.startswith("/") else f"/{info.name}"
    fd = shm_open(posix_name.encode(), os.O_RDWR, 0o600)
    if fd < 0:
        errno = ctypes.get_errno()
        raise OSError(errno, os.strerror(errno), info.name)
    try:
        m = mmap.mmap(fd, info.nbytes)
    finally:
        os.close(fd)
    arr = np.ndarray(shape=info.shape, dtype=np.dtype(info.dtype), buffer=m)
    arr.flags.writeable = False
    return arr
