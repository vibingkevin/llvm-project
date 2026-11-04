# Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Test the DevEco headers against the ROM libraries, without building a libc++.

OHOS_TEST_SOURCE may select tests matching the SDK libc++ version. It contains
libcxx/test and libcxx/utils; no headers or runtime libraries are taken from it.
"""
import importlib.util
import os
from pathlib import Path
import shlex
import sys

sdk = Path(os.environ["OHOS_SDK"])
llvm = Path(os.environ["LLVM_HOME"])
project = Path(__file__).resolve().parents[3]
source = Path(os.environ.get("OHOS_TEST_SOURCE", project))
suite = os.environ.get("OHOS_TEST_SUITE", "libcxx")
build = Path(os.environ["OHOS_TEST_BUILD"])
build.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(source / "libcxx/utils"))
# LLVM 15's test runner only uses pipes.quote, removed in Python 3.13.
if importlib.util.find_spec("pipes") is None:
    compat = build / "python-compat"
    compat.mkdir(exist_ok=True)
    (compat / "pipes.py").write_text("from shlex import quote\n")
    sys.path.insert(0, str(compat))
import libcxx.test.format
import libcxx.test.params
import libcxx.test.features
try:
    from libcxx.test.newconfig import configure
except ImportError:
    from libcxx.test.config import configure

config.name = suite + "-ohos-rom"
config.test_source_root = str(source / suite / "test")
config.test_exec_root = str(build)
config.test_format = libcxx.test.format.CxxStandardLibraryTest()
config.recursiveExpansionLimit = 10

headers = sdk / "llvm/include/libcxx-ohos/include/c++/v1"
libs = sdk / "llvm/lib/aarch64-linux-ohos"
common = ["--target=aarch64-unknown-linux-ohos", "--sysroot=" + str(sdk / "sysroot"),
          "-B" + str(sdk / "llvm/bin"), "-fPIC", "-fno-stack-protector",
          "-resource-dir=" + str(sdk / "llvm/lib/clang/15.0.4")]
compile_flags = ["-O3", "-nostdinc++", "-isystem", str(headers),
                 "-I" + str(source / "libcxx/test/support")]
link_flags = ["--ld-path=" + str(llvm / "bin/ld.lld"), "-L" + str(libs), "-lc++", "-lpthread"]
if suite == "libcxxabi":
    compile_flags += ["-D_LIBCPP_ENABLE_CXX17_REMOVED_UNEXPECTED_FUNCTIONS",
                      "-I" + str(source / "libcxx/src")]
if suite == "libunwind":
    compile_flags += ["-funwind-tables"]
    link_flags += ["-Wl,--export-dynamic", "-ldl"]
executor = [sys.executable, str(project / "libcxx/utils/hdc.py"),
            "--device", os.environ["OHOS_TEST_DEVICE"],
            "--remote-root", os.environ["OHOS_TEST_ROOT"],
            "--audit", str(build / "executions.jsonl")]
if "OHOS_TEST_UID" in os.environ:
    executor += ["--uid", os.environ["OHOS_TEST_UID"], "--run-as", os.environ["OHOS_TEST_RUN_AS"]]
config.substitutions += [
    ("%{cxx}", shlex.quote(os.environ.get("OHOS_TEST_CXX", str(llvm / "bin/clang++")))),
    ("%{flags}", shlex.join(common)),
    ("%{compile_flags}", shlex.join(compile_flags)),
    ("%{link_flags}", shlex.join(link_flags)),
    ("%{benchmark_flags}", ""),
    ("%{exec}", shlex.join(executor) + " --execdir %T --"),
    ("%{executor}", shlex.join(executor)),
    ("%{libcxx}", str(source / "libcxx")),
    ("%{libcxx-dir}", str(source / "libcxx")),
    ("%{include}", str(headers)),
    ("%{include-dir}", str(headers)),
    ("%{target-include}", str(headers)),
    ("%{target-include-dir}", str(headers)),
    ("%{lib}", str(libs)),
    ("%{lib-dir}", str(libs)),
    ("%{test-tools-dir}", str(build / "tools")),
    ("%{python}", shlex.quote(sys.executable)),
]
lit_config.params.setdefault("target_triple", "aarch64-unknown-linux-ohos")
lit_config.params.setdefault("std", "c++17")
lit_config.params.setdefault("enable_warnings", "False")
lit_config.params.setdefault("enable_experimental", "False")
lit_config.params.setdefault("using_system_stdlib", "True")
lit_config.params.setdefault("use_system_cxx_lib", "True")
configure(libcxx.test.params.DEFAULT_PARAMETERS, libcxx.test.features.DEFAULT_FEATURES,
          config, lit_config)
# SDK15 selects pthread in __config rather than its generated __config_site.
# The old feature probe includes only __config_site and otherwise skips two
# usable pthread interoperability tests.
from libcxx.test.dsl import compilerMacros, sourceBuilds
sdk_macros = compilerMacros(config, flags="-include __config")
if "_LIBCPP_HAS_THREAD_API_PTHREAD" in sdk_macros:
    config.available_features.add("libcpp-has-thread-api-pthread")
if "__cpp_sized_deallocation" in sdk_macros:
    config.available_features.add("has-sized-deallocation")
if sourceBuilds(config, "#include <functional>\nint main() { std::function<void()> f; }",
                ["-std=c++03"]):
    config.available_features.add("cxx03-std-function")
