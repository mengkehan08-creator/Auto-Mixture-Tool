from __future__ import annotations

import mmap
import os
import unittest
from unittest import mock

from quadmix.pipeline import shared_memory


class _Library:
    def __init__(self, shm_open=None):
        if shm_open is not None:
            self.shm_open = shm_open


class SharedMemoryCompatibilityTests(unittest.TestCase):
    @mock.patch("ctypes.CDLL")
    def test_loads_shm_open_from_libc_when_available(self, cdll: mock.Mock) -> None:
        expected = mock.Mock()
        cdll.return_value = _Library(expected)

        actual = shared_memory._load_shm_open()

        self.assertIs(actual, expected)
        cdll.assert_called_once_with("libc.so.6", use_errno=True)

    @mock.patch("ctypes.CDLL")
    def test_falls_back_to_librt_for_old_glibc(self, cdll: mock.Mock) -> None:
        expected = mock.Mock()
        cdll.side_effect = [
            _Library(),
            _Library(expected),
        ]

        actual = shared_memory._load_shm_open()

        self.assertIs(actual, expected)
        self.assertEqual(
            cdll.call_args_list,
            [
                mock.call("libc.so.6", use_errno=True),
                mock.call("librt.so.1", use_errno=True),
            ],
        )

    @mock.patch("os.close")
    @mock.patch("mmap.mmap", return_value=bytearray(8))
    @mock.patch("quadmix.pipeline.shared_memory._load_shm_open")
    def test_attach_uses_posix_name_and_closes_fd(
        self,
        load_shm_open: mock.Mock,
        mmap_mock: mock.Mock,
        close: mock.Mock,
    ) -> None:
        shm_open = mock.Mock(return_value=17)
        load_shm_open.return_value = shm_open
        info = shared_memory.SharedArrayInfo("sample_shm", (2,), "int32", 8)

        array = shared_memory.shared_to_ndarray(info)

        shm_open.assert_called_once_with(b"/sample_shm", os.O_RDWR, 0o600)
        mmap_mock.assert_called_once_with(17, 8)
        close.assert_called_once_with(17)
        self.assertFalse(array.flags.writeable)


if __name__ == "__main__":
    unittest.main()
