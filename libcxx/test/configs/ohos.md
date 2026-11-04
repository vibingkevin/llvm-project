# 测试 DevEco 头文件与 OHOS ROM 库

`ohos-system.cfg.py` 不构建或部署 libc++，编译使用 Command Line Tools 的 libc++ 头文件，链接使用同一 SDK 的库，设备加载 ROM 中的库。LLVM 编译器来自 Kotlin/llvm-project 的固定提交。系统库测试源码选择与 SDK libc++ 主版本相符的测试，避免把 LLVM21 新增标准库 API 当作旧库回归。

本次 SDK `_LIBCPP_VERSION=15004`。测试源码来自 `https://gitcode.com/openharmony/third_party_llvm-project.git`，使用 OHOS LLVM15 提交 `18c19dbb934e523b1ec68aa6b03af3c9c411d8a8`，需取 `libcxx/test`、`libcxx/utils`、`libcxx/src`、`libcxxabi/test`、`libcxxabi/src`、`libunwind/test`、`libunwind/src`。src 只为引用私有实现的测试提供辅助源码，不从这些树替换 SDK 安装头或部署运行库；此类测试不能单独证明 ROM 内部实现正确。

在测试源码根目录应用 `ohos-sdk15-support.patch`。补丁修正驱动和测试前提：用 `__GLIBC__` 识别 glibc，避免把 OHOS 的兼容宏误认作 glibc；调用 lit21 内部 shell 时关闭调试输出包装，避免编译器宏探测得到空结果。Python3.13+ 删除的 pipes.quote 由配置中的 shlex.quote 兼容模块处理。它还用 POSIX shell 运行输入输出包装脚本，保留 O3 栈展开测试要求的递归帧并按返回地址前一字节查符号；涉及替换 new/delete 的测试在 main 开始后计数，并阻止待测分配被优化删除。原有功能断言不删除。专门要求 ROM 全局初始化零分配的测试保留失败。

设置绝对路径 `OHOS_SDK`、`LLVM_HOME`、`OHOS_TEST_SOURCE`、`OHOS_TEST_BUILD`、`OHOS_TEST_DEVICE`、`OHOS_TEST_ROOT`。`OHOS_TEST_SOURCE` 是上述 LLVM15 测试树；后两项分别是完整 HDC ID、本会话独占设备目录。创建构建目录的 `lit.site.cfg.py`，内容为：

```python
lit_config.load_config(config, "/absolute/llvm-project/libcxx/test/configs/ohos-system.cfg.py")
```

运行型 libc++ 主组：

```sh
python3 "$LLVM_SOURCE/llvm/utils/lit/lit.py" -v -j4 \
  --filter='\.pass\.cpp$|\.sh\.cpp$' --filter-out='\.(compile|link)\.pass\.cpp$' \
  -o "$OHOS_TEST_BUILD/results.json" "$OHOS_TEST_BUILD"
```

另外枚举 `.sh.cpp` 中使用 `%{exec}`/`%{run}` 的用例。纯编译、诊断验证及 ObjC 平台组不计入 OHOS 真机覆盖。编译/验证在 host；executor 调用的目标程序在设备实际执行。HDC 原始退出码与传输错误写入 executions.jsonl，不能把 HDC 命令自身退出 0 当作程序成功。

libc++abi、libunwind 分别设置 `OHOS_TEST_SUITE=libcxxabi` 或 `libunwind`，使用独立 build 和设备目录，沿用同一配置运行全部测试。主配置使用 `-O3`、C++17；个别用例保留明确要求的测试开关。不支持项按用例原本的 REQUIRES/UNSUPPORTED 与实际探测判定，不能整组隐藏失败。

builtins 的 site 配置加载 `compiler-rt/test/builtins/ohos.cfg.py`。它链接 SDK15 的 builtins archive，以真实 archive 成员确定 librt_has_*；不重建 LLVM21 运行库。包括 SDK CRT 初始化、缓存刷新及 C/C++ 异常跨帧清理。

配套 llvm-test-suite 的部署、输出合并和跨 Clang15/21 ABI 探针见该仓库 `cmake/toolchains/ohos.md`。`libcxx/utils/hdc_test.py` 检查二进制 stdin、独立/合并输出、路径映射和真实退出码。

## 文件权限用例

root 会绕过 chmod 构造的拒绝访问条件，不能据此跳过权限断言。用同一 SDK 编译 `libcxx/utils/ohos-run-as.c`，推到本会话设备目录并赋予执行权限，设置 `OHOS_TEST_UID=2000` 和 `OHOS_TEST_RUN_AS=<设备上的执行器路径>` 后运行 libc++ 主组；也可单独复测 filesystem 组。执行器只更改每个临时测试目录的属主，随后清空附加组、setgid/setuid 并 exec 测试；不修改设备全局权限或 ROM。原始 root 失败与普通用户复测分别保留。


```sh
"$LLVM_HOME/bin/clang" --target=aarch64-unknown-linux-ohos \
  --sysroot="$OHOS_SDK/sysroot" -B"$OHOS_SDK/llvm/bin" \
  -resource-dir="$OHOS_SDK/llvm/lib/clang/15.0.4" \
  --ld-path="$LLVM_HOME/bin/ld.lld" -L"$OHOS_SDK/llvm/lib/aarch64-linux-ohos" \
  -O3 -fPIC -fno-stack-protector "$LLVM_SOURCE/libcxx/utils/ohos-run-as.c" \
  -o "$OHOS_TEST_BUILD/ohos-run-as"
hdc -t "$OHOS_TEST_DEVICE" file send "$OHOS_TEST_BUILD/ohos-run-as" "$OHOS_TEST_RUN_AS"
hdc -t "$OHOS_TEST_DEVICE" shell "chmod 755 '$OHOS_TEST_RUN_AS'"
```

诊断对照设置 `OHOS_TEST_CXX=$OHOS_SDK/llvm/bin/clang++` 并使用独立 build/设备目录；其余头文件、链接器和 ROM 保持一致。不要把两套编译器探测出来的附加 flags 直接互换，例如 Clang15 的 `-fcoroutines-ts` 已不被 Clang21 接受。

`-Werror` 自测应单独传 `--param=enable_warnings=True`；这两项要求编译失败，属于 host 驱动自测，不是设备失败。C++03/C++11 function ABI 演示例先探测 SDK 是否提供 C++03 std::function，避免把前置 API 缺失冒充预期运行时 ABI 错误。线程 API 及 sized deletion 特征从实际 SDK 宏探测，不沿用旧编译器假设。

本轮不构建 LLVM21 libc++、sanitizer 或其他新的设备 runtime；这些库自身的测试不能替代对 ROM 库的验证。C++20/23、debug libc++、实验扩展及非 AArch64 用例按明确的配置/架构要求另列，不计入当前 setup 的真机覆盖。

## 历史 helper 路径 O3 结果与真实限制

2026-11-04，JB LLVM21 `c2e420df942a21f93c15248b4fb9259737fa58c1`，Command Line Tools Clang15.0.4 / SDK26，HarmonyOS 6.1.0.120、API24 的 AArch64 真机：

| 组 | 总数 | PASS | FAIL | UNSUPPORTED | XFAIL |
| --- | ---: | ---: | ---: | ---: | ---: |
| SDK15 libc++ 运行型及运行 shell 用例 | 6452 | 5100 | 26 | 1319 | 7 |
| libc++abi | 71 | 57 | 1 | 13 | 0 |
| libunwind | 12 | 6 | 5 | 1 | 0 |
| SDK15 builtins | 220 | 142 | 2 | 76 | 0 |

libunwind 的 6 个 PASS 中有 1 个仅编译，其他 PASS 均有目标程序设备执行记录。libc++ 的 7 个 XFAIL 中，5 个在 host 验证编译/链接预期错误，2 个在设备触发预期运行失败。编译期 static_assert 仍在 host 判断；程序实际执行不等于每个断言都在运行时判断。测试 timeit/fpcmp、lit 判定及输出比较也在 host。

不能据此宣称原 setup 完全兼容：

- `condition_variable/wait_until.pass.cpp` 暴露 ROM 的时钟状态问题。同一 pthread 条件变量先调用 `pthread_cond_clockwait(CLOCK_MONOTONIC)`，内部偏移 16 的字段从 0 变成 1；随后 realtime 截止时间的 `pthread_cond_timedwait` 不结束。新条件变量直接 realtime 等待正常。Clang15/21 均复现；ROM 反汇编显示 `str w8, [x0, #0x10]` 后直接跳转 `pthread_cond_timedwait`，没有恢复原时钟。保留 FAIL，不更换条件变量或跳过该阶段掩盖问题。
- 其余 25 个 libc++ FAIL 在相同 ROM 上用 SDK15 编译也失败：locale 初始化/访问的分配计数、错误消息与错误类别、C locale 宽字符行为、排序和货币格式、`+nan` 文本。它们不是本次 LLVM21 新增回归，也不能记为成功。
- builtins 的 `divsc3` 对分母 `inf + i*sNaN`（sNaN 位型 `0x7f800001`）返回 NaN 而非零；`multf3` 边界舍入实际末尾 `…fffb`，期望 `…fffc`。两套编译器结果相同，属于所用 SDK archive 的既有数值缺陷。
- libc++abi 缺 `pthread_cancel` 声明；libunwind 5 项缺 SDK 未提供的 `libunwind.h` / `__libunwind_config.h`，未补入另一版本公开头伪装通过。其他排除项逐项来自 C++17、实验/debug/无异常配置、locale、CPU 架构或 archive 的实际成员要求。

locale 可用性同时探测 `platform_support.h` 中的实际名称能否构造 ROM 的 C++ `std::locale`。仅 `setlocale()` 接受别名不够：11 个捷克语正则用例经两套编译器同机失败确认后判为不支持。能构造但格式断言失败的英语、中文 locale 没有被禁用。

C++03/C++11 `std::function` ABI 演示例按测试需求启用 SDK 已有的 `_LIBCPP_ENABLE_CXX03_FUNCTION` 宏，已在设备触发原来预期的 `x == 42` 断言错误。它的 XFAIL 不是由前置编译错误代替。

`libcxx/utils/ohos-clockwait-repro.c` 是上述 ROM 时钟问题的独立复现，使用与 ohos-run-as.c 相同的目标/SDK/链接参数并加 `-lpthread` 编译。无参数应正常超时并退出 0；传任意参数会先作单调时钟等待，再作实时时钟等待，受影响 ROM 上后一步不结束，运行时须用外部 `timeout`。无需部署任何 SDK 共享库。

配套 test-suite 的 O3 2029 项结果、两个 NEON 构建失败及 FMV 支持缺口，见 `vibingkevin/llvm-test-suite` 的 `test/ohos-rom-compat` 分支。这里的结果仅覆盖记录的 setup 和 ROM，不包含整个 LLVM host 回归测试或新 runtime 的质量验证。

## 普通 Kotlin 编译路径

与固定 Kotlin 分支的普通 `ClangArgs.Native` 一致，编译使用 LLVM21 自带 intrinsic 头，系统和 libc++ 头取 Command Line Tools SDK15；链接 resource-dir 取 SDK15。lit 的单条编译加链接命令通过 `-nobuiltininc` 和显式 intrinsic include 保持这两个阶段的头文件选择，避免 SDK15 与 LLVM21 的 stdint.h include guard 冲突。包含 cstdint、cstddef、vector、arm_neon 的普通分步命令与 lit 合并命令预处理结果逐字节一致。历史 compileWithClang helper 在编译期也选 resource15，与本轮分开统计。

`compiler-rt/test/ohos.cfg.py` 接入 SDK runtime 测试。site 文件加载该配置，`OHOS_COMPILER_RT_CONFIG` 指向 CMake 生成的 lit.common.configured，`OHOS_TEST_SUITE` 选择 asan、tsan、hwasan、ubsan、ubsan_minimal、profile、cfi、scudo、fuzzer、gwp_asan、lsan、shadowcallstack、sanitizer_common。默认 O3，保留用例显式优化选项。设置 `OHOS_TEST_CC`、`OHOS_TEST_TOOLS` 可以对照 SDK15。不重新编译 LLVM21 runtime 冒充 SDK/ROM 兼容。

`ohos-process.c` 在设备 waitpid，保留退出码和真实信号区别；`hdc.py` 可回传测试生成的数据、转发指定环境、按固定每例目录映射编译时嵌入路径，并以 host 原 ELF 还原设备回溯的源码位置。原始设备输出另存；不替换功能断言。远端跨 RUN 数据先回收到 host，再发送到相同路径，临时目录最终清理。

`openmp/runtime/test/ohos.cfg.py` 使用 SDK 静态 libomp 和 ROM libc++；不部署 libomp.so。`llvm/test/ohos-execution.cfg.py` 将 lli、llvm-jitlink、llvm-rtdyld 放到真机，IR 准备和 FileCheck 留在 host，覆盖 ExecutionEngine 及组外直接使用这些执行工具的用例。执行器支持二进制输入、输出顺序、真实信号、文件回传、稳定路径、子工作目录和空结果归档，均有真机契约测试。

判定时区分默认 Kotlin、cinterop/native 依赖和显式诊断插桩。固定分支 OHOS 的 supportedSanitizers 为空；TSan/HWASan 不能标成普通 Kotlin 默认触发。PGO 最小复现已确认 LLVM21 插桩与 SDK15 profile runtime 的数据不兼容，使用 llvm-profdata15 也不能恢复；默认 Kotlin 不启用这条插桩路径。


### 运行证据与 host 工具边界

profile 测试通过 `GCOV_PREFIX/GCOV_PREFIX_STRIP` 将编译时嵌入的 host gcda 路径映射到本例设备目录；TMPDIR、profile 模式和 value profiling 环境变量显式转发。生成数据回传后再由 host 工具检查，不在 host 直接运行目标 ELF。CFI 的 `ohos-sanstats.py` 只在临时副本中映射统计文件内的模块文件名，地址及计数原样保留，原始设备文件不修改。设备输出中的栈帧及 CFI note 使用对应 host ELF 符号化，原输出另存。

设备生成的绝对符号链接只有指向本例工作目录时才映射成 host 内部相对链接，解包仍使用安全路径检查。readlink/readlinkat 的断言在设备完成，回传过程不能制造假失败。LLVM remote MCJIT 测试显式传递目标 lli-child-target；遗漏子进程参数导致的早期失败不能用 XFAIL 掩盖。

libc++ 的 host GDB pretty-printer 自测不会直接在 x86 host 启动 OHOS ELF，因此不提供 `host-has-gdb-with-python` feature。warnings 自测、空 RUN 自测和其他编译检查与 ROM 运行结果分开。15 对照替换编译器及对应 profile 工具，保持 SDK、ROM 和固定链接器一致；它不是另一次完整 LLVM15 工具链质量测试。

PGO 代表例 binary-id-padding 的 Clang21 产物在真机以 SIGSEGV 退出，Clang15 产物退出 0；额外信号定位探针得到 PC 位于 SDK15 `initializeValueProfRuntimeRecord`、LR 位于 `writeOneValueProfData`。LLVM21 profile 记录新增 BitmapPtr/NumBitmapBytes，与旧 runtime 布局不兼容。最小 raw profile 即使用 profdata15 也无法正确读取，不是仅换 host 工具版本就可解决。


OpenMP 的内部跳过与 lit 的 PASS 分开：均匀拓扑要求不适用于此异构 CPU，部分原子专用测试在 AArch64 直接跳过。kmp-affinity 在21 O3实际执行时发现 libomp 的12个单CPU place 与 sysfs 的8个 core 不同；15 O3提前调用 omp_get_place_num，引起线程绑定，随后全CPU掩码检查跳过。15 O0保留原检查顺序，实机复现相同拓扑差异。因此15 O3的退出0不能作为该功能已通过的证据，也不能将此差异直接归为21独有回归。

`profile/Posix/instrprof-dlopen-norpath.test` 内部通过 system 调用 llvm-profdata，需要同版本的目标工具。设置 `OHOS_TEST_TOOL_DIR` 指向预先部署的 AArch64 llvm-profdata 目录后才提供该 feature；部署的是检查工具，不是替换 ROM runtime。本轮 LLVM21 版本已构建并部署，目标测试真实 SIGSEGV；15 对照未部署同版本目标工具，明确标为前提缺失，不把历史 host 执行错误算作15失败。

sanitizer 日志测试回传 `sanitizer.log.*.txt`。suffix-log-path 的额外设备探针确认日志选项及映射路径正确，但 SDK15 runtime 仍将栈输出到 stderr、未生成指定日志，两套编译器相同；保留失败并旁置，不能靠更改 FileCheck 输入伪装通过。
