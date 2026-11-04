#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Map embedded test paths without changing host compilation input/output paths."""
import argparse
import re
from pathlib import Path
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "libcxx/utils"))
from hdc import stable_work_root

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--compiler", required=True)
parser.add_argument("--execdir", type=Path, required=True)
parser.add_argument("--prefix", required=True)
parser.add_argument("--remote-root", required=True)
parser.add_argument("args", nargs=argparse.REMAINDER)
a = parser.parse_args()
args = a.args[1:] if a.args[:1] == ["--"] else a.args
host = str(a.execdir.resolve())
remote = stable_work_root(a.remote_root, a.prefix)
# These flags embed runtime paths. Input files, -o, and profile-use files remain
# host paths. Test source and expected output are never rewritten.
embedded = ("-D", "-fprofile-instr-generate=", "-fprofile-generate=", "-fprofile-instrument-path=", "-Wl,-rpath,")
args = [re.sub(re.escape(host) + r'(?=/|["\']|$)', lambda _: remote, arg) if arg.startswith(embedded) else arg for arg in args]
for index in range(1, len(args)):
    if args[index - 1] in ("-rpath", "-Wl,-rpath"):
        args[index] = re.sub(re.escape(host) + r"(?=/|$)", lambda _: remote, args[index])
# Linking an absolute host .so without SONAME embeds that host path in
# DT_NEEDED. Give test DSOs their corresponding stable device path instead.
if "-shared" in args and "-o" in args and not any("soname" in arg for arg in args):
    output = Path(args[args.index("-o") + 1]).resolve()
    if output.is_relative_to(a.execdir.resolve()):
        args.append("-Wl,-soname," + str(Path(remote) / output.relative_to(a.execdir.resolve())))
sys.exit(subprocess.call([a.compiler, *args]))
