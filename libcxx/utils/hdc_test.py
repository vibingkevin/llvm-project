#!/usr/bin/env python3
"""Run the HDC process contract test with OHOS_TEST_DEVICE set."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from hdc import decode_result, mapped_path, stable_work_root


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
        self.assertEqual(mapped_path("-extra-module=/host/build/a", root, "/device"), "-extra-module=/device/a")
        self.assertEqual(mapped_path("%c/host/build/a.profraw", root, "/device"), "%c/device/a.profraw")
        self.assertEqual(mapped_path("%15x/host/build/a.profraw", root, "/device"), "%15x/device/a.profraw")
        self.assertEqual(mapped_path("suppressions=/host/build/a:log_path=/host/build/b", root, "/device"), "suppressions=/device/a:log_path=/device/b")
        self.assertEqual(mapped_path("__data,/host/build/a@foo=0", root, "/device"), "__data,/device/a@foo=0")
        self.assertEqual(mapped_path("-seed_inputs=/host/build/a,/host/build/b", root, "/device"), "-seed_inputs=/device/a,/device/b")

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

    @unittest.skipUnless(os.environ.get("OHOS_TEST_DEVICE"), "set OHOS_TEST_DEVICE for the device contract")
    def test_retrieves_generated_file_and_forwards_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = dict(os.environ, LLVM_PROFILE_FILE=str(root / "case.profraw"))
            result = subprocess.run([
                sys.executable, str(Path(__file__).with_name("hdc.py")),
                "--device", env["OHOS_TEST_DEVICE"], "--remote-root", env["OHOS_TEST_ROOT"],
                "--execdir", directory, "--retrieve-prefix", str(root / "case"),
                "--forward-env", "LLVM_PROFILE_FILE", "--", "sh", "-c",
                'printf profile > "$LLVM_PROFILE_FILE"; exit 9',
            ], env=env, capture_output=True, timeout=90)
            self.assertEqual(result.returncode, 9, result.stderr)
            self.assertEqual((root / "case.profraw").read_bytes(), b"profile")


    @unittest.skipUnless(os.environ.get("OHOS_TEST_PROCESS_SUPERVISOR"), "set the device waitpid helper")
    def test_signal_is_distinct_from_explicit_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            command = [sys.executable, str(Path(__file__).with_name("hdc.py")),
                       "--device", os.environ["OHOS_TEST_DEVICE"],
                       "--remote-root", os.environ["OHOS_TEST_ROOT"], "--execdir", directory,
                       "--process-supervisor", os.environ["OHOS_TEST_PROCESS_SUPERVISOR"],
                       "--", "sh", "-c"]
            for script, expected in [("kill -KILL $$", -9), ("exit 137", 137)]:
                result = subprocess.run(command + [script], capture_output=True, timeout=90)
                self.assertEqual(result.returncode, expected, result.stderr)

    @unittest.skipUnless(os.environ.get("OHOS_TEST_DEVICE"), "set OHOS_TEST_DEVICE for the device contract")
    def test_retrieves_benchmark_output(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([
                sys.executable, str(Path(__file__).with_name("hdc.py")),
                "--device", os.environ["OHOS_TEST_DEVICE"],
                "--remote-root", os.environ["OHOS_TEST_ROOT"], "--execdir", directory,
                "--retrieve-glob", "*Output.txt", "--", "sh", "-c",
                "printf computed > imageOutput.txt",
            ], capture_output=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((Path(directory) / "imageOutput.txt").read_text(), "computed")


    @unittest.skipUnless(os.environ.get("OHOS_TEST_DEVICE"), "set OHOS_TEST_DEVICE for the device contract")
    def test_stable_path_subdirectory_and_empty_glob(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sub = root / "case.tmp.dir"
            sub.mkdir()
            (root / "other.c.tmp").write_text("unrelated test")
            prefix = root / "case.tmp"
            remote = stable_work_root(os.environ["OHOS_TEST_ROOT"], prefix)
            command = [sys.executable, str(Path(__file__).with_name("hdc.py")),
                       "--device", os.environ["OHOS_TEST_DEVICE"],
                       "--remote-root", os.environ["OHOS_TEST_ROOT"],
                       "--execdir", directory, "--retrieve-prefix", str(prefix),
                       "--stable-workdir", "--retrieve-glob", "*Output.txt",
                       "--env", "EXPECTED=" + str(sub), "--", "sh", "-c"]
            result = subprocess.run(command + ['test "$PWD" = "$EXPECTED" && test ! -e ../other.c.tmp && printf persisted > state && ln -s "$PWD/state" state-link && pwd'],
                                    cwd=sub, capture_output=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip().decode(), remote + "/case.tmp.dir")
            self.assertEqual((sub / "state").read_text(), "persisted")
            self.assertTrue((sub / "state-link").is_symlink())
            self.assertEqual((sub / "state-link").read_text(), "persisted")
            result = subprocess.run(command + ["cat state"], cwd=sub, capture_output=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, b"persisted")

    @unittest.skipUnless(os.environ.get("OHOS_TEST_DEVICE"), "set OHOS_TEST_DEVICE for the device contract")
    def test_empty_retrieval_does_not_pollute_output(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([
                sys.executable, str(Path(__file__).with_name("hdc.py")),
                "--device", os.environ["OHOS_TEST_DEVICE"],
                "--remote-root", os.environ["OHOS_TEST_ROOT"], "--execdir", directory,
                "--retrieve-glob", "*Output.txt", "--", "sh", "-c", "printf hello",
            ], capture_output=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, b"hello")
            self.assertEqual(result.stderr, b"")


if __name__ == "__main__":
    unittest.main()
