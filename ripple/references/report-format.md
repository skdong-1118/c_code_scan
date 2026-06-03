# Report Format Reference

Use this reference when generating or explaining `.impact-scan/risk_report.md`.

## Required Sections

The final report is Chinese Markdown and normally includes:

- 概要
- 用户重点关注覆盖
- 分析分层
- 高/中风险项
- 架构风险类别
- 受影响 subsystem 候选
- Reference Evidence
- Impact Paths
- Deep Call-Chain Evidence
- 生命周期风险证据
- 内存泄漏关注点
- 指针别名与生命周期关注点
- 建议回归检查
- 局限性

Do not include the removed mandatory-review section.

## Layer Wording

Use these layer meanings:

- CodeGraph 层: reference/caller/callee/include/subsystem impact evidence. Local variable changes are first mapped to the enclosing function, then expanded with CodeGraph.
- Deep call-chain 层: use `.impact-scan/call_chain_analysis.json` to explain business entry groups, branch points, upstream fan-in, downstream fan-out, and paths that need source-level semantic review.
- Heuristic 层: deterministic risk signals from functions, paths, diff content, categories, object types, fields, ownership APIs, and escape points.
- 生命周期证据层: heap allocation, container insert/remove, callback opaque, struct field escape, and error cleanup evidence.

## Confidence

Confidence is high when CodeGraph produced reference evidence. Confidence is low when only deterministic heuristics are available.

Phrase limitations plainly:

- `这是 regression risk triage scan，不是 compatibility proof。`
- `function pointer 和 callback paths 依赖 CodeGraph 索引能力。`
- `没有 compile database 或 semantic C index 时，类型关系可能不完整。`

## Style

- Keep technical terms in English when clearer: `changed symbols`, `subsystem`, `legacy path`, `memory-lifetime`, `ABI`, `callback`, `CodeGraph`.
- Use evidence-backed language: `可能影响`, `建议验证`, `命中证据`.
- Avoid claiming a change is safe. The report narrows risk and validation paths.
