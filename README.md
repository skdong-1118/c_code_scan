# Ripple

`ripple` is a Claude Code skill for C regression impact review. It is now a pure model-driven workflow: the agent reads the latest diff, uses CodeGraph MCP tools directly, reasons over source evidence, and writes a Chinese reviewer-style report.

The hard scope is always the current branch latest commit:

```text
HEAD~1..HEAD
```

Do not use this skill for older commits, multiple commits, other branches, merge-base ranges, or custom ranges.

## Why This Version Exists

The previous implementation used a large Python scanner. That made the flow stable, but it also constrained deep reasoning, especially for:

- long business call chains
- shared low-level functions with many upstream entries
- function pointer, callback, ops table, and registration paths
- object lifetime and pointer alias analysis
- large diffs where the important path is not obvious from a fixed heuristic

This refactor intentionally removes the scanner and lets the model do the analysis. The skill keeps only hard workflow rules, evidence requirements, and report format constraints.

## Current Architecture

```text
ripple/
  SKILL.md
  agents/openai.yaml
  references/
    codegraph-mcp-checklist.md
    linux-deployment.md
    report-format.md
    risk-rules.md
```

There is no `ripple_scan.py` workflow in this version.

## Required Runtime

- Claude Code or a compatible agent runtime
- Git
- CodeGraph MCP tools exposed to the agent
- Read access to the target C repository

The skill does not call a Linux `codegraph` CLI. If only a command-line CodeGraph binary is available and no MCP tools are exposed to the agent, this version cannot complete Step 3 as designed.

## Default Workflow

Default mode is interactive. A new analysis starts from Step 1 and clears previous `.impact-scan` artifacts before reading any old workflow notes.

```text
Step 1: Scope discovery
Step 2: Risk framing
Step 3: CodeGraph MCP deep dive
Step 4: Source reasoning
Step 5: Final report
```

Only skip confirmations when the user explicitly asks for full-auto, one-shot, CI, or no-confirmation behavior.

## Output Artifacts

All artifacts are Markdown so the model can read and revise them directly:

```text
.impact-scan/scope.md
.impact-scan/risk-framing.md
.impact-scan/codegraph-evidence.md
.impact-scan/source-reasoning.md
.impact-scan/risk_report.md
```

Terminal summaries are not completion. The final deliverable is always:

```text
.impact-scan/risk_report.md
```

## Analysis Requirements

The agent must:

- inspect only `HEAD~1..HEAD`
- infer subsystem from changed paths instead of asking first
- use CodeGraph MCP for references, callers, callees, call chains, and definitions
- keep expanding call chains until reaching a top-level business entry/root or recording an evidence gap
- treat one-layer ordinary callers as incomplete evidence
- analyze function pointer/callback paths through registration, storage, indirect call site, and trigger entry when MCP supports those queries
- explain object lifecycle for heap objects, containers, callback opaque data, pointer fields, and error cleanup paths
- write reviewer-style conclusions, not just risk labels

## Risk Categories

Enabled default categories:

```text
memory_leak
memory_safety
abi_layout
pointer_alias_lifetime
error_handling
callback_dispatch
```

Target systems are single-threaded. Do not add threading, multiprocess, or execution-model review sections.

## Final Report

The final report must be Chinese Markdown. Professional terms such as `CodeGraph`, `business entry`, `fan-in`, `fan-out`, `callback`, `ABI`, `memory-lifetime`, and `evidence gap` may remain in English.

For each high/medium risk item, the report must answer:

- 改动点
- 风险原因
- 影响流程
- 最坏结果
- 验证建议

It must include analyzed call stacks and unresolved evidence gaps. Do not claim low impact from missing evidence.
