# Report Format Reference

Use this reference when generating `.impact-scan/risk_report.md`.

The final report must be Chinese Markdown. Professional technical terms may remain in English.

## Required Sections

```text
概要
分析分层
Reviewer 结论
高/中风险项
受影响 subsystem / 业务流程
Reference Evidence
已分析调用栈
生命周期与错误路径分析
函数指针 / Callback / 间接调用证据
Evidence Gaps
建议回归检查
局限性
```

Do not include a mandatory manual-review section. The report itself is the review.

## Reviewer Conclusions

For every high/medium risk item, write a concrete reviewer-style conclusion. Each item must answer:

- 改动点: what changed and where.
- 风险原因: why the evidence suggests risk.
- 影响流程: analyzed business flow, call stack, subsystem, or evidence gap.
- 最坏结果: concrete failure mode such as UAF, leak, wrong dispatch, ABI break, or error-path regression.
- 验证建议: scenario-level regression check tied to the affected path.

Avoid abstract-only wording such as:

```text
检测到 pointer_alias_lifetime 风险。
```

Prefer:

```text
对象被释放后仍可能被 queue/list/callback 持有；如果上层业务入口继续消费该对象，可能产生 UAF 或悬空指针。
```

## Analysis Layers

- CodeGraph MCP 层: definition, references, callers, callees, callchain, registration, indirect call evidence.
- Source reasoning 层: source-level interpretation of branches, object ownership, error paths, and return-value consumers.
- Heuristic risk 层: risk categories inferred from diff content, paths, public headers, callbacks, memory operations, ABI/layout changes, and lifecycle signals.
- Evidence gap 层: unresolved paths that must not be treated as low risk.

## Call Stack Reporting

The report must include analyzed call stacks from `.impact-scan/codegraph-evidence.md`.

For each path include:

```text
path
entry/root status
depth or qualitative length
legacy/non-legacy marker when known
evidence gap when unresolved
```

Successful statuses:

```text
complete_to_entry
complete_to_root
```

Incomplete statuses:

```text
evidence_gap
indirect_call_evidence_gap
path_explosion_gap
```

One-layer ordinary callers are not root evidence.

## Function Pointer and Callback Reporting

If a changed function may be called through a function pointer, ops table, handler table, callback, or registration API, include:

- registration site
- storage owner
- indirect call site
- trigger entry
- unresolved gaps

If only registration is found, do not call the path complete.

## Confidence

Confidence is high only when CodeGraph MCP evidence and source reasoning agree.

Phrase limitations plainly:

- `这是 regression risk review，不是 compatibility proof。`
- `function pointer 和 callback paths 依赖 CodeGraph MCP 能力。`
- `未闭合调用栈是 evidence gap，不是低风险证明。`

## Style

- Use evidence-backed language: `可能影响`, `建议验证`, `证据显示`.
- Avoid claiming a change is safe.
- Keep the report readable for C reviewers. Prefer concrete object/path stories over category lists.
