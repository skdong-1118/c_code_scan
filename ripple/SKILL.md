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

The guided workflow state is:

```text
.impact-scan/workflow_state.json
```

## Core Rules

- Require `codegraph` with `--codegraph-mode required`; do not use Grep, ripgrep, `rg`, or Claude Code's Grep tool for reference search.
- Default mode is interactive guided mode. Even if the user only says "analyze", stop and wait after each scanner step unless they clearly say `直接生成报告`, `不用确认`, `全自动`, `one-shot`, or `CI`.
- Do not ask for subsystem, focus symbols, risk categories, or ignore paths by default. Infer scope from latest-commit git changed files.
- New user analysis requests always start with Step 1 `discover`; this clears previous scan artifacts before reading old workflow state.
- Use `workflow_state.json` only when continuing the current analysis, not when the user asks to analyze/re-analyze again.
- Do not clear artifacts before `triage`, `expand`, or `report` when continuing the current analysis.
- Target systems are single-threaded. Do not add a separate threading, multiprocess, or execution-model review section.
- When continuing the current analysis, check `.impact-scan/workflow_state.json` and follow `next_required_step`; do not skip ahead.
- A step is complete only when its required artifact exists. Chat summaries are not step completion.

## Interactive Guided Mode

Do not run Step 1 through Step 4 in one uninterrupted sequence in guided mode.

```text
Step 0: Focus intake -> 自动推断 scope / 使用内置风险项
Step 1: Scope discovery -> 发现扫描范围 -> 用户确认
Step 2: Risk triage -> 初步风险分诊 -> 用户确认
Step 3: Deep call-chain analysis -> CodeGraph 深调用链 / 业务入口聚类 / 关键证据确认
Step 4: Final report -> 生成最终报告
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

Use CodeGraph only. Expand references and deep caller/callee paths for focus symbols, high-risk symbols, public interface symbols, memory/lifetime symbols, pointer-alias symbols, and enclosing functions for local field/heap/container/callback changes.

Deep call-chain analysis must consider multiple shapes, not only one long stack:

- branch points inside the changed function, such as `if/switch/state/mode/error` paths
- near callers where multiple flows directly share the common function
- deep upstream fan-in where business entries split many wrapper layers above the changed function
- downstream fan-out where the changed function calls different state, queue, callback, or lifecycle helpers

Trace caller paths to the top-level business entry or root caller. Do not set a fixed call-stack depth as the analysis target; depth is only a CodeGraph search budget.

Step 3 writes structured JSON artifacts. It does not write a Markdown review file.

Do not stop call-chain expansion because it seems enough. Success terminal conditions are only `complete_to_entry` or `complete_to_root`; `incomplete_depth_limit`, `truncated_path_budget`, and `evidence_gap` are incomplete evidence gaps. If any selected symbol has no successful path, do not claim low impact.

One-layer or shallow ordinary callers are not root evidence. If Step 3 cannot confirm a business entry/root, `workflow_state.json` must keep `next_required_step` as `expand`.

Step 3 is complete only when these artifacts exist:

```text
.impact-scan/call_chain_analysis.json
.impact-scan/step3a_call_paths.json
.impact-scan/step3b_business_entries.json
.impact-scan/step3c_branch_points.json
.impact-scan/step3d_state_flow.json
.impact-scan/step3e_evidence_gaps.json
.impact-scan/step3f_completion.json
```

`step3f_completion.json` must have `step3_complete: true`. These JSON files are the fixed Step 3 checklist: call paths, business entry groups, branch points, object/state flow candidates, evidence gaps, and completion status.

Summarize `.impact-scan/expansion_summary.json`: expanded symbols, reasons, CodeGraph hits, business entry group count, branch points, and missing reference evidence. Include only the key evidence that needs confirmation:

- inferred subsystem and ambiguous candidates, if any
- public interface or legacy path hits
- CodeGraph reference hits and impact paths
- business entry groups and branch points from deep call-chain analysis
- lifecycle evidence for heap objects, containers, callbacks, and pointer escapes

Stop and ask whether to generate the report.

### Step 4: report

```bash
python3 ripple/scripts/ripple_scan.py --step report --range HEAD~1..HEAD --codegraph-mode required
```

Before Step 4, verify `.impact-scan/step3f_completion.json` exists and has `step3_complete: true`. If missing or incomplete, finish Step 3 first; do not generate a final report.

Verify `.impact-scan/risk_report.md` exists, then summarize it briefly for the user. The final report must be written in Chinese; professional terms such as `CodeGraph`, `business entry groups`, `fan-in`, `fan-out`, `legacy path`, `callback`, `ABI`, `memory-lifetime`, and `evidence gap` may remain in English. For report sections and wording, read `references/report-format.md` when needed.

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
- If `.impact-scan/step3f_completion.json` is missing or incomplete before report, rerun `--step expand`.
- If `.impact-scan/risk_report.md` is missing after report, rerun `--step report`; if artifacts are missing, rerun one-shot mode.
- If scope is ambiguous, show `subsystem_resolution_candidates` and wait for the user to provide the complete path.

## References

- `references/risk-rules.md`: deterministic scoring, enabled categories, local-function mapping, heap/object lifetime evidence, pointer alias guidance.
- `references/report-format.md`: Chinese report sections, language rules, confidence wording.
- `references/linux-deployment.md`: Linux intranet deployment and CodeGraph setup.
