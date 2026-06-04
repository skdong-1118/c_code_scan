# Ripple

`ripple` 是一个面向 Claude Code / AI Agent 的 C 语言回归影响评审 skill。当前分支采用“纯模型驱动”方案：agent 读取最近一次 diff，直接调用 `CodeGraph MCP`，结合源码证据进行推理，并生成中文 reviewer 风格报告。

硬性分析范围始终是当前分支最后一个 commit：

```text
HEAD~1..HEAD
```

不要把本 skill 用于历史 commit、多个 commit、其他分支、merge-base 范围或自定义范围。

## 为什么做这个版本

旧版本依赖一个较大的 Python 扫描脚本。脚本让流程更稳定，但也限制了模型对复杂 C 工程的深度推理，尤其是：

- 很长的业务调用栈
- 底层通用函数被多个上层业务入口复用
- function pointer、callback、ops table、注册表路径
- 对象生命周期和 pointer alias 分析
- 大改动中需要从业务语义判断重点路径的场景

这个重构分支故意移除扫描脚本，让模型承担主要分析工作。skill 只保留硬性流程、证据要求和报告格式约束。

## 当前结构

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

这个版本没有 `ripple_scan.py` 主流程。

## 运行要求

- Claude Code 或兼容的 agent 运行环境
- Git
- agent 可直接使用的 `CodeGraph MCP` 工具
- 目标 C 仓库的源码读取权限

这个 skill 不调用 Linux 命令行版 `codegraph`。如果环境里只有命令行 `codegraph`，但 agent 没有可用的 CodeGraph MCP 工具，则本版本无法按设计完成 Step 3。

## 默认流程

默认是交互式流程。每次新分析从 Step 1 开始，并在读取旧产物前清空 `.impact-scan`。

```text
Step 1：Scope discovery，发现本次变更范围
Step 2：Risk framing，建立风险假设
Step 3：CodeGraph MCP 深挖，深入调用链和引用证据
Step 4：Source reasoning，结合源码做语义推理
Step 5：Final report，生成最终中文报告
```

只有当用户明确要求 `直接生成报告`、`不用确认`、`全自动`、`one-shot` 或 `CI` 时，才跳过中间确认。

## 输出产物

所有产物都使用 Markdown，方便模型直接读取、修订和引用：

```text
.impact-scan/scope.md
.impact-scan/risk-framing.md
.impact-scan/codegraph-evidence.md
.impact-scan/source-reasoning.md
.impact-scan/risk_report.md
```

终端总结不算完成。最终交付始终是：

```text
.impact-scan/risk_report.md
```

## 分析要求

agent 必须：

- 只检查 `HEAD~1..HEAD`
- 根据变更路径自动推断 subsystem，不默认询问用户
- 使用 `CodeGraph MCP` 查询 definition、references、callers、callees、callchain
- 持续展开调用链，直到到达顶层业务入口/root，或者明确记录 `evidence_gap`
- 不把一层普通 caller 当成 root 证据
- 对 function pointer / callback 路径分析 registration、storage owner、indirect call site 和 trigger entry
- 对 heap object、container、callback opaque、指针字段和 error cleanup path 说明对象生命周期
- 写 reviewer 风格结论，不只输出风险标签

## 默认风险项

```text
memory_leak
memory_safety
abi_layout
pointer_alias_lifetime
error_handling
callback_dispatch
```

目标系统按单线程模型处理。不要增加多线程、多进程或执行模型评审章节。

## 最终报告

最终报告必须是中文 Markdown。必要的专业术语可以保留英文，例如 `CodeGraph`、`business entry`、`fan-in`、`fan-out`、`callback`、`ABI`、`memory-lifetime`、`evidence gap`。

每个 high/medium 风险项都必须回答：

- 改动点
- 风险原因
- 影响流程
- 最坏结果
- 验证建议

报告必须包含已分析调用栈和未解决的 evidence gap。不能把缺少证据解释成低风险。
