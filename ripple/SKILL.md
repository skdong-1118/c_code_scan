---
name: ripple
description: 用于评审当前分支最后一次 C 代码提交是否可能影响已有功能、老功能流程、公共接口、内存/生命周期安全、ABI/layout、错误处理、指针别名、callback 分发或 subsystem 行为；需要 CodeGraph MCP 和源码语义推理。
---

# Ripple C 回归影响评审

## 分析范围

只分析当前分支最后一个 commit：

```text
HEAD~1..HEAD
```

不要分析历史 commit、多个 commit、其他分支、merge-base 范围或自定义范围。如果用户要求其他范围，停止并说明 `ripple` 被故意限制为只分析最近一次提交。

最终交付始终是：

```text
.impact-scan/risk_report.md
```

终端总结或对话总结不算完成。

## 核心规则

- 本版本是纯模型驱动分析。不要运行 `ripple_scan.py`，它不是本流程的一部分。
- 必须使用 `CodeGraph MCP` 工具。不要用 Grep、ripgrep、`rg`、shell `codegraph` 或普通文本搜索替代 CodeGraph 证据。
- 默认是交互式分步流程。每一步完成后停止等待确认，除非用户明确说 `直接生成报告`、`不用确认`、`全自动`、`one-shot` 或 `CI`。
- 新分析必须从 Step 1 开始，并在读取旧产物前清空 `.impact-scan/`。只有用户明确说继续上一次分析时，才读取旧产物。
- 默认根据最近 commit 的变更路径推断 subsystem。不要默认询问 subsystem、focus symbol、风险项或忽略路径。
- 目标系统按单线程模型处理。不要增加多线程、多进程或执行模型评审章节。
- 每一步必须写出对应 Markdown 产物。只在聊天中推理不算该步骤完成。

## 产物

```text
.impact-scan/scope.md
.impact-scan/risk-framing.md
.impact-scan/codegraph-evidence.md
.impact-scan/source-reasoning.md
.impact-scan/risk_report.md
```

## 交互式流程

交互模式下，不要一口气跑完所有步骤。

```text
Step 1：Scope discovery，发现变更范围
Step 2：Risk framing，建立风险假设
Step 3：CodeGraph MCP 深挖，深入调用链和引用证据
Step 4：Source reasoning，结合源码做语义推理
Step 5：Final report，生成最终报告
```

### Step 1：范围发现

先清理旧产物：

```bash
mkdir -p .impact-scan
find .impact-scan -mindepth 1 -maxdepth 1 -type f -delete
```

然后只检查：

```bash
git diff --name-status HEAD~1..HEAD
git diff --stat HEAD~1..HEAD
git diff --unified=80 HEAD~1..HEAD -- '*.c' '*.h'
```

写入 `.impact-scan/scope.md`，内容包括：

- commit range
- changed files
- 推断出的 subsystem 路径
- 变更的 C/header 文件
- 看起来像大改动或 public interface 的文件
- 需要用户确认的歧义点

停止并询问用户 scope 是否正确。

### Step 2：风险建模

阅读 `references/risk-rules.md`。

把 diff hunk 映射到被修改的函数或类型。如果改动只涉及局部变量、字段、heap object、container 操作或 callback 相关语句，要映射到 enclosing function。不要把 `ret`、`tmp`、`ctx`、`flag`、`state` 这类局部名字当成 CodeGraph 查询对象。

写入 `.impact-scan/risk-framing.md`，内容包括：

- 需要调查的 changed subjects
- 风险分类：`memory_leak`、`memory_safety`、`abi_layout`、`pointer_alias_lifetime`、`error_handling`、`callback_dispatch`
- 每个 subject 为什么值得关注
- Step 3 的 CodeGraph MCP 查询计划

停止并询问是否继续进入 CodeGraph 深挖。

### Step 3：CodeGraph MCP 深挖

阅读 `references/codegraph-mcp-checklist.md`。

对每个 selected subject，使用 CodeGraph MCP 查询：

- definition
- references
- callers
- callees
- call chain paths

对于 callback / function pointer 风险，还要使用环境中可用的 MCP 能力查询：

- address-taken references
- registration sites
- handler / ops / callback table assignments
- indirect call sites
- trigger entry paths

不要因为找到一个 caller 就停止。必须继续展开 caller，直到到达顶层 business entry/root，或者明确记录 evidence gap。一层普通 caller 不是 root 证据。

写入 `.impact-scan/codegraph-evidence.md`，内容包括：

- 已执行的每个 MCP 查询
- 原始结果摘要
- 已分析调用栈
- business entry/root 状态
- branch points 和 fan-in/fan-out
- function pointer / callback 注册与触发证据
- 未解决的 evidence gaps

停止并询问是否继续做源码语义推理。

### Step 4：源码语义推理

阅读变更函数，以及 Step 3 中发现的重要函数。用 CodeGraph 证据指导源码阅读。

写入 `.impact-scan/source-reasoning.md`，内容包括：

- object / data lifecycle 故事线
- error path 和 cleanup 行为
- pointer alias 和 ownership transfer
- callback / function pointer 注册与触发行为
- 上游 caller 如何消费返回值、状态变化、副作用和错误码
- 仍未解决的 evidence gaps

不要从缺少证据推出低风险结论。

停止并询问是否生成最终报告。

### Step 5：最终报告

阅读 `references/report-format.md`。

生成 `.impact-scan/risk_report.md`，使用中文 Markdown。报告必须包含：

- 概要
- 分析分层
- reviewer 风格结论
- 高/中风险项
- 受影响 subsystem / 业务流程
- reference evidence
- 已分析调用栈
- 生命周期推理
- evidence gaps
- 具体验证建议
- 局限性

每个 high/medium 风险项都必须回答：

- 改动点
- 风险原因
- 影响流程
- 最坏结果
- 验证建议

确认 `.impact-scan/risk_report.md` 存在后，再简要向用户总结。

## 失败处理

- 如果 CodeGraph MCP 工具不可用，停止并说明本版本无法完成 Step 3。
- 如果调用栈无法到达 business entry/root，标记为 `evidence_gap`。
- 如果 function pointer / callback 注册或触发路径无法闭合，标记为 `indirect_call_evidence_gap`。
- 如果 `.impact-scan/risk_report.md` 缺失，任务未完成。

## 参考文件

- `references/codegraph-mcp-checklist.md`：必须执行的 MCP 查询检查清单。
- `references/risk-rules.md`：风险分类和 C 语言推理规则。
- `references/report-format.md`：最终报告格式和写作风格。
- `references/linux-deployment.md`：MCP 部署要求。
