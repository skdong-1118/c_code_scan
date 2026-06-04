# CodeGraph MCP 检查清单

Step 3 使用本文件。目标是让模型推理建立在证据上，同时保留模型对证据含义的判断空间。

## 必查证据类型

对每个 selected changed subject，在环境支持时调用 CodeGraph MCP 查询以下证据：

```text
definition
references
callers
callees
callchain
```

不同内网 CodeGraph MCP server 暴露的工具名可能不同。使用语义最接近的 MCP 工具，并把实际工具名记录到 `.impact-scan/codegraph-evidence.md`。

## 每个 subject 的最小证据

每个 subject 至少记录：

- subject 名称和文件路径
- definition 位置
- reference 文件 / 函数
- direct callers
- direct callees
- call-chain paths
- 每条 path 是否到达 `complete_to_entry`、`complete_to_root`，或者只能标记 evidence gap

## 调用链展开规则

不要停在第一个 caller。

持续展开 callers，直到满足以下条件之一：

- 到达顶层 business entry
- 到达 root / dispatch / service / main / task / event 入口
- MCP 工具无法返回更多证据
- path explosion 导致结果不可读

如果在到达 entry/root 前停止，记录为 `evidence_gap`。缺少证据不是低风险。

## 分叉与共享流程规则

对底层公共函数或 common flow，必须显式关注：

- changed function 内部的 branch points
- 直接共享该函数的近层 callers
- 多层 wrapper 之上才分叉的深层 upstream fan-in
- 进入 state、queue、callback、lifecycle、error helper 的 downstream fan-out

## Function Pointer 与 Callback 规则

对于 `callback_dispatch` 或 `pointer_alias_lifetime` 风险，普通 caller chain 不够。

还要查：

- address-taken references：`func`、`&func`
- ops / handler / callback table 赋值
- registration APIs
- storage owner：global table、struct field、queue/list node、context object
- indirect call sites
- trigger business entry

如果只找到 registration，但找不到 trigger path，记录为 `indirect_call_evidence_gap`。

## 证据记录格式

在 `.impact-scan/codegraph-evidence.md` 中使用以下格式：

```markdown
### subject_name

- Definition: ...
- References: ...
- Callers: ...
- Callees: ...
- Call stacks:
  - entry -> wrapper -> subject (`complete_to_entry`)
  - middle_caller -> subject (`evidence_gap`, shallow ordinary caller)
- Callback / function pointer evidence:
  - registration: ...
  - storage owner: ...
  - indirect call site: ...
  - trigger entry: ...
- Evidence gaps:
  - ...
```
