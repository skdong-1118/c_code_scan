---
name: c-commit-impact-scan
description: Use in Claude Code when scanning a large C codebase commit for possible impact on legacy features, especially in an offline or intranet Windows agent environment. This skill prioritizes local CodeGraph impact scanning, then falls back to ripgrep and deterministic rules before producing a regression risk report.
---

# C Commit Impact Scan

## Purpose

Use this skill in Claude Code to answer: "Did the latest C commit change common interfaces or shared modules in a way that may break old features?"

The target environment is a large commercial C codebase, usually intranet-only, often on Windows, and possibly handled by a weak AI agent. Do not ask the model to read the whole repository. Use local tools and deterministic rules first, then summarize the structured output.

## Default Workflow

1. Confirm the current directory is the target git repository.
2. Confirm `codegraph` or `codegraph.exe` is installed. CodeGraph is the primary backend for this skill.
3. Run the bundled scanner from the repository root:

   ```powershell
   python path\to\c-commit-impact-scan\scripts\c_impact_scan.py --range HEAD~1..HEAD --codegraph-mode prefer
   ```

   On macOS or Linux:

   ```bash
   python3 path/to/c-commit-impact-scan/scripts/c_impact_scan.py --range HEAD~1..HEAD --codegraph-mode prefer
   ```

4. For first-time setup, if the user has approved indexing or the repository policy allows it, add `--init-codegraph`:

   ```powershell
   python path\to\c-commit-impact-scan\scripts\c_impact_scan.py --range HEAD~1..HEAD --codegraph-mode prefer --init-codegraph
   ```

5. If the scan must fail when CodeGraph is unavailable, use:

   ```powershell
   python path\to\c-commit-impact-scan\scripts\c_impact_scan.py --range HEAD~1..HEAD --codegraph-mode required
   ```

6. Read `.impact-scan/risk_report.md` first.
7. If more evidence is needed, inspect these generated files:
   - `.impact-scan/codegraph_status.json`
   - `.impact-scan/diff_summary.json`
   - `.impact-scan/changed_symbols.json`
   - `.impact-scan/references.json`
   - `.impact-scan/subsystem_impact.json`
   - `.impact-scan/risk_items.json`
8. Produce a concise report with:
   - overall risk: high, medium, or low
   - whether CodeGraph was used successfully
   - high-risk changed files and symbols
   - affected legacy subsystem candidates
   - evidence paths from changed item to references
   - suggested regression tests
   - scan limitations and confidence

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
3. Summarize findings.
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
- global variable changed: +2
- changed symbol referenced by 10 or more files: +3
- changed symbol referenced across 3 or more top-level subsystems: +3
- build file or feature switch changed: +3

Risk level:

- `high`: score >= 8, or any public header/API change with broad references
- `medium`: score 4-7
- `low`: score 0-3 and narrow local references

Confidence:

- `high`: CodeGraph or strong index exists and references were found
- `medium`: `rg` references and file-level evidence exist
- `low`: only diff heuristics were available, or generated references are sparse

## C-Specific Review Focus

Always highlight these C risks when present:

- public header changes
- struct layout changes, including field order and field type changes
- enum numeric value changes
- macro default value changes
- `#ifdef` / `#if` behavior changes
- callback registration and function pointer table changes
- error code, return value, ownership, lifetime, or buffer size semantic changes
- shared module changes used by legacy subsystems

## Report Style

Use evidence-backed language. Prefer:

> "This commit is high risk because `include/foo.h` changed and references were found in 7 subsystems."

Avoid:

> "This is safe."

When evidence is incomplete, say exactly why:

> "Confidence is medium because no compile database or semantic C index was available; macro-expanded paths were not verified."

## Windows Intranet Notes

Read `references/windows-deployment.md` when setting up the skill on Windows or packaging it for an offline server.
