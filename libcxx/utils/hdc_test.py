#!/usr/bin/env python3
"""Run the HDC process contract test with OHOS_TEST_DEVICE set."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from hdc import decode_result, mapped_path


class HdcTest(unittest.TestCase):
    def test_result_frame(self):
        self.assertEqual(decode_result(b"__OHOS_RESULT__:7:3:2\na\x00\xff\r\n"), (7, b"a\x00\xff", b"\r\n"))
        for raw in (b"HDC disconnected", b"__OHOS_RESULT__:0:10:0\nshort"):
            with self.assertRaises(ValueError):
                decode_result(raw)

    def test_mapping_preserves_unrelated_paths(self):
        root = Path("/host/build")
        self.assertEqual(mapped_path("/host/build/a b", root, "/device"), "/device/a b")
        self.assertEqual(mapped_path("/host/build-other/a", root, "/device"), "/host/build-other/a")
        self.assertEqual(mapped_path("/proc/self/maps", root, "/device"), "/proc/self/maps")
        self.assertEqual(mapped_path("-d/host/build/db", root, "/device"), "-d/device/db")
        self.assertEqual(mapped_path("--input=/host/build/a", root, "/device"), "--input=/device/a")

    @unittest.skipUnless(os.environ.get("OHOS_TEST_DEVICE"), "set OHOS_TEST_DEVICE for the device contract")
    def test_process_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a b").write_text("data")
            result = subprocess.run([
                sys.executable, str(Path(__file__).with_name("hdc.py")),
                "--device", os.environ["OHOS_TEST_DEVICE"],
                "--remote-root", os.environ["OHOS_TEST_ROOT"], "--execdir", directory,
                "--env", "TEST_QUOTE=a'b $c", "--", "sh", "-c",
                "cat; cat 'a b'; printf '%s' \"$TEST_QUOTE\"; printf err >&2; exit 7",
            ], input=b"in\x00put\n", capture_output=True, timeout=90)
            self.assertEqual(result.returncode, 7, result.stderr)
            self.assertEqual(result.stdout, b"in\x00put\ndataa'b $c")
            self.assertEqual(result.stderr, b"err")

    @unittest.skipUnless(os.environ.get("OHOS_TEST_DEVICE"), "set OHOS_TEST_DEVICE for the device contract")
    def test_merged_output_preserves_order(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([
                sys.executable, str(Path(__file__).with_name("hdc.py")),
                "--device", os.environ["OHOS_TEST_DEVICE"],
                "--remote-root", os.environ["OHOS_TEST_ROOT"], "--execdir", directory,
                "--merge-stderr", "--", "sh", "-c",
                "printf one; printf two >&2; printf three",
            ], capture_output=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, b"onetwothree")
            self.assertEqual(result.stderr, b"")


if __name__ == "__main__":
    unittest.main()
