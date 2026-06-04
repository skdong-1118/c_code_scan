# 报告格式参考

生成 `.impact-scan/risk_report.md` 时使用本文件。

最终报告必须是中文 Markdown。必要的专业术语可以保留英文。

## 必需章节

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

不要加入“必须人工 review”这类独立章节。报告本身就是 review 结论。

## Reviewer 结论

对每个 high/medium 风险项，都要写具体的 reviewer 风格结论。每项必须回答：

- 改动点：改了什么，在哪个文件 / 函数 / 类型。
- 风险原因：为什么这些证据指向风险，不要只写风险分类名。
- 影响流程：已分析的业务流程、调用栈、subsystem，或明确的 evidence gap。
- 最坏结果：具体失败模式，例如 UAF、leak、错误 dispatch、ABI 破坏、error path regression。
- 验证建议：和受影响路径绑定的具体回归验证场景。

避免只写抽象句子，例如：

```text
检测到 pointer_alias_lifetime 风险。
```

优先写成：

```text
对象被释放后仍可能被 queue/list/callback 持有；如果上层业务入口继续消费该对象，可能产生 UAF 或悬空指针。
```

## 分析分层

- CodeGraph MCP 层：definition、references、callers、callees、callchain、registration、indirect call evidence。
- Source reasoning 层：结合源码解释 branch、object ownership、error path、return-value consumer。
- Heuristic risk 层：根据 diff 内容、路径、public header、callback、memory 操作、ABI/layout 变化和 lifecycle 信号推断风险分类。
- Evidence gap 层：未闭合路径必须显式记录，不能当作低风险。

## 调用栈报告要求

报告必须包含 `.impact-scan/codegraph-evidence.md` 中已经分析过的调用栈。

每条 path 包含：

```text
path
entry/root status
depth 或定性长度
legacy/non-legacy 标记，若能判断
未闭合时的 evidence gap
```

成功状态：

```text
complete_to_entry
complete_to_root
```

未完成状态：

```text
evidence_gap
indirect_call_evidence_gap
path_explosion_gap
```

一层普通 caller 不是 root 证据。

## Function Pointer 与 Callback 报告要求

如果 changed function 可能通过 function pointer、ops table、handler table、callback 或 registration API 被调用，必须包含：

- registration site
- storage owner
- indirect call site
- trigger entry
- unresolved gaps

如果只找到了 registration，不要把路径判断为 complete。

## 置信度

只有当 CodeGraph MCP 证据和源码语义推理互相印证时，置信度才可以写 high。

局限性要直接写清楚：

- `这是 regression risk review，不是 compatibility proof。`
- `function pointer 和 callback paths 依赖 CodeGraph MCP 能力。`
- `未闭合调用栈是 evidence gap，不是低风险证明。`

## 写作风格

- 使用证据驱动的表达：`可能影响`、`建议验证`、`证据显示`。
- 避免声称变更是安全的。
- 报告要让 C reviewer 容易读懂。优先写具体对象 / 路径故事，不要只罗列风险分类。
