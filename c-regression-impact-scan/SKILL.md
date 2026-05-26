---
name: c-regression-impact-scan
description: Use in Claude Code whenever the user asks whether the latest change, recent modification, last commit, HEAD commit, or HEAD~1..HEAD change affects existing features, old features, legacy behavior, regression risk, subsystem behavior, public C interfaces, memory leaks, memory safety, ABI/layout, concurrency, error handling, ownership/lifetime, macro/config behavior, protocol compatibility, state timing, callback dispatch, performance/resource usage, security boundaries, build/deploy behavior, or stable functionality in a C codebase. Trigger for natural requests like "分析最近一次修改对已有功能的影响", "检查最近提交有没有影响老功能", "看这次改动是否有回归风险", "分析这个子系统最近修改的影响", or "检查 C 代码改动是否可能导致内存泄漏". Prioritize local CodeGraph impact scanning, then fall back to ripgrep and deterministic architecture risk rules. The final deliverable must be a Chinese Markdown detection report.
---

# Guided C Regression Impact Scan

## Purpose

Use this skill in Claude Code to answer: "Did the latest C change introduce architecture-level regression risk for existing subsystem behavior?"

This is a **guided workflow skill** — the agent collects user focus, runs deterministic tools for evidence, applies fixed risk rules, and generates a template-based report. It does NOT ask the model to read the entire repository or independently judge "is this safe."

## Core Principle

```
用户给重点 → 工具产证据 → 规则做评分 → 模板写报告 → 模型少推理
```

The model orchestrates the steps. The Python scanner produces evidence. Deterministic rules produce scores. A template produces the final report. The model only summarizes and confirms.

## Non-Negotiable Deliverable

The final deliverable is always a Markdown file on disk:

```
.impact-scan/risk_report.md
```

Do not treat a terminal/chat summary as completion. Even when using guided mode, the agent must run the report step or one-shot scanner before the final reply. The final reply should mention the generated file path and a short summary only after `.impact-scan/risk_report.md` exists.

## Two Modes

### Default: Guided Mode (multi-step)

Best for interactive use with a local agent. The agent walks through each step with user confirmation at key checkpoints:

```
Step 0: Focus intake  → 用户提供重点
Step 1: Scope discovery → 发现扫描范围 → 用户确认
Step 2: Risk triage → 初步风险分诊
Step 3: Focused expansion → 定向扩展影响面
Step 4: Evidence review → 用户确认关键证据
Step 5: Final report → 生成最终报告
```

### Alternative: One-shot Mode

Best for CI or when the user says "直接生成报告":

```bash
python3 c-regression-impact-scan/scripts/c_impact_scan.py --range HEAD~1..HEAD --subsystem subsys/net
```

This runs all steps at once and outputs `.impact-scan/risk_report.md`.

## Guided Workflow

### Step 0: Focus Intake (用户提供重点)

Before scanning, ask the user what they care about. Guide them to provide a focus config. This reduces guesswork for weak models.

The user can provide focus via:

**Option A: Focus config file** (`.impact-scan-focus.yml` in repo root):

```yaml
subsystem: subsys/net
focus_symbols:
  - api_open
  - session_alloc
focus_risks:
  - memory_leak
  - abi_layout
  - protocol_compatibility
ignore_paths:
  - tests/
  - docs/
legacy_paths:
  - legacy/
  - stable/
public_interfaces:
  - include/
notes:
  - 老客户端 open/close 行为不能变
  - session 重复创建销毁不能泄漏
```

**Option B: CLI flags** (quick, no file needed):

```
--focus-symbols api_open,session_alloc
--focus-risks memory_leak,abi_layout
--ignore-paths tests/,docs/
```

If the user hasn't provided focus, ask:

> 请告诉我你最关心什么：
> - 哪些 subsystem 需要重点检查？
> - 哪些 symbol 不能出问题？
> - 哪些风险类别最关注（memory_leak / abi_layout / protocol_compatibility / ...）？
> - 哪些路径可以忽略（tests/ / docs/）？
> - 有什么项目特殊背景需要我知道？

The scanner will read focus from `.impact-scan-focus.yml` automatically. CLI flags override file config.

### Step 1: Scope Discovery (发现扫描范围)

Run the scanner to discover what changed:

```bash
python3 c-regression-impact-scan/scripts/c_impact_scan.py \
  --step discover --range HEAD~1..HEAD --subsystem subsys/net
```

This outputs `.impact-scan/scope_discovery.json`:

- changed files (C files, headers, build files, public interfaces)
- inferred subsystems

Present the summary to the user for confirmation:

> 本次变更涉及以下内容：
> - Changed files: 5
> - C/header files: 3
> - Public interface files: include/api.h
> - Inferred subsystems: subsys/net
>
> 是否按 subsys/net 扫描？有没有需要调整的子系统范围？

### Step 2: Risk Triage (初步风险分诊)

Run quick triage WITHOUT reference search. This only scores changed files/symbols using deterministic rules:

```bash
python3 c-regression-impact-scan/scripts/c_impact_scan.py \
  --step triage --range HEAD~1..HEAD --subsystem subsys/net
```

This outputs `.impact-scan/triage_summary.json`:

- high / medium / low risk counts
- focus symbol coverage (which found, which missing)
- expansion candidates (what would be expanded in Step 3)

Important: Step 2 does NOT search for references across the codebase. It only identifies risk signals in the diff itself. This keeps it fast.

### Step 3: Focused Expansion (定向扩展影响面)

Only expand references for:

- user-specified `focus_symbols`
- high-risk symbols (score >= 8)
- public interface symbols
- memory-lifetime symbols

Do NOT expand all changed symbols. This keeps reference search focused and fast:

```bash
python3 c-regression-impact-scan/scripts/c_impact_scan.py \
  --step expand --range HEAD~1..HEAD --subsystem subsys/net
```

This outputs `.impact-scan/expansion_summary.json`:

- which symbols were expanded and why
- reference counts per expanded symbol
- CodeGraph vs fallback hits

Tool strategy (internal, don't expose to user unless asked):

```
CodeGraph → rg fallback → heuristic only
```

If CodeGraph or rg fails, confidence is lowered — the report will state this explicitly. Don't fabricate impact paths.

### Step 4: Evidence Review (用户确认关键证据)

Before generating the final report, present key findings for user confirmation:

- Are the legacy paths correct?
- Are the public interfaces correct?
- Are the ignore paths correct?
- Do the impact paths match project reality?
- Which risk items should be emphasized in the report?

This step is critical for weak models — project knowledge lives with the user, not the agent.

If the user already asked to analyze the latest change and did not explicitly ask to pause for confirmation, continue to Step 5 after presenting the key evidence. Do not stop at a terminal/chat summary.

### Step 5: Final Report (生成最终报告)

Generate the Chinese Markdown report from all collected artifacts:

```bash
python3 c-regression-impact-scan/scripts/c_impact_scan.py \
  --step report --range HEAD~1..HEAD --subsystem subsys/net
```

This reads all `.impact-scan/*.json` artifacts and generates `.impact-scan/risk_report.md`.

The report includes:

- **概要**: overall risk, max score, confidence, CodeGraph status
- **用户重点关注覆盖**: which focus symbols found, which risks detected
- **分析分层**: CodeGraph / Heuristic / Manual Review
- **高/中风险项**: table of high and medium risk items
- **架构风险类别**: aggregated by category
- **受影响 subsystem 候选**: per-subsystem impact reasons, files, symbols, checks
- **Reference Evidence**: CodeGraph/rg reference counts
- **Impact Paths**: symbol → file → subsystem chains
- **必须人工 Review**: mandatory manual review items
- **内存泄漏关注点**: memory-lifetime specific findings
- **建议回归检查**: suggested regression tests
- **局限性**: scan limitations and confidence caveats

The report is written as UTF-8 with BOM for Windows compatibility.

## Focus Config Reference

### File: `.impact-scan-focus.yml`

```yaml
subsystem: subsys/net
focus_symbols:
  - api_open
  - session_alloc
focus_risks:
  - memory_leak
  - abi_layout
ignore_paths:
  - tests/
  - docs/
legacy_paths:
  - legacy/
public_interfaces:
  - include/
notes:
  - 老客户端 open/close 行为不能变
```

### CLI flags

| Flag | Example |
|------|---------|
| `--focus-symbols` | `api_open,session_alloc` |
| `--focus-risks` | `memory_leak,abi_layout` |
| `--ignore-paths` | `tests/,docs/` |
| `--focus` | path to `.impact-scan-focus.yml` |

CLI flags override file config.

## Subsystem Configuration

Place `.impact-scan.yml` or `.impact-scan.json` inside each subsystem directory:

```yaml
public_interfaces:
  - include/
  - sdk/include/
legacy_paths:
  - legacy/
  - stable/
high_risk_paths:
  - platform/
  - protocol/
  - storage/
memory_sensitive_paths:
  - core/session/
  - buffer/
low_risk_paths:
  - tests/
  - docs/
```

## Risk Rules (Deterministic Scoring)

### File-level weights

- changed public `.h` file: +4
- changed path matching `include/common/public/api/lib/platform/protocol/sdk/adapter`: +3
- configured high-risk path: +3
- configured legacy path: +3
- configured memory-sensitive path: +2
- build/feature file changed: +3
- large change (>= 80 lines): +2

### Symbol-level weights

- function declaration/definition changed: +4
- struct/union/enum/typedef changed: +4
- macro or conditional compilation changed: +3
- callback/function pointer pattern changed: +4
- global data changed: +2
- memory allocation/lifetime change: +5
- container ownership change (list/tree/hash/queue/map/cache): +5
- semantic behavior keyword changed: +2
- symbol in public/shared path: +3
- symbol in high-risk path: +3
- symbol in memory-sensitive path: +3
- legacy file reference: +4
- referenced by >= 10 files: +3
- spans >= 3 subsystems: +3

### Architecture risk category weights

| Category | Weight |
|----------|--------|
| `memory_safety` | +5 |
| `memory_leak` | +5 |
| `abi_layout` | +5 |
| `security_boundary` | +5 |
| `concurrency` | +4 |
| `ownership_lifetime` | +4 |
| `protocol_compatibility` | +4 |
| `state_machine_timing` | +4 |
| `callback_dispatch` | +4 |
| `error_handling` | +3 |
| `macro_config` | +3 |
| `performance_resource` | +3 |
| `build_deploy` | +3 |

### Risk levels

- **high**: score >= 8
- **medium**: score 4–7
- **low**: score 0–3

Scoring is triage only — not proof of defect. High score means "review this," not "this is broken."

## Three-Layer Analysis

### CodeGraph 层

Query function/symbol references, callers/callees, include/import relationships, and subsystem spread. Provides impact evidence. Does NOT prove safety — macro expansion, conditional compilation, function pointers, and callbacks can hide impact.

### Heuristic 层

Deterministic rules identify risk signals from names, paths, diff content, and categories. This is risk triage only. It can say "review this" but NOT "this is safe."

### Manual Review 层

For risks that static tools cannot resolve — pointer aliasing, ownership transfer, callback/async flow, struct field passing, error cleanup paths — write items into `必须人工 Review`. This reduces manual review scope, not replaces architect judgment.

## Architecture Risk Categories

| Category | Detects |
|----------|---------|
| `memory_safety` | buffer overflow, OOB, UAF, double free, unsafe copy/format |
| `memory_leak` | alloc/free imbalance, missing cleanup, refcount imbalance, container ops |
| `abi_layout` | struct/union/enum/typedef layout, packing, alignment, exported symbols |
| `concurrency` | lock/unlock asymmetry, race, atomic/refcount, thread/timer/interrupt |
| `error_handling` | return value, error code, goto error, NULL check, cleanup path |
| `ownership_lifetime` | ownership transfer, init/destroy order, retain/release, container insert/remove |
| `macro_config` | macro default, feature flag, platform conditional, build-time behavior |
| `protocol_compatibility` | wire format, version, endian, opcode, field meaning, persistent data |
| `state_machine_timing` | state transition, event order, timer, timeout, retry, start/stop |
| `callback_dispatch` | function pointer table, ops table, handler registration, dispatch |
| `performance_resource` | CPU, memory peak, file/socket/thread/timer, loop, lock contention |
| `security_boundary` | auth, permission, input validation, path/command injection, overflow |
| `build_deploy` | Makefile/CMake, link flags, exported symbols, install/deploy behavior |

## Memory Leak Focus

When report flags `memory-lifetime`, do not treat it as a normal function change. Require or suggest memory-leak-specific verification:

- allocation success and failure paths
- early return / goto error cleanup paths
- ownership transfer between caller and callee
- refcount increment/decrement balance
- buffer resize and realloc error handling
- container insert/remove ownership transfer (list_add, rb_insert, hash_add, queue_push, map_put, cache_insert, etc.)
- callback cleanup and module unload paths
- repeated-call or long-running legacy paths

## Report Style

Chinese Markdown, technical terms in English when clearer. Sections:

- 概要
- 用户重点关注覆盖
- 分析分层
- 高/中风险项
- 架构风险类别
- 受影响 subsystem 候选
- Reference Evidence
- Impact Paths
- 必须人工 Review
- 内存泄漏关注点
- 建议回归检查
- 局限性

Use evidence-backed language. When confidence is low, state why:

> Confidence is medium because no compile database or semantic C index was available.

## Agent Guidance

1. Collect user focus first (Step 0) — don't skip this.
2. Run `--step discover` and confirm scope with user.
3. Run `--step triage` for quick risk scoring.
4. Run `--step expand` for focused reference search.
5. Present key evidence for user confirmation (Step 4), but continue if the user asked for a complete analysis and did not ask to pause.
6. Run `--step report` to generate the final Markdown.
7. Verify `.impact-scan/risk_report.md` exists. If it does not exist, run one-shot mode as fallback.
8. Read `.impact-scan/risk_report.md` and summarize for the user.

Completion rule:

- Completed: `.impact-scan/risk_report.md` exists and the final reply includes its path.
- Not completed: only terminal/chat text was produced, or only JSON artifacts were produced.
- Recovery: run `python c-regression-impact-scan/scripts/c_impact_scan.py --step report --range HEAD~1..HEAD` from the target repo. If report artifacts are missing, run one-shot mode without `--step`.

If CodeGraph is missing, tell the user and either stop (`--codegraph-mode required`) or continue with lower confidence (`--codegraph-mode prefer`).

For weak local models, rely on `.impact-scan/risk_items.json` and `.impact-scan/subsystem_analysis.json` more than free-form code reading. The scanner produces structured evidence — use it.

## Windows Intranet Notes

- Python 3.6+ compatible
- No dependency on sed/awk/xargs/find/bash
- `risk_report.md` written as UTF-8 with BOM
- Subprocess output decoded UTF-8 first with tolerant GBK fallback
- Prefer `codegraph.exe` on Windows, fall back to `rg.exe`
