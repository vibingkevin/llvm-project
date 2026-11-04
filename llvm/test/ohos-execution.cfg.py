# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Run LLVM execution tools on OHOS, with host IR preparation and FileCheck."""
import os
from pathlib import Path
import shlex
import sys

project = Path(__file__).resolve().parents[2]
llvm = Path(os.environ['LLVM_HOME'])
build = Path(os.environ['OHOS_TEST_BUILD'])
remote = os.environ['OHOS_TEST_ROOT'].rstrip('/')
# Use the cross build's feature settings, but host tools for IR preparation.
# The caller supplies the original generated site configuration.
site = Path(os.environ['OHOS_LLVM_SITE_CONFIG']).read_text()
header = site.split('# Let the main config do the real work.')[0]
exec(compile(header, os.environ['OHOS_LLVM_SITE_CONFIG'], 'exec'))
config.llvm_tools_dir = str(llvm / 'bin')
config.host_arch = 'AArch64'
config.host_triple = config.target_triple = 'aarch64-unknown-linux-ohos'
config.native_target = 'AArch64'
config.targets_to_build = 'AArch64'
lit_config.load_config(config, str(project / 'llvm/test/lit.cfg.py'))
config.test_exec_root = str(build)
config.name = 'LLVM-OHOS-Execution'
executor = [sys.executable, str(project / 'libcxx/utils/hdc.py'),
            '--device', os.environ['OHOS_TEST_DEVICE'], '--remote-root', remote,
            '--execdir', '%T', '--retrieve-prefix', '%t', '--stable-workdir',
            '--path-map', str(project / 'llvm/test') + '=' + remote + '/source',
            '--audit', str(build / 'executions.jsonl')]
if 'OHOS_TEST_PROCESS_SUPERVISOR' in os.environ:
    executor += ['--process-supervisor', os.environ['OHOS_TEST_PROCESS_SUPERVISOR']]
rewritten = []
for key, value in config.substitutions:
    for tool in ['lli-child-target', 'llvm-jitlink-executor', 'llvm-rtdyld', 'llvm-jitlink', 'lli']:
        host = str(llvm / 'bin' / tool)
        if host not in value:
            continue
        target = remote + '/bin/' + tool
        if tool in ['lli-child-target', 'llvm-jitlink-executor']:
            value = value.replace(host, target)
        else:
            command = shlex.join(executor + ['--', target])
            if tool == 'lli':
                command += ' -O3'
            value = value.replace(host, command)
    for tool, flag in [("llc", "-mtriple"), ("llvm-mc", "-triple")]:
        host = str(llvm / "bin" / tool)
        value = value.replace(host, host + " " + flag + "=aarch64-unknown-linux-ohos")
    rewritten.append((key, value))
config.substitutions = rewritten
config.available_features.add('native')
config.available_features.add('ohos')
