# CodeGraph MCP 检查清单

Step 3 使用本文件。目标是从代码关系证据中还原完整业务流程，而不是只找到最近一层 caller。

## 必查证据类型

对每个 changed subject，在环境支持时调用 CodeGraph MCP 查询：

```text
definition
references
callers
callees
callchain
```

不同 CodeGraph MCP server 暴露的工具名可能不同。使用语义最接近的 MCP 工具，并把实际工具名记录到 `.impact-scan/codegraph-evidence.md`。

## 每个 subject 的最小证据

至少记录：

- subject 名称、类型和文件路径
- definition 位置
- reference 所在文件和函数
- direct callers 与 direct callees
- 已展开的 call-chain paths
- 每条路径对应的业务入口、触发条件和业务含义
- 路径状态：`complete_to_entry`、`complete_to_root` 或 evidence gap

## 向上展开规则

不规定调用栈层数，也不要停在第一个 caller。

持续展开 callers，直到：

- 到达可解释业务含义的顶层入口
- 到达 main、service、dispatch、event、command、API、配置、消息或初始化入口
- 同一上游路径已经进入已分析过的业务入口组
- MCP 无法返回更多证据
- 路径规模过大，需要按业务入口组归纳

一层普通 caller 不是业务入口证据。提前停止必须记录为 `evidence_gap`。

## 业务入口分组

不要要求每条路径都逐字符不同。根据业务含义分组：

- 对外接口、命令或管理入口
- 配置加载、下发、同步或查询入口
- 消息接收与 dispatch 入口
- 事件、定时器或状态驱动入口
- 初始化、恢复、升级或兼容入口
- 旧功能、旁路或特殊模式入口

每组至少保留一条代表性完整路径，并说明其他路径为何属于同一业务组。

## 分叉与共享流程

对公共函数或通用流程，必须同时检查：

- changed subject 内部的业务分支
- 直接 callers 处的近层分叉
- 多层 wrapper 之上的远层分叉
- 多个业务入口汇入同一公共流程的 fan-in
- 公共流程向不同处理、状态或结果分发的 fan-out
- 跨 subsystem 的复用路径

找到一个入口不能证明其他入口无影响。必须确认主要业务入口组是否已经覆盖。

## 间接触发路径

如果 changed subject 通过 callback、handler table、ops table、注册 API 或其他表驱动方式触发，还要查询：

- address-taken references
- registration sites
- handler / ops / callback table assignments
- 保存该处理器的对象或表
- indirect call / dispatch sites
- 从 dispatch site 向上的业务触发入口

这些证据用于还原“哪个业务场景会触发该处理器”。只找到 registration、但找不到业务触发入口时，记录为 `indirect_call_evidence_gap`。

## 停止条件

只有满足以下条件后才能结束 Step 3：

- 每个 changed subject 都有 definition 和引用证据
- 主要业务入口组已经识别
- 共享流程的近层和远层业务分叉都已检查
- 间接触发路径已闭合或明确记录缺口
- 跨 subsystem 路径已检查
- 未展开路径都有具体停止原因

“已经找到一条有用证据”不是停止条件。

## 证据记录格式

```markdown
### subject_name

- Definition: ...
- References: ...
- Callers / Callees: ...
- 业务入口组:
  - 入口含义: ...
  - 代表路径: entry -> wrapper -> subject
  - 触发条件: ...
  - 路径状态: complete_to_entry
- 共享流程与分叉:
  - ...
- 间接触发证据:
  - registration: ...
  - dispatch site: ...
  - trigger entry: ...
- Evidence gaps:
  - ...
```
