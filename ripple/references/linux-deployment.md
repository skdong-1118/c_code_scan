# Linux 内网部署说明

在离线或内网 Linux 服务器上部署纯 MCP 版 `ripple` 时使用本文件。

## 必需工具

- Git
- Claude Code 或兼容的 agent 运行环境
- 已配置给 agent 使用的 CodeGraph MCP server
- 目标 C 仓库的源码读取权限

本版本的 `ripple` 工作流不需要 Python。

## CodeGraph MCP 要求

agent 必须能使用 CodeGraph MCP 工具，并且这些工具能够提供或近似提供：

```text
definition
references
callers
callees
callchain
```

对于 function pointer 和 callback 分析，MCP server 最好还能提供：

```text
address-taken references
registration sites
handler table assignments
indirect call sites
```

如果这些工具不可用，agent 必须把缺失证据记录为 `indirect_call_evidence_gap`。

## 仓库准备

从目标仓库根目录运行 agent。仓库必须能提供足够源码上下文，并支持以下命令：

```bash
git diff --name-status HEAD~1..HEAD
git diff --stat HEAD~1..HEAD
git diff --unified=80 HEAD~1..HEAD -- '*.c' '*.h'
```

工作流会把 Markdown 产物写入：

```text
.impact-scan/
```

## 运行注意事项

- 本版本不要依赖 shell `codegraph` 命令。
- 不要用 `rg` 或 Grep 替代 CodeGraph 证据。
- 在 `.impact-scan/codegraph-evidence.md` 中记录实际使用的 MCP 工具名。
- 如果 MCP 不可用，在 Step 3 前停止，并说明本版本无法完成分析。
