---
name: c-regression-impact-scan
description: Use in Claude Code whenever the user asks whether the latest change, recent modification, last commit, HEAD commit, or HEAD~1..HEAD change affects existing features, old features, legacy behavior, regression risk, subsystem behavior, architecture flow, business flow, cross-subsystem behavior, memory leaks, ownership/lifetime, or stable functionality in a C codebase. Trigger for natural requests like "分析最近一次修改对已有功能的影响", "检查最近提交有没有影响老功能", "看这次改动是否有回归风险", "分析这个子系统最近修改的影响", or "检查是否可能导致内存泄漏". Prioritize local CodeGraph impact scanning, then fall back to ripgrep and deterministic flow-impact plus memory-leak rules. The final deliverable must be a Chinese Markdown detection report.
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
   - `.impact-scan/subsystem_analysis.json`
   - `.impact-scan/risk_items.json`
   - `.impact-scan/architecture_risk_summary.json` (kept for compatibility; usually empty in flow-focused mode)
   - `.impact-scan/manual_review.json`
9. Produce a final Chinese Markdown detection report. Use `.impact-scan/risk_report.md` as the base report, refine it if needed, and ensure the final answer points to the generated `.md` file. The Markdown report must include:
   - overall risk: high, medium, or low
   - whether CodeGraph was used successfully
   - the three analysis layers: CodeGraph, Heuristic, and Manual Review
   - high-risk changed files and symbols
   - affected legacy subsystem candidates, with per-subsystem impact reason, changed files, referenced files, changed tokens, and suggested checks
   - evidence paths from changed item to references
   - architecture flow-impact findings
   - memory leak and ownership-lifetime findings
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

Do not claim CodeGraph proves a change is safe. It provides impact evidence for architecture flow review, but business behavior still needs targeted regression validation.

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

## Three-Layer Analysis Model

The report must clearly separate these three layers. Do not let Claude Code present heuristic evidence as a formal proof.

### CodeGraph 层

Use CodeGraph to find:

- function/symbol reference
- callers and callees
- include/import relationships
- subsystem spread
- changed token to referenced file impact paths

CodeGraph gives impact evidence. It does not prove business behavior is safe; use the evidence to select affected flows and regression scenarios.

### Heuristic 层

Use deterministic rules to identify risk signals from:

- changed files and subsystem paths
- legacy paths
- architecture flow paths
- reference count
- subsystem spread
- CodeGraph or `rg` impact paths

Heuristic analysis is only `flow impact triage`. It can say "this should be reviewed" or "this flow is likely affected"; it must not say "this is safe" unless stronger evidence exists.

### Manual Review 层

When static evidence is incomplete, write the item into the Markdown report under `必须人工 Review` and ask engineers to manually inspect it. This layer is mandatory for architecture-flow risks that ordinary symbol/reference graphs cannot reliably resolve:

- changed path is in a configured architecture flow directory
- changed path is in a configured legacy feature directory
- changed token is referenced by legacy feature files
- changed token is referenced by many files
- changed token crosses multiple subsystems
- impact path reaches an old feature flow or compatibility flow
- CodeGraph is unavailable or has sparse results
- memory-lifetime evidence appears in changed lines

For each Manual Review item, include the subject, kind, level, reasons, evidence files when available, and what the engineer should verify. The purpose is to reduce manual review scope, not to replace the architect's judgment.

## Risk Rules

Use deterministic flow-impact scoring before model reasoning. Treat these as default weights:

- configured architecture flow path changed: +4
- configured legacy feature path changed: +5
- legacy reference from CodeGraph or `rg`: +5
- changed token referenced by 10 or more files: +3
- changed token referenced across 3 or more top-level subsystems: +3
- large change size: +2
- memory leak or ownership-lifetime related change: +5
- memory-sensitive path on memory-lifetime change: +3

Risk level:

- `high`: score >= 8
- `medium`: score 4-7
- `low`: score 0-3 and narrow local references

Confidence:

- `high`: CodeGraph or strong index exists and references were found
- `medium`: `rg` references and file-level evidence exist
- `low`: only diff heuristics were available, or generated references are sparse

## Architecture Flow Review Focus

发现以下架构流程影响时必须在报告中突出说明：

- 直接修改 configured architecture flow path
- 直接修改 configured legacy feature path
- changed token 被 legacy feature files 引用
- changed token 引用范围很广
- changed token 跨多个 subsystem
- Impact Paths 到达老功能、稳定功能或兼容流程
- memory-lifetime changed token，例如 `malloc`, `calloc`, `realloc`, `strdup`, `free`, `release`, `destroy`, `cleanup`, `refcount`
- CodeGraph 不可用或结果稀疏，需要降低 confidence

## Memory Leak Focus

内存泄漏作为唯一保留的 C 语言专项风险。发现 `memory-lifetime` changed token 时，报告必须包含 `内存泄漏关注点`，并要求验证：

- allocation/free 是否成对
- ownership transfer 是否清晰
- cleanup paths 是否覆盖异常路径
- refcount increment/decrement 是否平衡
- legacy repeated-call paths 是否存在累积泄漏风险

## Report Style

The output report must be Chinese Markdown, but technical terms should stay in English when that is clearer. Prefer mixed wording such as `changed tokens`, `subsystem`, `legacy path`, `impact path`, `business flow`, `compile database`, and `CodeGraph`.

Keep these sections unless there is a strong reason to add more:

- `概要`
- `分析分层`
- `高/中风险项`
- `架构流程影响类别`
- `受影响 subsystem 候选`
- `Reference Evidence`
- `Impact Paths`
- `必须人工 Review`
- `内存泄漏关注点`
- `建议回归检查`
- `局限性`

Use evidence-backed language. Prefer:

> "This commit is high risk because a changed token is referenced by legacy feature files and spans 7 subsystems."

Avoid:

> "This is safe."

When evidence is incomplete, say exactly why:

> "Confidence is medium because CodeGraph did not return complete impact paths and fallback references were sparse."

## Windows Intranet Notes

Read `references/windows-deployment.md` when setting up the skill on Windows or packaging it for an offline server.
