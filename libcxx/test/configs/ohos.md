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
  --filter='\.pass\.cpp$' --filter-out='\.(compile|link)\.pass\.cpp$' \
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

## 本轮 O3 结果与真实限制

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
