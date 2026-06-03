---
name: ripple
description: Use when analyzing whether the current branch latest C commit (HEAD~1..HEAD) can affect existing features, legacy behavior, subsystem behavior, public C interfaces, memory/lifetime safety, ABI/layout, error handling, pointer alias/lifetime, callback dispatch, or regression risk. Requires local CodeGraph; final output is a Chinese Markdown report.
---

# Guided C Regression Impact Scan

## Scope

`ripple` analyzes only the current branch latest commit:

```text
HEAD~1..HEAD
```

Do not analyze older commits, multiple commits, other branches, merge-base ranges, or custom ranges. If asked for another range, stop and explain that this skill is intentionally limited to the latest commit.

The final deliverable is always:

```text
.impact-scan/risk_report.md
```

Terminal or chat summaries are not completion.

## Core Rules

- Require `codegraph` with `--codegraph-mode required`; do not use Grep, ripgrep, `rg`, or Claude Code's Grep tool for reference search.
- Default to interactive guided mode. stop and wait after each scanner step unless the user clearly says `直接生成报告`, `不用确认`, `全自动`, `one-shot`, or `CI`.
- Do not ask for subsystem, focus symbols, risk categories, or ignore paths by default. Infer scope from latest-commit git changed files.
- Starting a new analysis clears previous scan artifacts at `discover` or one-shot start. Do not clear artifacts before `triage`, `expand`, or `report`.
- Target systems are single-threaded. Do not add a separate threading, multiprocess, or execution-model review section.

## Interactive Guided Mode

Do not run Step 1 through Step 5 in one uninterrupted sequence in guided mode.

```text
Step 0: Focus intake -> 自动推断 scope / 使用内置风险项
Step 1: Scope discovery -> 发现扫描范围 -> 用户确认
Step 2: Risk triage -> 初步风险分诊 -> 用户确认
Step 3: Focused expansion -> CodeGraph 定向扩展 -> 用户确认
Step 4: Evidence review -> 关键证据确认
Step 5: Final report -> 生成最终报告
```

### Step 1: discover

```bash
python3 ripple/scripts/ripple_scan.py --step discover --range HEAD~1..HEAD --codegraph-mode required
```

Summarize `.impact-scan/scope_discovery.json`: changed files, C/header files, inferred subsystem, and any `subsystem_resolution_candidates`.

Scope inference happens before scoped diff. If the user passes a leaf name such as `nbm`, use it only as a matcher against latest-commit changed paths; a unique match such as `fosip/nbm` becomes the scan scope. Multiple candidates are not guessed.

### Step 2: triage

```bash
python3 ripple/scripts/ripple_scan.py --step triage --range HEAD~1..HEAD --codegraph-mode required
```

Summarize `.impact-scan/triage_summary.json`: high/medium/low counts, changed symbol count, and expansion candidates.

For C function-body changes, Step 2 maps local variable, field, heap allocation, container, and callback evidence to the enclosing function. Do not use local names such as `ret`, `ctx`, `tmp`, or `flag` as CodeGraph query symbols.

For risk details, read `references/risk-rules.md` only when you need to explain scoring, lifetime evidence, or pointer alias behavior.

### Step 3: expand

```bash
python3 ripple/scripts/ripple_scan.py --step expand --range HEAD~1..HEAD --codegraph-mode required
```

Use CodeGraph only. Expand references for focus symbols, high-risk symbols, public interface symbols, memory/lifetime symbols, pointer-alias symbols, and enclosing functions for local field/heap/container/callback changes.

Summarize `.impact-scan/expansion_summary.json`: expanded symbols, reasons, CodeGraph hits, and missing reference evidence.

### Step 4: evidence review

Show only the key evidence that needs user confirmation:

- inferred subsystem and ambiguous candidates, if any
- public interface or legacy path hits
- CodeGraph reference hits and impact paths
- lifecycle evidence for heap objects, containers, callbacks, and pointer escapes

Stop and ask whether to generate the report.

### Step 5: report

```bash
python3 ripple/scripts/ripple_scan.py --step report --range HEAD~1..HEAD --codegraph-mode required
```

Verify `.impact-scan/risk_report.md` exists, then summarize it briefly for the user. For report sections and wording, read `references/report-format.md` when needed.

## One-Shot Mode

Use only when the user explicitly asks for full-auto/CI behavior:

```bash
python3 ripple/scripts/ripple_scan.py --range HEAD~1..HEAD --codegraph-mode required
```

One-shot mode still clears stale artifacts first and still generates `.impact-scan/risk_report.md`.

## Optional Config

The scanner reads optional `.impact-scan-focus.yml` from the repo root or `--focus path`:

```yaml
subsystem: subsys/net
focus_symbols:
  - api_open
ignore_paths:
  - tests/
  - docs/
legacy_paths:
  - legacy/
public_interfaces:
  - include/
notes:
  - old client behavior must not change
```

Subsystem directories may contain `.impact-scan.yml` or `.impact-scan.json` with `public_interfaces`, `legacy_paths`, `high_risk_paths`, `memory_sensitive_paths`, and `low_risk_paths`.

## Failure Handling

- If CodeGraph is missing or `.codegraph` is absent in required mode, stop and report the CodeGraph error.
- If `.impact-scan/risk_report.md` is missing after report, rerun `--step report`; if artifacts are missing, rerun one-shot mode.
- If scope is ambiguous, show `subsystem_resolution_candidates` and wait for the user to provide the complete path.

## References

- `references/risk-rules.md`: deterministic scoring, enabled categories, local-function mapping, heap/object lifetime evidence, pointer alias guidance.
- `references/report-format.md`: Chinese report sections, language rules, confidence wording.
- `references/linux-deployment.md`: Linux intranet deployment and CodeGraph setup.
