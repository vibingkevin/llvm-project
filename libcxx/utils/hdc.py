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
    option = re.match(r"^(-{1,2}[^=]+=|-[-A-Za-z]+)(/.*)$", value)
    if option:
        return option[1] + mapped_path(option[2], local_root, remote_root)
    if "," in value:
        return ",".join(mapped_path(part, local_root, remote_root) for part in value.split(","))
    # Environment options and profile patterns may prefix an absolute path.
    value = re.sub(r"(^|[=:]|%[cmpbh]|%[0-9]+x)" + re.escape(str(local_root)) + r"(?=/|$)",
                   lambda match: match[1] + remote_root, value)
    path = Path(value)
    if path.is_absolute() and path.is_relative_to(local_root):
        return str(Path(remote_root) / path.relative_to(local_root))
    return value


def stable_work_root(remote_root, prefix):
    key = hashlib.sha256(str(Path(prefix).resolve()).encode()).hexdigest()
    return remote_root.rstrip("/") + "/.tests/" + key + "/work"


def decode_result(raw):
    header, payload = raw.split(b"\n", 1)
    match = re.fullmatch(rb"__OHOS_RESULT__:(\d+):(\d+):(\d+)(?::\d+)?", header)
    if not match:
        raise ValueError("missing device result frame: " + repr(raw[:200]))
    status, out_size, err_size = map(int, match.groups())
    if status > 255 or len(payload) != out_size + err_size:
        raise ValueError(f"truncated or invalid device result frame: expected {out_size + err_size} bytes, got {len(payload)}; tail={payload[-200:]!r}")
    return status, payload[:out_size], payload[out_size:]


def symbolize_output(data, symbolizer, local_root, remote_root):
    def replace(match):
        module = match[2].decode()
        if not module.startswith(remote_root + "/"):
            return match[0]
        obj = local_root / module[len(remote_root) + 1:]
        result = subprocess.run([symbolizer, "--output-style=JSON", "--no-inlines",
                                 "--obj=" + str(obj), match[3].decode()],
                                capture_output=True, check=True, timeout=20)
        info = json.loads(result.stdout)[0]["Symbol"][0]
        if not info["Line"]:
            return match[0]
        location = f" in {info['FunctionName']} {info['FileName']}:{info['Line']}:{info['Column']}"
        return match[1] + location.encode() + b" (" + match[2] + b"+" + match[3] + b")"
    def replace_note(match):
        module = match[1].decode()
        if not module.startswith(remote_root + "/"):
            return match[0]
        obj = local_root / module[len(remote_root) + 1:]
        result = subprocess.run([symbolizer, "--output-style=JSON", "--no-inlines",
                                 "--obj=" + str(obj), match[2].decode()],
                                capture_output=True, check=True, timeout=20)
        info = json.loads(result.stdout)[0]["Symbol"][0]
        if not info["FunctionName"]:
            return match[0]
        return b"(" + match[1] + b"+" + match[2] + b"): note: " + info["FunctionName"].encode() + b" defined here"
    data = re.sub(rb"\(([^\n()]+)\+(0x[0-9a-f]+)\): note: \(unknown\) defined here", replace_note, data)
    return re.sub(rb"(#[0-9]+ 0x[0-9a-f]+)[ \t]+\(([^\n()]+)\+(0x[0-9a-f]+)\)", replace, data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True)
    parser.add_argument("--remote-root", required=True)
    parser.add_argument("--local-root", type=Path)
    parser.add_argument("--path-map", action="append", default=[], help="map an additional pre-staged host directory: HOST=DEVICE")
    parser.add_argument("--execdir", type=Path)
    parser.add_argument("--no-sync", action="store_true")
    parser.add_argument("--stable-workdir", action="store_true", help="use the same mapped paths at compile time and runtime")
    parser.add_argument("--merge-stderr", action="store_true")
    parser.add_argument("--uid", type=int)
    parser.add_argument("--run-as")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--env", nargs="*", default=[])
    parser.add_argument("--prepend_env", nargs="*", default=[])
    parser.add_argument("--audit", type=Path)
    parser.add_argument("--forward-env", action="append", default=[])
    parser.add_argument("--retrieve-prefix", type=Path,
                        help="copy this test's temporary files back for host-side checks")
    parser.add_argument("--retrieve-glob", action="append", default=[], help="retrieve generated files in the execution directory")
    parser.add_argument("--gcov-prefix-map", action="store_true", help="relocate embedded host gcda paths into the device work directory")
    parser.add_argument("--symbolizer", help="symbolize target offsets using the original host ELF")
    parser.add_argument("--process-supervisor", help="device waitpid helper; propagate actual child signals")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("missing command")
    if any(not re.fullmatch(r"[A-Za-z0-9_.?*+-]+", pattern) for pattern in args.retrieve_glob):
        parser.error("retrieve globs must be basenames")
    if args.no_sync and not args.local_root:
        parser.error("--no-sync requires --local-root")
    if args.uid is not None and (not args.run_as or args.no_sync):
        parser.error("--uid requires --run-as and per-test sync")
    if args.symbolizer and not args.retrieve_prefix:
        parser.error("--symbolizer requires --retrieve-prefix")
    execdir = (args.execdir or Path.cwd()).resolve()
    local_root = (args.local_root or execdir).resolve()
    if not execdir.is_relative_to(local_root):
        parser.error("execution directory is outside --local-root")
    hdc = [os.environ.get("HDC", "hdc"), "-t", args.device]
    run_id = uuid.uuid4().hex
    job = args.remote_root.rstrip("/") + "/.runs/" + run_id
    remote_root = args.remote_root if args.no_sync else job + "/work"
    cwd = Path.cwd().resolve()
    if not cwd.is_relative_to(execdir):
        cwd = execdir
    if args.retrieve_prefix:
        prefix = args.retrieve_prefix.resolve()
        if prefix.parent != execdir:
            parser.error("--retrieve-prefix must be directly inside --execdir")
    if args.stable_workdir:
        if args.no_sync or not args.retrieve_prefix:
            parser.error("--stable-workdir requires per-test sync and --retrieve-prefix")
        remote_root = stable_work_root(args.remote_root, prefix)
    remote_cwd = mapped_path(str(cwd), local_root, remote_root)
    remote_sync_root = mapped_path(str(execdir), local_root, remote_root)
    extra_maps = []
    for entry in args.path_map:
        host, separator, target = entry.partition("=")
        if not separator or not Path(host).is_absolute() or not target.startswith("/"):
            parser.error("--path-map requires absolute HOST=DEVICE paths")
        extra_maps.append((Path(host).resolve(), target))

    def map_argument(value):
        value = mapped_path(value, local_root, remote_root)
        for host, target in extra_maps:
            value = mapped_path(value, host, target)
        return value

    remote_command = [map_argument(x) for x in command]
    # lit sometimes supplies a relative executable, resolved in the working dir.
    if Path(command[0]).is_file():
        remote_command[0] = map_argument(str(Path(command[0]).resolve()))
    record = {"device": args.device, "command": command, "remote_command": remote_command,
              "cwd": str(execdir), "id": run_id, "test_prefix": str(args.retrieve_prefix) if args.retrieve_prefix else None}
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
                    # compiler-rt shares %T between tests. Do not resend every
                    # other test's binaries on each invocation; unprefixed
                    # shared inputs and this test's complete prefix stay intact.
                    def own_artifacts(info):
                        name = Path(info.name).parts
                        first = name[0] if name and name[0] != "." else (name[1] if len(name) > 1 else "")
                        if args.retrieve_prefix and re.search(r"\.(?:c|cpp|test|ll|s)\.tmp", first) and not first.startswith(prefix.name):
                            return None
                        return info
                    tar.add(execdir, arcname=".", filter=own_artifacts)
                transport("file", "send", str(archive), job + "/work.tar")
                if args.stable_workdir:
                    setup += ["rm -rf " + shlex.quote(remote_root)]
                setup += ["mkdir -p " + shlex.quote(remote_root),
                          "tar -xf " + shlex.quote(job + "/work.tar") + " -C " + shlex.quote(remote_root)]
            stdin_path = "/dev/null"
            if stdin:
                (tmp / "stdin").write_bytes(stdin)
                transport("file", "send", str(tmp / "stdin"), job + "/stdin")
                stdin_path = job + "/stdin"
            env = [name + "=" + map_argument(os.environ[name])
                   for name in args.forward_env if name in os.environ]
            if args.gcov_prefix_map:
                env += ["GCOV_PREFIX=" + remote_root, "GCOV_PREFIX_STRIP=" + str(len(local_root.parts) - 1)]
            for entry in args.env + args.prepend_env:
                name, separator, value = entry.partition("=")
                env.append(name + separator + map_argument(value))
            target_command = remote_command
            if args.process_supervisor:
                target_command = [args.process_supervisor, job + "/signal", *remote_command]
            invocation_args = ["env", *env, "timeout", "-k", "5", str(args.timeout), *target_command]
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
            script += "; status=$?; signal=0; if [ -f " + shlex.quote(job + "/signal") + " ]; then signal=$(cat " + shlex.quote(job + "/signal") + "); fi"
            script += "; printf '__OHOS_RESULT__:%d:%d:%d:%d\\n' \"$status\""
            script += " \"$(wc -c < " + shlex.quote(job + "/stdout") + ")\""
            script += " \"$(wc -c < " + shlex.quote(job + "/stderr") + ")\" \"$signal\"; "
            script += "cat " + shlex.quote(job + "/stdout") + " " + shlex.quote(job + "/stderr")
            if args.retrieve_prefix or args.retrieve_glob:
                # Only this test's prefix is collected; other parallel tests can
                # share %T without having their files overwritten on the host.
                script += "; cd " + shlex.quote(remote_sync_root)
                patterns = ([shlex.quote(prefix.name) + "*"] if args.retrieve_prefix else []) + args.retrieve_glob
                script += "; set --; for item in " + " ".join(patterns) + "; do if [ -e \"$item\" ]; then set -- \"$@\" \"$item\"; fi; done"
                script += "; if [ \"$#\" -gt 0 ]; then tar -cf " + shlex.quote(job + "/artifacts.tar") + " -- \"$@\"; else mkdir -p " + shlex.quote(job + "/empty") + "; tar -cf " + shlex.quote(job + "/artifacts.tar") + " -C " + shlex.quote(job + "/empty") + " .; fi"
            else:
                script += "; rm -rf " + shlex.quote(job)
            raw = transport("shell", script, timeout=args.timeout + 30)
            status, stdout, stderr = decode_result(raw)
            target_signal = int(raw.split(b"\n", 1)[0].rsplit(b":", 1)[1])
            if args.retrieve_prefix or args.retrieve_glob:
                archive = tmp / "artifacts.tar"
                transport("file", "recv", job + "/artifacts.tar", str(archive))
                with tarfile.open(archive) as tar:
                    def local_artifact(info, destination):
                        # Device-created absolute symlinks to this test's files
                        # must remain inside the host test directory on return.
                        if info.issym() and info.linkname.startswith(remote_sync_root + "/"):
                            target = execdir / info.linkname[len(remote_sync_root) + 1:]
                            parent = execdir / Path(info.name).parent
                            info = info.replace(linkname=os.path.relpath(target, parent))
                        return tarfile.data_filter(info, destination)
                    tar.extractall(execdir, filter=local_artifact)
                transport("shell", "rm -rf " + shlex.quote(job))
            cleaned = True
            if args.symbolizer and not any("symbolize=0" in os.environ.get(name, "")
                                            for name in args.forward_env):
                (execdir / (prefix.name + ".device-stdout")).write_bytes(stdout)
                (execdir / (prefix.name + ".device-stderr")).write_bytes(stderr)
                stdout = symbolize_output(stdout, args.symbolizer, local_root, remote_root)
                stderr = symbolize_output(stderr, args.symbolizer, local_root, remote_root)
            sys.stdout.buffer.write(stdout)
            sys.stderr.buffer.write(stderr)
            record.update(exit_code=status, stdout_sha256=hashlib.sha256(stdout).hexdigest(),
                          stderr_sha256=hashlib.sha256(stderr).hexdigest(), target_signal=target_signal)
            return -target_signal if target_signal else status
    except Exception as exc:
        record["transport_error"] = str(exc)
        print("OHOS executor: " + str(exc), file=sys.stderr)
        return 125
    finally:
        record["elapsed"] = time.monotonic() - started
        if args.audit:
            with args.audit.open("a") as stream:
                stream.write(json.dumps(record) + "\n")
        if args.stable_workdir:
            try:
                transport("shell", "rm -rf " + shlex.quote(remote_root))
            except Exception as exc:
                print("OHOS work cleanup: " + str(exc), file=sys.stderr)
        if not cleaned:
            try:
                transport("shell", "rm -rf " + shlex.quote(job))
            except Exception as exc:
                print("OHOS cleanup: " + str(exc), file=sys.stderr)


if __name__ == "__main__":
    result = main()
    if result < 0:
        import resource
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        sys.stdout.flush()
        sys.stderr.flush()
        os.kill(os.getpid(), -result)
    sys.exit(result)
