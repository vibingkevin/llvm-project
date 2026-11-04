# Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Run compiler-rt tests with the compiler's headers and the SDK's runtimes."""
import os
from pathlib import Path
import shlex
import subprocess
import sys

project = Path(__file__).resolve().parents[2]
sdk = Path(os.environ["OHOS_SDK"])
llvm = Path(os.environ["LLVM_HOME"])
build = Path(os.environ["OHOS_TEST_BUILD"])
suite = os.environ["OHOS_TEST_SUITE"]
cc = os.environ.get("OHOS_TEST_CC", str(llvm / "bin/clang"))
resource = sdk / "llvm/lib/clang/15.0.4"
intrinsics = Path(subprocess.check_output([cc, "-print-resource-dir"], text=True).strip()) / "include"
config.clang = cc
config.target_cflags = shlex.join([
    "--target=aarch64-unknown-linux-ohos", "--sysroot=" + str(sdk / "sysroot"),
    "-B" + str(sdk / "llvm/bin"), "-O3", "-fPIC", "-fno-stack-protector",
    "-nobuiltininc", "-isystem", str(intrinsics), "-resource-dir=" + str(resource),
    "--ld-path=" + str(llvm / "bin/ld.lld"),
    "-L" + str(sdk / "llvm/lib/aarch64-linux-ohos"), "-lc++", "-lpthread",
])
config.compiler_rt_libdir = str(resource / "lib/aarch64-linux-ohos")
config.compiler_rt_output_dir = str(resource)
config.test_exec_root = str(build)
executor = [sys.executable, str(project / "libcxx/utils/hdc.py"),
            "--device", os.environ["OHOS_TEST_DEVICE"],
            "--remote-root", os.environ["OHOS_TEST_ROOT"],
            "--execdir", "%T", "--retrieve-prefix", "%t", "--stable-workdir",
            "--audit", str(build / "executions.jsonl")]
if "OHOS_TEST_PROCESS_SUPERVISOR" in os.environ:
    executor += ["--process-supervisor", os.environ["OHOS_TEST_PROCESS_SUPERVISOR"]]
for name in ("LLVM_PROFILE_FILE", "ASAN_OPTIONS", "TSAN_OPTIONS", "UBSAN_OPTIONS", "HWASAN_OPTIONS", "SCUDO_OPTIONS", "LSAN_OPTIONS", "GWP_ASAN_OPTIONS", "SANITIZER_STATS_PATH", "LD_LIBRARY_PATH", "LD_PRELOAD", "TMPDIR", "LLVM_PROFILE_NO_MMAP", "LLVM_PROFILE_VERBOSE", "LLVM_VP_BUFFER_SIZE", "LLVM_VP_MAX_NUM_VALS_PER_SITE"):
    executor += ["--forward-env", name]
if suite in ("asan", "tsan", "hwasan", "ubsan", "lsan", "sanitizer_common", "gwp_asan", "cfi"):
    executor += ["--symbolizer", str(llvm / "bin/llvm-symbolizer")]
if suite == "profile":
    executor += ["--gcov-prefix-map"]
    if "OHOS_TEST_TOOL_DIR" in os.environ:
        executor += ["--env", "PATH=" + os.environ["OHOS_TEST_TOOL_DIR"] + ":/system/bin:/system/xbin"]
if suite == "sanitizer_common":
    executor += ["--retrieve-glob", "sanitizer.log.*.txt"]
config.emulator = shlex.join(executor) + " --"
config.have_curl = False
config.target_page_size = int(os.environ["OHOS_PAGE_SIZE"])
config.has_lld = (llvm / "bin/ld.lld").is_file()
config.use_lld = True
config.use_lto = suite == "cfi"
config.use_thinlto = False
config.llvm_tools_dir = os.environ.get("OHOS_TEST_TOOLS", str(llvm / "bin"))
lit_config.load_config(config, os.environ["OHOS_COMPILER_RT_CONFIG"])
# OHOS installs un-suffixed runtime names inside its target directory.
config.target_suffix = ""
config.name_suffix = "-ohos-sdk15"
config.cxx_mode_flags += ["-nostdinc++", "-isystem", str(sdk / "llvm/include/libcxx-ohos/include/c++/v1")]
config.available_features.add("ohos")
if suite == "profile" and "OHOS_TEST_TOOL_DIR" in os.environ:
    config.available_features.add("target-llvm-profdata")
config.profile_lit_binary_dir = str(build)
config.asan_lit_source_dir = str(project / "compiler-rt/test/asan")
config.asan_lit_binary_dir = str(build)
config.tsan_lit_source_dir = str(project / "compiler-rt/test/tsan")
config.tsan_lit_binary_dir = str(build)
config.hwasan_lit_source_dir = str(project / "compiler-rt/test/hwasan")
config.hwasan_lit_binary_dir = str(build)
config.bits = "64"
config.arm_thumb = False
config.asan_dynamic = True
config.has_libcxx = False  # No separately instrumented libc++ is deployed.
config.deflake_threshold = "10"
config.enable_aliases = "0"
config.ubsan_lit_test_mode = "Standalone"
config.cfi_lit_test_mode = "Standalone"
config.target_flags = ""
if suite == "fuzzer":
    # libc++ wraps stddef.h with include_next; it must precede intrinsic headers.
    config.target_cflags = shlex.join(config.cxx_mode_flags[1:]) + " " + config.target_cflags
config.cmake_binary_dir = str(build)
scudo_archive = Path(config.compiler_rt_libdir) / "libclang_rt.scudo_standalone.a"
scudo_symbols = subprocess.check_output([str(llvm / "bin/llvm-nm"), "--defined-only", "--demangle", str(scudo_archive)], text=True) if scudo_archive.exists() else ""
config.gwp_asan = "gwp_asan::GuardedPoolAllocator::" in scudo_symbols
if config.gwp_asan:
    config.available_features.add("gwp_asan")
config.test_cfi = True
config.lsan_lit_test_mode = "AddressSanitizer"
config.tool_name = os.environ.get("OHOS_SANITIZER", "asan")
if suite == "hwasan":
    config.compiler_rt_bindir = str(project / "compiler-rt/lib/hwasan/scripts")
suite_config = "lit.common.cfg.py" if suite in ("ubsan", "ubsan_minimal", "lsan", "sanitizer_common") else "lit.cfg.py"
lit_config.load_config(config, str(project / "compiler-rt/test" / suite / suite_config))

# Some upstream suites append C++ flags after target flags. Preserve the normal
# driver's libc++ -> intrinsic -> sysroot order even in those substitutions.
cxx_headers = shlex.join(config.cxx_mode_flags[1:])
config.substitutions = [
    (key, value.replace(cxx_headers, "").replace(cc, cc + " " + cxx_headers, 1)
     if "--driver-mode=g++" in value and cxx_headers in value else value)
    for key, value in config.substitutions
]

# strace in a host PATH is not evidence of a target executable.
config.available_features.discard("strace")

wrapper = shlex.join([sys.executable, str(Path(__file__).with_name("ohos-clang.py")),
                      "--compiler", cc, "--execdir", "%T", "--prefix", "%t",
                      "--remote-root", os.environ["OHOS_TEST_ROOT"], "--"])
config.substitutions = [(key, value.replace(cc, wrapper, 1)) for key, value in config.substitutions]

if suite == "cfi":
    config.substitutions.append((r"(?<![/\w.-])sanstats(?![\w.-])", shlex.join([
        sys.executable, str(Path(__file__).with_name("ohos-sanstats.py")),
        "--tool", str(llvm / "bin/sanstats"), "--execdir", "%T", "--prefix", "%t",
        "--remote-root", os.environ["OHOS_TEST_ROOT"]])))
