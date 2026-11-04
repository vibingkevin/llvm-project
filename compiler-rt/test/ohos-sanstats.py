#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Map only module filenames in device statistics for host symbolization."""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "libcxx/utils"))
from hdc import stable_work_root

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--tool", required=True)
p.add_argument("--execdir", type=Path, required=True)
p.add_argument("--prefix", required=True)
p.add_argument("--remote-root", required=True)
p.add_argument("file", type=Path)
a = p.parse_args()
raw = a.file.read_bytes()
if not raw or raw[0] not in (4, 8):
    raise ValueError("invalid statistics pointer size")
size = raw[0] * 2
out = bytearray(raw[:1])
remote = stable_work_root(a.remote_root, a.prefix).encode()
pos = 1
while pos < len(raw):
    end = raw.index(b"\0", pos)
    module = raw[pos:end]
    if module.startswith(remote + b"/"):
        module = str(a.execdir.resolve()).encode() + module[len(remote):]
    out += module + b"\0"
    pos = end + 1
    while True:
        record = raw[pos:pos + size]
        if len(record) != size:
            raise ValueError("truncated statistics record")
        out += record
        pos += size
        if not any(record):
            break
# The original device statistics and all address/count records remain intact.
with tempfile.TemporaryDirectory(prefix="ohos-sanstats-") as tmp:
    mapped = Path(tmp) / "mapped.stats"
    mapped.write_bytes(out)
    sys.exit(subprocess.call([a.tool, str(mapped)]))
