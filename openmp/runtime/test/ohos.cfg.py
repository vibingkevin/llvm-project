# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Exercise the SDK's static OpenMP runtime against the device ROM."""
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import lit.llvm

sdk = Path(os.environ['OHOS_SDK'])
llvm = Path(os.environ['LLVM_HOME'])
project = Path(__file__).resolve().parents[3]
build = Path(os.environ['OHOS_TEST_BUILD'])
cc = os.environ.get('OHOS_TEST_CC', str(llvm / 'bin/clang'))
resource = sdk / 'llvm/lib/clang/15.0.4'
intrinsics = Path(subprocess.check_output([cc, '-print-resource-dir'], text=True).strip()) / 'include'
config.test_c_compiler = cc
config.test_cxx_compiler = shlex.join([cc, '--driver-mode=g++', '-nostdinc++', '-isystem', str(sdk / 'llvm/include/libcxx-ohos/include/c++/v1')])
config.test_compiler_features = ['clang']
config.test_compiler_has_omp_h = False  # Always use the SDK header with its runtime.
config.test_filecheck = str(llvm / 'bin/FileCheck')
config.test_not = str(llvm / 'bin/not')
config.test_openmp_flags = '-fopenmp -static-openmp'
config.test_extra_flags = shlex.join(['--target=aarch64-unknown-linux-ohos', '--sysroot='+str(sdk/'sysroot'), '-nobuiltininc', '-isystem', str(intrinsics), '-resource-dir='+str(resource), '--ld-path='+str(llvm/'bin/ld.lld'), '-L'+str(sdk/'llvm/lib/aarch64-linux-ohos'), '-O3', '-fPIC', '-lc++', '-lpthread'])
config.libomp_obj_root = str(build)
config.library_dir = str(sdk / 'llvm/lib/aarch64-linux-ohos')
config.omp_header_directory = str(sdk / 'llvm/include')
config.operating_system = 'Linux'
config.target_triple = 'aarch64-unknown-linux-ohos'
config.using_hwloc = False
# SDK archive contains the OMPT callback machinery; the tests validate it.
config.has_ompt = True
config.has_ompx_taskgraph = False
config.has_libm = True
config.has_libatomic = False
config.is_standalone_build = True
config.has_omit_frame_pointer_flag = True
config.target_arch = 'aarch64'
config.compiler_frontend_variant = 'GNU'
config.compiler_simulate_id = ''
config.environment['OMP_NUM_THREADS'] = '4'
lit.llvm.initialize(lit_config, config)
lit_config.load_config(config, str(Path(__file__).with_name('lit.cfg')))
executor = [sys.executable, str(project/'libcxx/utils/hdc.py'), '--device', os.environ['OHOS_TEST_DEVICE'], '--remote-root', os.environ['OHOS_TEST_ROOT'], '--execdir', '%T', '--retrieve-prefix', '%t', '--stable-workdir', '--audit', str(build/'executions.jsonl')]
if 'OHOS_TEST_PROCESS_SUPERVISOR' in os.environ:
    executor += ['--process-supervisor', os.environ['OHOS_TEST_PROCESS_SUPERVISOR']]
names = {'LD_PRELOAD'}
for path in Path(__file__).parent.rglob('*'):
    if path.suffix in ('.c', '.cpp', '.h'):
        names.update(re.findall(r'\b(?:OMP|KMP|GOMP)_[A-Z0-9_]+', path.read_text(errors='replace')))
for name in sorted(names):
    executor += ['--forward-env', name]
config.substitutions = [(key, shlex.join(executor)+' -- %t' if key == '%libomp-run' else value) for key, value in config.substitutions]
config.available_features.add('ohos')

wrapper = shlex.join([sys.executable, str(project/'compiler-rt/test/ohos-clang.py'),
                      '--compiler', cc, '--execdir', '%T', '--prefix', '%t',
                      '--remote-root', os.environ['OHOS_TEST_ROOT'], '--'])
config.substitutions = [(key, value.replace(cc, wrapper, 1)) for key, value in config.substitutions]
