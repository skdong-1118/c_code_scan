# Ripple

`ripple` 是一个面向 Claude Code / AI Agent 的业务影响发现 skill。它从当前分支最后一次代码修改出发，使用 `CodeGraph MCP` 和源码语义推理，发现开发者可能没有意识到的受影响业务流程。

硬性分析范围始终是：

```text
HEAD~1..HEAD
```

不要用于历史 commit、多个 commit、其他分支、merge-base 范围或自定义范围。

## 设计目标

`ripple` 重点回答：

```text
我改了这段代码，哪些业务功能可能被影响？
哪些上游入口会走到这里？
哪些其他流程共享了这段公共逻辑？
哪些老功能、旁路流程或特殊条件容易被忽略？
```

重点场景包括：

- 很长的业务调用栈
- 底层公共流程被多个业务入口复用
- 多层 wrapper 之上才出现业务分叉
- callback、handler table、ops table 等间接触发路径
- 配置、状态、消息类型或模式决定的条件流程
- 跨 subsystem 的共享数据和副作用

## 当前结构

```text
ripple/
  SKILL.md
  agents/openai.yaml
  references/
    business-impact-rules.md
    codegraph-mcp-checklist.md
    linux-deployment.md
    report-format.md
```

## 运行要求

- Claude Code 或兼容的 agent 运行环境
- Git
- agent 可直接使用的 `CodeGraph MCP` 工具
- 目标仓库的源码读取权限

## 默认流程

默认是交互式流程。每次新分析从 Step 1 开始，并在读取旧产物前清空 `.impact-scan`。

```text
Step 1：发现变更范围
Step 2：解释变更的业务语义
Step 3：发现上游业务入口和共享流程
Step 4：分析潜在遗漏流程
Step 5：生成业务影响报告
```

只有当用户明确要求 `直接生成报告`、`不用确认`、`全自动`、`one-shot` 或 `CI` 时，才跳过中间确认。

## 输出产物

```text
.impact-scan/scope.md
.impact-scan/change-semantics.md
.impact-scan/codegraph-evidence.md
.impact-scan/business-reasoning.md
.impact-scan/impact_report.md
```

终端总结不算完成。最终交付始终是：

```text
.impact-scan/impact_report.md
```

## 分析要求

agent 必须：

- 只检查 `HEAD~1..HEAD`
- 根据变更路径自动推断 subsystem
- 把代码差异翻译成业务行为变化
- 使用 `CodeGraph MCP` 发现所有主要上游业务入口
- 持续展开共享公共流程，直到区分不同业务含义的分支
- 主动寻找老功能、旁路、特殊条件和间接触发流程
- 单独输出“开发者可能忽略的影响流程”
- 无法确认的路径标记为 `evidence_gap`，不能当作无影响

## 最终报告

最终报告必须是中文 Markdown，并以业务流程为中心，至少包含：

- 本次变更的业务语义
- 已确认影响流程
- 潜在影响流程
- 开发者可能忽略的影响流程
- 跨 subsystem 影响
- 未闭合证据
- 具体业务验证建议
