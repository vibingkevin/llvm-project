#!/usr/bin/env python3
# Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
# See https://llvm.org/LICENSE.txt for license information.
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""Execute a cross-compiled test on an OHOS device, preserving its process result.

Compatible with libc++'s executor and test-suite's RUN_UNDER interfaces. The
pre-staged mode maps a build tree onto --remote-root without deploying SDK libs.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid


def mapped_path(value, local_root, remote_root):
    # Programs also accept paths joined to an option (-d/path, --input=/path).
    option = re.match(r"^(--[^=]+=|-[-A-Za-z]+)(/.*)$", value)
    if option:
        return option[1] + mapped_path(option[2], local_root, remote_root)
    path = Path(value)
    if path.is_absolute() and path.is_relative_to(local_root):
        return str(Path(remote_root) / path.relative_to(local_root))
    return value


def decode_result(raw):
    header, payload = raw.split(b"\n", 1)
    match = re.fullmatch(rb"__OHOS_RESULT__:(\d+):(\d+):(\d+)", header)
    if not match:
        raise ValueError("missing device result frame: " + repr(raw[:200]))
    status, out_size, err_size = map(int, match.groups())
    if status > 255 or len(payload) != out_size + err_size:
        raise ValueError("truncated or invalid device result frame")
    return status, payload[:out_size], payload[out_size:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True)
    parser.add_argument("--remote-root", required=True)
    parser.add_argument("--local-root", type=Path)
    parser.add_argument("--execdir", type=Path)
    parser.add_argument("--no-sync", action="store_true")
    parser.add_argument("--merge-stderr", action="store_true")
    parser.add_argument("--uid", type=int)
    parser.add_argument("--run-as")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--env", nargs="*", default=[])
    parser.add_argument("--prepend_env", nargs="*", default=[])
    parser.add_argument("--audit", type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("missing command")
    if args.no_sync and not args.local_root:
        parser.error("--no-sync requires --local-root")
    if args.uid is not None and (not args.run_as or args.no_sync):
        parser.error("--uid requires --run-as and per-test sync")
    execdir = (args.execdir or Path.cwd()).resolve()
    local_root = (args.local_root or execdir).resolve()
    if not execdir.is_relative_to(local_root):
        parser.error("execution directory is outside --local-root")
    hdc = [os.environ.get("HDC", "hdc"), "-t", args.device]
    run_id = uuid.uuid4().hex
    job = args.remote_root.rstrip("/") + "/.runs/" + run_id
    remote_root = args.remote_root if args.no_sync else job + "/work"
    remote_cwd = mapped_path(str(execdir), local_root, remote_root)
    remote_command = [mapped_path(x, local_root, remote_root) for x in command]
    # lit sometimes supplies a relative executable, resolved in the working dir.
    if Path(command[0]).is_file():
        remote_command[0] = mapped_path(str(Path(command[0]).resolve()), local_root, remote_root)
    record = {"device": args.device, "command": command, "remote_command": remote_command,
              "cwd": str(execdir), "id": run_id}
    started = time.monotonic()
    cleaned = False

    def transport(*parts, timeout=60):
        result = subprocess.run(hdc + list(parts), stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=timeout)
        if result.returncode or (parts[0] != "shell" and
            (b"[Fail]" in result.stdout or b"[Fail]" in result.stderr)):
            raise RuntimeError((result.stdout + result.stderr).decode(errors="replace"))
        return result.stdout

    try:
        with tempfile.TemporaryDirectory(prefix="ohos-exec-") as tmp:
            tmp = Path(tmp)
            stdin = sys.stdin.buffer.read()
            if not args.no_sync or stdin:
                transport("shell", "mkdir -p " + shlex.quote(job))
            setup = ["mkdir -p " + shlex.quote(job)]
            if not args.no_sync:
                archive = tmp / "work.tar"
                with tarfile.open(archive, "w") as tar:
                    tar.add(execdir, arcname=".")
                transport("file", "send", str(archive), job + "/work.tar")
                setup += ["mkdir -p " + shlex.quote(remote_root),
                          "tar -xf " + shlex.quote(job + "/work.tar") + " -C " + shlex.quote(remote_root)]
            stdin_path = "/dev/null"
            if stdin:
                (tmp / "stdin").write_bytes(stdin)
                transport("file", "send", str(tmp / "stdin"), job + "/stdin")
                stdin_path = job + "/stdin"
            env = args.env + args.prepend_env
            invocation_args = ["env", *env, "timeout", "-k", "5", str(args.timeout), *remote_command]
            if args.uid is not None:
                setup += ["chown -R " + str(args.uid) + ":" + str(args.uid) + " " + shlex.quote(remote_root)]
                invocation_args = [args.run_as, str(args.uid), *invocation_args]
                record["uid"] = args.uid
            invocation = shlex.join(invocation_args)
            setup += ["cd " + shlex.quote(remote_cwd)]
            # HDC's own exit code does not report the device program's exit code.
            script = " && ".join(setup) + " && " + invocation
            script = "( " + script + " ) < " + shlex.quote(stdin_path)
            script += " > " + shlex.quote(job + "/stdout")
            script += " 2>&1" if args.merge_stderr else " 2> " + shlex.quote(job + "/stderr")
            # Create the redirection directory before entering the subshell.
            script = "mkdir -p " + shlex.quote(job) + "; : > " + shlex.quote(job + "/stderr") + "; " + script
            script += "; status=$?; printf '__OHOS_RESULT__:%d:%d:%d\\n' \"$status\""
            script += " \"$(wc -c < " + shlex.quote(job + "/stdout") + ")\""
            script += " \"$(wc -c < " + shlex.quote(job + "/stderr") + ")\"; "
            script += "cat " + shlex.quote(job + "/stdout") + " " + shlex.quote(job + "/stderr")
            script += "; rm -rf " + shlex.quote(job)
            raw = transport("shell", script, timeout=args.timeout + 30)
            status, stdout, stderr = decode_result(raw)
            cleaned = True
            sys.stdout.buffer.write(stdout)
            sys.stderr.buffer.write(stderr)
            record.update(exit_code=status, stdout_sha256=hashlib.sha256(stdout).hexdigest(),
                          stderr_sha256=hashlib.sha256(stderr).hexdigest())
            return status
    except Exception as exc:
        record["transport_error"] = str(exc)
        print("OHOS executor: " + str(exc), file=sys.stderr)
        return 125
    finally:
        record["elapsed"] = time.monotonic() - started
        if args.audit:
            with args.audit.open("a") as stream:
                stream.write(json.dumps(record) + "\n")
        if not cleaned:
            try:
                transport("shell", "rm -rf " + shlex.quote(job))
            except Exception as exc:
                print("OHOS cleanup: " + str(exc), file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
