---
name: c-regression-impact-scan
description: Use in Claude Code whenever the user asks whether the latest change, recent modification, last commit, HEAD commit, or HEAD~1..HEAD change affects existing features, old features, legacy behavior, regression risk, subsystem behavior, public C interfaces, memory leaks, memory safety, ABI/layout, concurrency, error handling, ownership/lifetime, macro/config behavior, protocol compatibility, state timing, callback dispatch, performance/resource usage, security boundaries, build/deploy behavior, or stable functionality in a C codebase. Trigger for natural requests like "分析最近一次修改对已有功能的影响", "检查最近提交有没有影响老功能", "看这次改动是否有回归风险", "分析这个子系统最近修改的影响", or "检查 C 代码改动是否可能导致内存泄漏". Prioritize local CodeGraph impact scanning, then fall back to ripgrep and deterministic architecture risk rules. The final deliverable must be a Chinese Markdown detection report.
---

# C Regression Impact Scan

## Purpose

Use this skill in Claude Code to answer: "Did the latest C change introduce architecture-level regression risk for existing subsystem behavior?"

The target environment is a large commercial C codebase, usually intranet-only, often on Windows, and possibly handled by a weak AI agent. Do not ask the model to read the whole repository. Use local tools and deterministic rules first, then summarize the structured output.

## Default Workflow

1. Confirm the current directory is the target git repository.
2. Confirm `codegraph` or `codegraph.exe` is installed. CodeGraph is the primary backend for this skill.
3. Choose the subsystem directory to scan, such as `subsys/net` or `product/http`.
4. Run the bundled scanner from the repository root with `--subsystem`:

   ```powershell
   python path\to\c-regression-impact-scan\scripts\c_impact_scan.py --range HEAD~1..HEAD --subsystem subsys\net --codegraph-mode prefer
   ```

   On macOS or Linux:

   ```bash
   python3 path/to/c-regression-impact-scan/scripts/c_impact_scan.py --range HEAD~1..HEAD --subsystem subsys/net --codegraph-mode prefer
   ```

5. For first-time setup, if the user has approved indexing or the repository policy allows it, add `--init-codegraph`:

   ```powershell
   python path\to\c-regression-impact-scan\scripts\c_impact_scan.py --range HEAD~1..HEAD --subsystem subsys\net --codegraph-mode prefer --init-codegraph
   ```

6. If the scan must fail when CodeGraph is unavailable, use:

   ```powershell
   python path\to\c-regression-impact-scan\scripts\c_impact_scan.py --range HEAD~1..HEAD --subsystem subsys\net --codegraph-mode required
   ```

7. Read `.impact-scan/risk_report.md` first.
8. If more evidence is needed, inspect these generated files:
   - `.impact-scan/scan_config.json`
   - `.impact-scan/codegraph_status.json`
   - `.impact-scan/diff_summary.json`
   - `.impact-scan/changed_symbols.json`
   - `.impact-scan/impact_paths.json`
   - `.impact-scan/references.json`
   - `.impact-scan/subsystem_impact.json`
   - `.impact-scan/risk_items.json`
   - `.impact-scan/architecture_risk_summary.json`
   - `.impact-scan/manual_review.json`
9. Produce a final Chinese Markdown detection report. Use `.impact-scan/risk_report.md` as the base report, refine it if needed, and ensure the final answer points to the generated `.md` file. The Markdown report must include:
   - overall risk: high, medium, or low
   - whether CodeGraph was used successfully
   - high-risk changed files and symbols
   - affected legacy subsystem candidates
   - evidence paths from changed item to references
   - memory-lifetime and leak-risk findings
   - architecture risk categories
   - mandatory manual-review items
   - suggested regression tests
   - scan limitations and confidence

The final deliverable is not just a chat summary. It must be a Chinese Markdown report file, normally `.impact-scan/risk_report.md`.

Encoding requirements:

- The Chinese Markdown report must be written as UTF-8 with BOM to reduce garbled text in Windows viewers.
- JSON artifacts remain standard UTF-8.
- Subprocess output from Git, CodeGraph, and rg must be decoded as UTF-8 first with tolerant fallback, avoiding Windows GBK `UnicodeDecodeError` failures.

## Subsystem Configuration

For better legacy-impact results, add `.impact-scan.yml` inside the subsystem directory, not the repository root. The parser is intentionally simple for Python 3.6 and offline Windows environments; use top-level list keys:

```text
repo/
  subsys/net/
    .impact-scan.yml
    include/
    legacy/
```

```yaml
public_interfaces:
  - include/
  - sdk/include/
legacy_paths:
  - legacy/
  - product/stable/
high_risk_paths:
  - platform/
  - protocol/
  - storage/
  - upgrade/
memory_sensitive_paths:
  - core/session/
  - buffer/
  - memory/
low_risk_paths:
  - tests/
  - docs/
```

Paths in the subsystem config are relative to the subsystem directory. With `--subsystem subsys/net`, `include/` becomes `subsys/net/include/` internally.

The scanner also accepts `.impact-scan.json` inside the subsystem directory for stricter internal configuration. Prefer subsystem configuration over asking Claude Code to infer old-feature boundaries from the whole repository.

## Tool Priority

Prefer tools in this order. Do not skip CodeGraph if it is installed.

1. `codegraph` or `codegraph.exe`.
2. `rg` or `rg.exe`.
3. Universal Ctags, if available.
4. Python fallback rules in the bundled scanner.

Do not require Linux-only tools such as `bash`, `sed`, `awk`, `xargs`, `find`, or `cscope` in the Windows baseline. If Git Bash or WSL exists, it may be used as an optional enhancement only.

## CodeGraph Use

If `codegraph` is available, use it before `rg`. Treat it as the primary impact query backend, not as the final decision maker.

Useful commands vary by installed version. Try non-destructive help first:

```powershell
codegraph --help
codegraph impact --help
```

If `.codegraph` does not exist, ask before running expensive indexing on very large repositories unless the user already requested a scan or repository policy allows indexing. In automated CI, indexing may be allowed by configuration.

CodeGraph is useful for:

- changed function impact
- callers and callees
- include/import relationships
- subsystem spread

Do not claim CodeGraph proves a change is safe. In C code, macro expansion, conditional compilation, function pointers, callbacks, and platform-specific build flags can hide impact.

## Claude Code Guidance

Claude Code should keep the interaction simple:

1. Run the scanner.
2. Read the generated Markdown and JSON artifacts.
3. Ensure `.impact-scan/risk_report.md` exists and is the final Chinese Markdown detection report.
4. Avoid opening broad repository files unless a specific risk item needs evidence.

If CodeGraph is missing, tell the user clearly and either:

- stop, when `--codegraph-mode required` was requested
- continue with lower confidence, when `--codegraph-mode prefer` was used

For weak local models, rely on `.impact-scan/risk_items.json` and `.impact-scan/risk_report.md` more than free-form code reading.

## Risk Rules

Use deterministic scoring before model reasoning. Treat these as default weights:

- changed public `.h` file: +4
- changed path containing `include`, `common`, `public`, `api`, `lib`, `platform`, `protocol`, `sdk`, or `adapter`: +3
- function signature or declaration changed: +4
- `struct`, `union`, `enum`, or `typedef` changed: +4
- macro or conditional compilation changed: +3
- function pointer, callback, ops table, or vtable-like table changed: +4
- memory allocation/lifetime related change: +5
- memory-sensitive path change: +2 to +3
- legacy reference from CodeGraph or `rg`: +4
- configured high-risk path change: +3
- semantic behavior keyword changed, such as return/error/NULL/size/lock: +2
- global variable changed: +2
- changed symbol referenced by 10 or more files: +3
- changed symbol referenced across 3 or more top-level subsystems: +3
- build file or feature switch changed: +3

Architecture risk category weights:

- `memory_safety`: +5
- `memory_leak`: +5
- `abi_layout`: +5
- `concurrency`: +4
- `error_handling`: +3
- `ownership_lifetime`: +4
- `macro_config`: +3
- `protocol_compatibility`: +4
- `state_machine_timing`: +4
- `callback_dispatch`: +4
- `performance_resource`: +3
- `security_boundary`: +5
- `build_deploy`: +3

Risk level:

- `high`: score >= 8, or any public header/API change with broad references
- `medium`: score 4-7
- `low`: score 0-3 and narrow local references

Confidence:

- `high`: CodeGraph or strong index exists and references were found
- `medium`: `rg` references and file-level evidence exist
- `low`: only diff heuristics were available, or generated references are sparse

## C-Specific Review Focus

发现以下 C 风险时必须在报告中突出说明：

- 公共头文件变化
- 结构体布局变化，包括字段顺序和字段类型变化
- 枚举值变化
- 宏默认值变化
- `#ifdef` / `#if` 行为变化
- 回调注册和函数指针表变化
- 分配/释放所有权变化以及潜在泄漏路径
- `malloc`, `calloc`, `realloc`, `strdup`, `free`, `release`, `destroy`, `cleanup`, `refcount`, buffer size, and error-exit path changes
- 错误码、返回值、所有权、生命周期或 buffer size 语义变化
- 老功能子系统使用的共享模块变化

## 架构风险类别

检测到以下类别时，必须写入中文 Markdown 报告：

- `memory_safety`: buffer overflow, out-of-bounds, use-after-free, double free, uninitialized memory, unsafe copy/format operations
- `memory_leak`: allocation/free imbalance, missing cleanup, refcount imbalance, `realloc` failure handling
- `abi_layout`: struct/union/enum/typedef layout, packing, alignment, exported symbol, or binary interface change
- `concurrency`: lock/unlock asymmetry, race condition, atomic/refcount behavior, thread/timer/interrupt interaction
- `error_handling`: changed return value, error code, `goto error`, `NULL` handling, cleanup path
- `ownership_lifetime`: ownership transfer, init/destroy order, retain/release, object lifetime across callbacks
- `macro_config`: macro default, feature flag, platform conditional, build-time behavior
- `protocol_compatibility`: wire format, version, endian, opcode, field meaning, persistent data compatibility
- `state_machine_timing`: state transition, event order, timer, timeout, retry, start/stop sequence
- `callback_dispatch`: function pointer table, ops table, handler registration, dispatch table
- `performance_resource`: CPU, memory peak, file/socket/thread/timer resources, loop complexity, lock contention
- `security_boundary`: auth, permission, input validation, path/command injection, integer or buffer overflow
- `build_deploy`: Makefile/CMake/link flags, exported symbols, install/deploy behavior, default build options

## 内存泄漏关注点

当报告标记 `memory-lifetime` 时，不要把它当成普通函数变化处理。需要要求或建议进行内存泄漏专项验证：

- 内存分配成功和失败路径
- 提前 `return` / `goto error` 清理路径
- 调用者和被调用者之间的所有权转移
- 引用计数递增和递减是否平衡
- buffer resize 和 `realloc` 错误处理
- callback 清理和模块卸载路径
- 重复调用或长时间运行的老功能路径

如果内网环境没有动态分析工具，建议对受影响老功能做定向压力循环和进程内存监控。

## Report Style

The output report must be Chinese Markdown. Keep these sections unless there is a strong reason to add more:

- `概要`
- `高/中风险项`
- `架构风险类别`
- `受影响子系统候选`
- `引用证据`
- `影响路径`
- `必须人工 Review`
- `内存泄漏关注点`
- `建议回归检查`
- `局限性`

Use evidence-backed language. Prefer:

> "This commit is high risk because `include/foo.h` changed and references were found in 7 subsystems."

Avoid:

> "This is safe."

When evidence is incomplete, say exactly why:

> "Confidence is medium because no compile database or semantic C index was available; macro-expanded paths were not verified."

## Windows Intranet Notes

Read `references/windows-deployment.md` when setting up the skill on Windows or packaging it for an offline server.
