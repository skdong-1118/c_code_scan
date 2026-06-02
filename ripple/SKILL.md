---
name: ripple
description: Use in Claude Code whenever the user asks whether the current branch latest commit, last commit, HEAD commit, or HEAD~1..HEAD change affects existing features, old features, legacy behavior, regression risk, subsystem behavior, public C interfaces, memory leaks, memory safety, ABI/layout, error handling, ownership/lifetime, pointer alias/lifetime, callback dispatch, or stable functionality in a C codebase. Trigger for natural requests like "分析最近一次修改对已有功能的影响", "检查最近提交有没有影响老功能", "看这次改动是否有回归风险", "分析这个子系统最近修改的影响", or "检查 C 代码改动是否可能导致内存泄漏". Analyze only the current branch latest commit with range HEAD~1..HEAD; never analyze older commits, multiple commits, other branches, or arbitrary commit ranges. Use built-in risk categories only: memory_leak, memory_safety, abi_layout, pointer_alias_lifetime, error_handling, callback_dispatch. Require local CodeGraph impact scanning with --codegraph-mode required; do not use Grep, ripgrep, rg, or Claude Code's Grep tool for reference search. The final deliverable must be a Chinese Markdown detection report.
---

# Guided C Regression Impact Scan

## Purpose

Use this skill in Claude Code to answer: "Did the latest C change introduce architecture-level regression risk for existing subsystem behavior?"

Hard scope limit: this skill only analyzes the current branch latest commit. The commit range is fixed to:

```
HEAD~1..HEAD
```

Do not analyze older commits, multiple commits, other branches, merge-base ranges, or custom commit ranges. If the user asks for a different commit range, stop and explain that `ripple` is intentionally limited to the current branch latest commit.

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

Do not treat a terminal/chat summary as final completion. In interactive guided mode, checkpoint replies are allowed between steps, but the final completion reply is allowed only after the agent runs the report step and verifies `.impact-scan/risk_report.md` exists. The final completion reply should mention the generated file path and a short summary.

## Interaction Contract

Default behavior is **interactive guided mode**. After each scanner step, the agent must stop and wait for the user's confirmation before running the next step.

The agent may skip checkpoints only when the user clearly says one of:

- `直接生成报告`
- `不用确认`
- `全自动`
- `one-shot`
- `CI`

If the user's request is simply "分析最近一次修改对已有功能的影响", that means guided mode, not one-shot mode.

Checkpoint rule:

- Step 0 uses latest-commit inference and built-in risk categories; do not stop for user focus unless inference is clearly insufficient.
- Starting a new analysis must clear previous scan artifacts. The scanner clears the output directory at `discover` or one-shot start; do not manually delete artifacts before `triage`, `expand`, or `report` because those steps depend on earlier JSON files.
- Step 1 runs `discover`, summarizes scope, then waits for confirmation.
- Step 2 runs `triage`, summarizes risk counts and expansion candidates, then waits for confirmation.
- Step 3 runs `expand`, summarizes reference evidence and CodeGraph status, then waits for confirmation.
- Step 4 summarizes key evidence and waits for confirmation before final report.
- Step 5 runs `report`, verifies `.impact-scan/risk_report.md`, then sends the final completion reply with the path and short summary.

Do not run Step 1 through Step 5 in one uninterrupted sequence in guided mode.

## Two Modes

### Default: Interactive Guided Mode (multi-step)

Best for interactive use with a local agent. The agent walks through each step with user confirmation at key checkpoints:

```
Step 0: Focus intake  → 自动推断 scope / 使用内置风险项
Step 1: Scope discovery → 发现扫描范围 → 用户确认
Step 2: Risk triage → 初步风险分诊
Step 3: Focused expansion → 定向扩展影响面
Step 4: Evidence review → 用户确认关键证据
Step 5: Final report → 生成最终报告
```

### Alternative: One-shot Mode

Best for CI or when the user says "直接生成报告":

```bash
python3 ripple/scripts/ripple_scan.py --range HEAD~1..HEAD --subsystem subsys/net
```

This runs all steps at once and outputs `.impact-scan/risk_report.md`.

## Guided Workflow

### Step 0: Focus Intake (自动推断为主)

Do not ask the user to choose subsystem, focus symbols, focus risks, or ignore paths by default.

Default behavior:

- infer subsystem from the current branch latest commit changed files;
- do not require user-specified focus symbols;
- infer low-value ignore paths from changed files and configured low-risk paths;
- use the built-in enabled risk categories only.

Built-in enabled risk categories:

```text
memory_leak
memory_safety
abi_layout
pointer_alias_lifetime
error_handling
callback_dispatch
```

The target systems are single-threaded. Treat execution as single-threaded and do not create a separate execution-model review section.

Only ask the user for Step 0 input if project-specific background is necessary and cannot be inferred from the latest commit.

Optional focus config is still supported:

**Option A: Focus config file** (`.impact-scan-focus.yml` in repo root):

```yaml
subsystem: subsys/net
focus_symbols:
  - api_open
  - session_alloc
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

**Option B: CLI flags** (optional override):

```
--focus-symbols api_open,session_alloc
--ignore-paths tests/,docs/
```

The scanner will read focus from `.impact-scan-focus.yml` automatically. CLI flags override file config.

### Step 1: Scope Discovery (发现扫描范围)

Run the scanner to discover what changed:

```bash
python3 ripple/scripts/ripple_scan.py \
  --step discover --range HEAD~1..HEAD --subsystem subsys/net
```

This outputs `.impact-scan/scope_discovery.json`:

- changed files (C files, headers, build files, public interfaces)
- inferred subsystems

The `discover` step starts a new analysis and clears previous `.impact-scan/` artifacts before writing fresh files.

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
python3 ripple/scripts/ripple_scan.py \
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
- pointer-alias/lifetime symbols, especially `void *opaque/user_data/ctx/priv`, struct field assignments, container inserts, and callback registration escape points

Do NOT expand all changed symbols. This keeps reference search focused and fast:

```bash
python3 ripple/scripts/ripple_scan.py \
  --step expand --range HEAD~1..HEAD --subsystem subsys/net
```

This outputs `.impact-scan/expansion_summary.json`:

- which symbols were expanded and why
- reference counts per expanded symbol
- CodeGraph reference hits

Tool strategy (internal, don't expose to user unless asked):

```
CodeGraph required → heuristic only
```

Do not use Grep, ripgrep, `rg`, or Claude Code's Grep tool for reference search. If CodeGraph is missing or fails in required mode, stop and report the CodeGraph problem instead of falling back.

### Step 4: Evidence Review (用户确认关键证据)

Before generating the final report, present key findings for user confirmation:

- Are the legacy paths correct?
- Are the public interfaces correct?
- Are the ignore paths correct?
- Do the impact paths match project reality?
- Which risk items should be emphasized in the report?

This step is critical for weak models — project knowledge lives with the user, not the agent.

Stop here and wait for the user's confirmation unless the user explicitly selected one-shot/full-auto mode. Do not continue to Step 5 automatically in interactive guided mode.

### Step 5: Final Report (生成最终报告)

Generate the Chinese Markdown report from all collected artifacts:

```bash
python3 ripple/scripts/ripple_scan.py \
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
- **Reference Evidence**: CodeGraph reference counts
- **Impact Paths**: symbol → file → subsystem chains
- **必须人工 Review**: mandatory manual review items
- **内存泄漏关注点**: memory-lifetime specific findings
- **指针别名与生命周期关注点**: type/field/ownership/escape-point checks that do not rely on variable names
- **建议回归检查**: suggested regression tests
- **局限性**: scan limitations and confidence caveats

The report is written as plain UTF-8 for Linux deployment.

## Focus Config Reference

### File: `.impact-scan-focus.yml`

```yaml
subsystem: subsys/net
focus_symbols:
  - api_open
  - session_alloc
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
- large change (>= 80 lines): +2

### Symbol-level weights

- function declaration/definition changed: +4
- struct/union/enum/typedef changed: +4
- callback/function pointer pattern changed: +4
- global data changed: +2
- memory allocation/lifetime change: +5
- container ownership change (list/tree/hash/queue/map/cache): +5
- pointer alias / escaped lifetime change: +5
- callback opaque/context pointer alias change: +5
- semantic behavior keyword changed: +2
- symbol in public/shared path: +3
- symbol in high-risk path: +3
- symbol in memory-sensitive path: +3
- legacy file reference: +4
- referenced by >= 10 files: +3
- spans >= 3 subsystems: +3

### Architecture risk category weights

Default enabled categories are limited to:

```text
memory_leak
memory_safety
abi_layout
pointer_alias_lifetime
error_handling
callback_dispatch
```

| Category | Weight |
|----------|--------|
| `memory_safety` | +5 |
| `memory_leak` | +5 |
| `abi_layout` | +5 |
| `pointer_alias_lifetime` | +5 |
| `callback_dispatch` | +4 |
| `error_handling` | +3 |

### Risk levels

- **high**: score >= 8
- **medium**: score 4–7
- **low**: score 0–3

Scoring is triage only — not proof of defect. High score means "review this," not "this is broken."

## Three-Layer Analysis

### CodeGraph 层

Query function/symbol references, callers/callees, include/import relationships, and subsystem spread. Provides impact evidence. Does NOT prove safety — function pointers and callbacks can hide impact.

### Heuristic 层

Deterministic rules identify risk signals from names, paths, diff content, and categories. This is risk triage only. It can say "review this" but NOT "this is safe."

### Manual Review 层

For risks that static tools cannot resolve — pointer aliasing, ownership transfer, callback flow, struct field passing, error cleanup paths — write items into `必须人工 Review`. This reduces manual review scope, not replaces architect judgment. For C pointer risks, do not rely on local variable names; track the object type, struct fields, ownership APIs, and escape points instead.

## Architecture Risk Categories

| Category | Detects |
|----------|---------|
| `memory_safety` | buffer overflow, OOB, UAF, double free, unsafe copy/format |
| `memory_leak` | alloc/free imbalance, missing cleanup, refcount imbalance, container ops |
| `abi_layout` | struct/union/enum/typedef layout, packing, alignment, exported symbols |
| `error_handling` | return value, error code, goto error, NULL check, cleanup path |
| `pointer_alias_lifetime` | same object under different pointer names, void* opaque/user_data/ctx, field/global/container escape, callback registration lifetime |
| `callback_dispatch` | function pointer table, ops table, handler registration, dispatch |

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

## Pointer Alias / Lifetime Focus

C pointer risks must be checked by object identity and lifetime, not by variable name. A changed object may appear as `s`, `ctx`, `priv`, `opaque`, `user_data`, a struct field, a global, or a container element. When report flags `pointer_alias_lifetime`, require or suggest this focused review strategy:

### Tracking priority

1. **Type / struct identity**: search `struct xxx *`, `xxx_t *`, casts from `void *`, `sizeof(struct xxx)`, `offsetof(struct xxx, field)`, and `container_of(..., xxx, ...)`.
2. **Field-level access**: search `->field`, `.field`, added/removed pointer fields, refcount fields, list-node fields, length/capacity fields, and copy/reset code.
3. **Ownership API pairs**: match `create/new/alloc/init/get/ref/retain/acquire/open` with `free/destroy/deinit/put/unref/release/close/cleanup`.
4. **Escape points**: inspect assignment into `obj->field`, globals/statics, list/hash/map/queue/cache/tree nodes, callback registration, and module-level registries.
5. **Error paths**: inspect `goto fail/error/cleanup`, early `return`, partial initialization, and unregister/remove cleanup after an escaped pointer.

### Mandatory high-risk patterns

- `void *opaque`, `void *ctx`, `void *user_data`, `void *priv`, or `void *cookie` is cast back to a changed object type.
- Changed object is passed into callback registration or dispatch table.
- Changed object is stored into a struct field/global/container and may outlive the current function.
- A struct gains or changes pointer/refcount/list-node fields without matching destroy/copy/clone/error-cleanup updates.
- `memcpy`, `memset`, shallow copy, `sizeof`, `offsetof`, or `container_of` touches a struct containing pointers, refcount, or list/hash node fields.

### Report language rule

When this risk is detected, the report must say that local variable names are not reliable evidence of safety. It should phrase the review target as:

> 按对象类型、字段访问、ownership API 和逃逸点追踪该对象；不要只按变量名 grep。

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
- 指针别名与生命周期关注点
- 建议回归检查
- 局限性

Use evidence-backed language. When confidence is low, state why:

> Confidence is medium because no compile database or semantic C index was available.

## Agent Guidance

1. Determine mode first. Default to interactive guided mode unless the user explicitly asks for one-shot/full-auto mode.
2. For Step 0, do not ask for subsystem, focus symbols, focus risks, or ignore paths by default. Use latest-commit inference and the built-in enabled risk categories.
3. Run `--step discover`, summarize scope, then stop and ask whether to continue or adjust only if the inferred scope is obviously wrong.
4. Only after confirmation, run `--step triage`, summarize risk counts and expansion candidates, then stop and ask whether to continue.
5. Only after confirmation, run `--step expand`, summarize reference evidence and CodeGraph status, then stop and ask whether to continue.
6. Only after confirmation, present key evidence for review (Step 4), then stop and ask whether to generate the final report.
7. Only after confirmation, run `--step report` to generate the final Markdown.
8. Verify `.impact-scan/risk_report.md` exists. If it does not exist, run one-shot mode as fallback.
9. Read `.impact-scan/risk_report.md` and summarize for the user.

Completion rule:

- Completed: `.impact-scan/risk_report.md` exists and the final reply includes its path.
- Not completed: only terminal/chat text was produced, or only JSON artifacts were produced.
- Recovery: run `python3 ripple/scripts/ripple_scan.py --step report --range HEAD~1..HEAD --codegraph-mode required` from the target repo. If report artifacts are missing, run one-shot mode without `--step`.

If CodeGraph is missing, tell the user and stop. Do not continue with Grep, ripgrep, `rg`, or Claude Code's Grep tool.

For weak local models, rely on `.impact-scan/risk_items.json` and `.impact-scan/subsystem_analysis.json` more than free-form code reading. The scanner produces structured evidence — use it.

## Linux Intranet Notes

- Python 3.6+ compatible
- Runs on Linux hosts with `git`, `python3`, and `codegraph` on `PATH`
- `risk_report.md` written as plain UTF-8
- Subprocess output decoded as UTF-8
- Uses `codegraph` on Linux; no Grep/ripgrep fallback is used in the default workflow
