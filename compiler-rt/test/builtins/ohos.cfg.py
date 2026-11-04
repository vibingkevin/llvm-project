# Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Run the existing builtins unit tests against the DevEco SDK archive."""
import os
from pathlib import Path
import shlex
import subprocess
import sys
import lit.formats

project = Path(__file__).resolve().parents[3]
sdk = Path(os.environ["OHOS_SDK"])
llvm = Path(os.environ["LLVM_HOME"])
build = Path(os.environ["OHOS_TEST_BUILD"])
resource = sdk / "llvm/lib/clang/15.0.4"
libdir = resource / "lib/aarch64-linux-ohos"
archive = libdir / "libclang_rt.builtins.a"
config.name_suffix = "-ohos-sdk15"
config.test_exec_root = str(build)
config.test_format = lit.formats.ShTest(execute_external=False)
config.host_os = "Linux"
config.is_msvc = False
config.builtins_is_msvc = False
config.builtins_build_crt = True
config.compiler_rt_libdir = str(libdir)
config.compiler_rt_src_root = str(project / "compiler-rt")
config.builtins_lit_source_dir = str(project / "compiler-rt/test/builtins/Unit")
config.target_suffix = ""
config.clang = os.environ.get("OHOS_TEST_CC", str(llvm / "bin/clang"))
intrinsics = Path(subprocess.check_output([config.clang, "-print-resource-dir"], text=True).strip()) / "include"
config.cxx_mode_flags = ["--driver-mode=g++", "-nostdinc++", "-isystem",
                         str(sdk / "llvm/include/libcxx-ohos/include/c++/v1")]
config.debug_info_flags = ["-g"]
config.sanitizer_cxx_lib = "libc++"
config.emulator = "hdc"
config.target_cflags = shlex.join([
    "--target=aarch64-unknown-linux-ohos", "--sysroot=" + str(sdk / "sysroot"),
    "-B" + str(sdk / "llvm/bin"), "-O3", "-fPIC", "-fno-stack-protector",
    "-nobuiltininc", "-isystem", str(intrinsics),
    "-resource-dir=" + str(resource), "--ld-path=" + str(llvm / "bin/ld.lld"),
    "-L" + str(sdk / "llvm/lib/aarch64-linux-ohos"), "-lc++", "-lpthread", "-DCOMPILER_RT_HAS_FLOAT16"])
members = subprocess.check_output([str(llvm / "bin/llvm-ar"), "t", str(archive)], text=True)
features = sorted({"librt_has_" + item.split(".")[0] for item in members.splitlines()})
config.builtins_lit_source_features = ";".join(features)
config.available_features.update(["ohos", "clang", "aarch64-target-arch", "target=aarch64-unknown-linux-ohos", "native-run"])
config.environment["PATH"] = str(llvm / "bin") + os.pathsep + config.environment["PATH"]
executor = [sys.executable, str(project / "libcxx/utils/hdc.py"),
            "--device", os.environ["OHOS_TEST_DEVICE"], "--remote-root", os.environ["OHOS_TEST_ROOT"],
            "--audit", str(build / "executions.jsonl")]
config.substitutions.append(("%run_nomprotect ", shlex.join(executor) + " --execdir %T -- "))
config.substitutions.append(("%run ", shlex.join(executor) + " --execdir %T -- "))
lit_config.load_config(config, str(project / "compiler-rt/test/builtins/Unit/lit.cfg.py"))
