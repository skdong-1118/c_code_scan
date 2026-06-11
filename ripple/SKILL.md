---
name: ripple
description: 用于分析当前分支最后一次提交可能影响哪些已有业务功能、老功能流程、共享公共流程、跨 subsystem 路径和容易忽略的间接入口；适用于需要 CodeGraph MCP 和源码业务语义推理的代码变更影响分析。
---

# Ripple 业务影响发现

## 分析范围

只分析当前分支最后一个 commit：

```text
HEAD~1..HEAD
```

不要分析历史 commit、多个 commit、其他分支、merge-base 范围或自定义范围。如果用户要求其他范围，停止并说明 `ripple` 被故意限制为只分析最近一次提交。

最终交付始终是：

```text
.impact-scan/impact_report.md
```

终端总结或对话总结不算完成。

## 核心规则

- 必须使用 `CodeGraph MCP` 获取定义、引用、调用关系和调用路径证据。
- 不要用 Grep、ripgrep、`rg` 或普通文本搜索替代 CodeGraph 关系证据。
- 默认是交互式分步流程。每一步完成后停止等待确认，除非用户明确说 `直接生成报告`、`不用确认`、`全自动`、`one-shot` 或 `CI`。
- 新分析必须从 Step 1 开始，并在读取旧产物前清空 `.impact-scan/`。只有用户明确说继续上一次分析时，才读取旧产物。
- 默认根据最近 commit 的实际变更路径推断 subsystem，不要预设目录前缀。
- 不要默认询问 subsystem、focus symbol、风险项或忽略路径。
- 所有判断都围绕业务行为、功能流程、触发条件和用户可观察结果展开。
- 每一步必须写出对应 Markdown 产物。只在聊天中推理不算该步骤完成。

## 产物

```text
.impact-scan/scope.md
.impact-scan/change-semantics.md
.impact-scan/codegraph-evidence.md
.impact-scan/business-reasoning.md
.impact-scan/impact_report.md
```

## 交互式流程

交互模式下，不要一口气跑完所有步骤。

```text
Step 1：Scope discovery，发现变更范围
Step 2：Change semantics，解释变更的业务语义
Step 3：CodeGraph MCP 深挖，发现业务入口和共享流程
Step 4：Business reasoning，分析潜在遗漏流程
Step 5：Final report，生成业务影响报告
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
git diff --unified=80 HEAD~1..HEAD
```

写入 `.impact-scan/scope.md`，内容包括：

- commit range
- changed files
- 从完整变更路径推断出的 subsystem
- 变更涉及的函数、类型、配置、消息或数据对象
- 看起来会改变公共流程或外部行为的文件
- 需要用户确认的歧义点

停止并询问用户 scope 是否正确。

### Step 2：变更业务语义

阅读 `references/business-impact-rules.md`。

把每个 diff hunk 映射到 enclosing function、类型、配置项、消息处理器或其他有业务意义的 changed subject。局部变量名只用于理解 enclosing subject，不要直接作为 CodeGraph 查询对象。

写入 `.impact-scan/change-semantics.md`，内容包括：

- changed subjects
- 修改前后的行为差异
- 变化对应的业务语义
- 可能受到影响的业务条件、模式、状态、消息类型或结果
- Step 3 的 CodeGraph MCP 查询计划

停止并询问是否继续进入 CodeGraph 深挖。

### Step 3：业务入口和共享流程深挖

阅读 `references/codegraph-mcp-checklist.md`。

对每个 changed subject，使用 CodeGraph MCP 查询：

- definition
- references
- callers
- callees
- call chain paths

持续向上展开，不规定固定层数。必须尽可能到达顶层业务入口，并区分：

- 当前函数附近直接分叉的业务流程
- 多层 wrapper 之后才出现的业务分叉
- 多个业务入口共享的公共流程
- 跨 subsystem 的复用路径
- 配置、状态、模式、消息类型决定的条件路径
- 注册式、表驱动或其他间接触发路径

不要因为找到一个 caller、一条证据或一个入口就停止。只有主要业务入口组已区分，或者剩余路径被明确记录为 evidence gap，才算完成。

写入 `.impact-scan/codegraph-evidence.md`，内容包括：

- 已执行的每个 MCP 查询及实际工具名
- 原始结果摘要
- 已分析调用路径
- 顶层业务入口及业务含义
- shared flow、branch point、fan-in 和 fan-out
- 间接注册、dispatch 与触发入口证据
- 未解决的 evidence gaps

停止并询问是否继续做业务语义推理。

### Step 4：潜在遗漏流程分析

阅读变更位置以及 Step 3 中发现的重要源码，用 CodeGraph 证据指导阅读。

写入 `.impact-scan/business-reasoning.md`，内容包括：

- 已确认受到影响的业务流程
- 可能受到影响但条件尚未完全确认的流程
- 开发者容易忽略的老功能、旁路、恢复或特殊条件流程
- changed subject 在每条流程中的作用
- 上游如何使用其返回结果、状态变化、数据变化或其他副作用
- 变更可能造成的业务结果差异
- 跨 subsystem 影响
- 仍未解决的 evidence gaps

不要因为缺少证据而推出“无影响”结论。

停止并询问是否生成最终报告。

### Step 5：最终报告

阅读 `references/report-format.md`。

生成 `.impact-scan/impact_report.md`，使用中文 Markdown。报告必须包含：

- 概要
- 本次变更的业务语义
- 已确认影响流程
- 潜在影响流程
- 开发者可能忽略的影响流程
- 共享公共流程与业务分叉
- 跨 subsystem 影响
- 已分析调用路径
- Evidence Gaps
- 业务验证建议
- 局限性

每条影响流程都必须回答：

- 业务入口是什么
- 通过什么调用或触发路径到达 changed subject
- 在什么条件下触发
- changed subject 在流程中起什么作用
- 可能改变什么业务结果
- 当前证据状态和验证建议

确认 `.impact-scan/impact_report.md` 存在后，再简要向用户总结。

## 失败处理

- 如果 CodeGraph MCP 工具不可用，停止并说明无法完成 Step 3。
- 如果调用路径无法到达顶层业务入口，标记为 `evidence_gap`。
- 如果间接注册与触发路径无法闭合，标记为 `indirect_call_evidence_gap`。
- 如果路径规模过大无法完整展开，按业务入口组归纳并标记 `path_explosion_gap`，不要任意截断为固定层数。
- 如果 `.impact-scan/impact_report.md` 缺失，任务未完成。

## 参考文件

- `references/business-impact-rules.md`：业务语义和潜在遗漏流程的判断规则。
- `references/codegraph-mcp-checklist.md`：必须执行的 MCP 查询检查清单。
- `references/report-format.md`：最终业务影响报告格式。
- `references/linux-deployment.md`：MCP 部署要求。
