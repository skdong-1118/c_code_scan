---
name: ripple
description: Use when reviewing whether the current branch latest C commit can regress existing behavior, legacy flows, public interfaces, memory/lifetime safety, ABI/layout, error handling, pointer aliasing, callback dispatch, or subsystem behavior. Requires CodeGraph MCP tools and source-level reasoning.
---

# Ripple C Regression Review

## Scope

Analyze only the current branch latest commit:

```text
HEAD~1..HEAD
```

Do not analyze older commits, multiple commits, other branches, merge-base ranges, or custom ranges. If the user asks for another range, stop and explain that `ripple` is intentionally limited to the latest commit.

The final deliverable is always:

```text
.impact-scan/risk_report.md
```

Terminal or chat summaries are not completion.

## Core Rules

- This version is pure model-driven analysis. Do not run `ripple_scan.py`; it is not part of this workflow.
- Require CodeGraph MCP tools. Do not use Grep, ripgrep, `rg`, shell `codegraph`, or text search as a substitute for CodeGraph evidence.
- Default mode is interactive guided mode. Stop after each step unless the user clearly asks for `直接生成报告`, `不用确认`, `全自动`, `one-shot`, or `CI`.
- New analysis requests always start at Step 1 and clear `.impact-scan/` before reading old artifacts. Continue old artifacts only when the user explicitly says to continue the previous analysis.
- Infer subsystem from latest-commit changed paths. Do not ask for subsystem, focus symbols, risk categories, or ignored paths by default.
- Target systems are single-threaded. Do not add threading, multiprocess, or execution-model review sections.
- Every step must write its required Markdown artifact. Reasoning in chat is not step completion.

## Artifacts

```text
.impact-scan/scope.md
.impact-scan/risk-framing.md
.impact-scan/codegraph-evidence.md
.impact-scan/source-reasoning.md
.impact-scan/risk_report.md
```

## Interactive Workflow

Do not run all steps in one uninterrupted sequence in guided mode.

```text
Step 1: Scope discovery
Step 2: Risk framing
Step 3: CodeGraph MCP deep dive
Step 4: Source reasoning
Step 5: Final report
```

### Step 1: Scope Discovery

Start by clearing stale artifacts:

```bash
mkdir -p .impact-scan
find .impact-scan -mindepth 1 -maxdepth 1 -type f -delete
```

Then inspect only:

```bash
git diff --name-status HEAD~1..HEAD
git diff --stat HEAD~1..HEAD
git diff --unified=80 HEAD~1..HEAD -- '*.c' '*.h'
```

Write `.impact-scan/scope.md` with:

- commit range
- changed files
- inferred subsystem paths
- changed C/header files
- large or public-interface-looking files
- any ambiguity that needs user confirmation

Stop and ask whether the scope looks right.

### Step 2: Risk Framing

Read `references/risk-rules.md`.

Map diff hunks to changed functions/types. If a local variable, field, heap object, container operation, or callback-related line changed, map it to the enclosing function. Do not treat local names such as `ret`, `tmp`, `ctx`, `flag`, or `state` as CodeGraph query subjects.

Write `.impact-scan/risk-framing.md` with:

- changed subjects to investigate
- risk categories: `memory_leak`, `memory_safety`, `abi_layout`, `pointer_alias_lifetime`, `error_handling`, `callback_dispatch`
- why each subject matters
- CodeGraph MCP query plan for Step 3

Stop and ask whether to continue to CodeGraph deep dive.

### Step 3: CodeGraph MCP Deep Dive

Read `references/codegraph-mcp-checklist.md`.

For every selected subject, use CodeGraph MCP tools for:

- definition
- references
- callers
- callees
- call chain paths

For callback/function pointer risks, also use any available MCP capability for:

- address-taken references
- registration sites
- handler/ops/callback table assignments
- indirect call sites
- trigger entry paths

Do not stop because one caller was found. Continue caller expansion until the path reaches a top-level business entry/root, or record an evidence gap. One-layer ordinary callers are not root evidence.

Write `.impact-scan/codegraph-evidence.md` with:

- every MCP query performed
- raw result summary
- analyzed call stacks
- business entry/root status
- branch points and fan-in/fan-out
- function pointer/callback registration and trigger evidence
- unresolved evidence gaps

Stop and ask whether to continue to source reasoning.

### Step 4: Source Reasoning

Read the changed functions and the important functions found in Step 3. Use CodeGraph evidence to guide source reading.

Write `.impact-scan/source-reasoning.md` with:

- object/data lifecycle story
- error path and cleanup behavior
- pointer alias and ownership transfer
- callback/function pointer registration and trigger behavior
- how upstream callers consume return values, state changes, side effects, and errors
- evidence gaps that remain unresolved

Do not claim low impact from missing evidence.

Stop and ask whether to generate the final report.

### Step 5: Final Report

Read `references/report-format.md`.

Generate `.impact-scan/risk_report.md` in Chinese Markdown. It must include:

- summary
- analysis layers
- reviewer-style conclusions
- high/medium risk items
- affected subsystem/business flows
- reference evidence
- analyzed call stacks
- lifecycle reasoning
- evidence gaps
- concrete regression checks
- limitations

For every high/medium risk item, answer:

- 改动点
- 风险原因
- 影响流程
- 最坏结果
- 验证建议

Verify the file exists, then briefly summarize it for the user.

## Failure Handling

- If CodeGraph MCP tools are unavailable, stop and say this version cannot complete Step 3.
- If a call stack cannot reach a business entry/root, label it as `evidence_gap`.
- If function pointer/callback registration or trigger paths cannot be resolved, label them as `indirect_call_evidence_gap`.
- If `.impact-scan/risk_report.md` is missing, the task is not complete.

## References

- `references/codegraph-mcp-checklist.md`: required MCP query checklist.
- `references/risk-rules.md`: risk categories and C reasoning guidance.
- `references/report-format.md`: final report format and style.
- `references/linux-deployment.md`: MCP deployment expectations.
