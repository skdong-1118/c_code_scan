# 风险规则参考

当需要解释风险分类、生命周期推理或 pointer alias 时，使用本文件。

## 默认启用风险项

```text
memory_leak
memory_safety
abi_layout
pointer_alias_lifetime
error_handling
callback_dispatch
```

目标系统按单线程模型处理。不要加入多线程、多进程或执行模型分析。

## 文件级风险信号

- 修改 public `.h` 文件
- 修改 public / shared path
- 修改 high-risk path
- 修改 legacy path
- 修改 memory-sensitive path
- 大改动，例如单文件变更行数很高

这些信号只表示需要重点关注，不是缺陷证明。

## Symbol 级风险信号

- function declaration / definition 变化
- struct / union / enum / typedef 变化
- callback / function pointer 模式变化
- global data 变化
- function body 内局部上下文变化
- memory allocation / lifetime 变化
- container ownership 变化
- pointer alias / escaped lifetime 变化
- callback opaque / context pointer alias 变化
- semantic behavior keyword 变化
- symbol 位于 public / shared path
- symbol 位于 high-risk path
- symbol 位于 memory-sensitive path
- legacy file reference
- reference 范围很广
- 跨多个 subsystem

风险等级建议：

- high：影响面广、涉及 public/legacy/lifecycle/callback/ABI，或证据显示可能改变既有行为。
- medium：存在明确风险信号，但影响面或调用路径尚未完全闭合。
- low：只有局部低风险改动，且 CodeGraph MCP 和源码证据均未发现明显影响面。

风险等级是 triage 结果，不是缺陷证明。

## 局部函数上下文

如果 diff 只修改函数体内局部变量或字段，不要用局部名查询 CodeGraph，例如：

```text
ret
ctx
tmp
flag
state
```

必须把 diff 行映射到 enclosing function，保留局部证据，再把 enclosing function 作为 Step 3 的 CodeGraph MCP 查询对象。

示例：

```c
ret = flag + 1;
ctx->state = READY;
```

这些改动应该展开 enclosing function，而不是展开 `ret`、`flag`、`ctx` 或 `state`。

## Heap / Object 生命周期证据

heap object 和 escaped object 需要特殊证据，因为 C 指针名经常在不同函数中变化。

重点跟踪：

- `malloc`、`calloc`、`realloc`、`strdup`
- `free`、`destroy`、`cleanup`、`release`
- `ref`、`unref`、`retain`、`get`、`put`
- container insert/remove：`list`、`hash`、`map`、`queue`、`cache`、`tree`
- `obj->field = ptr`、global/static、callback registration
- `void *opaque`、`user_data`、`ctx`、`priv`、`cookie`
- `goto error`、`cleanup`、early return、partial initialization

报告中要保留这些问题：

- success path 和 failure path 上 allocation/free 是否成对？
- container insert 或 callback registration 后 ownership 是否转移？
- callback 触发时 escaped object 是否仍然存活？
- destroy/copy/clone/error-cleanup path 是否覆盖新增或修改的指针字段？
- `realloc` 失败时原指针是否仍然可释放？

## Pointer Alias 指导

不要依赖变量名判断 C 指针安全。相同对象可能在不同位置表现为：

```text
s
ctx
priv
opaque
user_data
struct field
global
container element
```

应该按对象身份跟踪：

- type / struct identity
- field access
- ownership API pairs
- escape points
- error paths

解释该风险时，要写成生命周期证据和建议验证路径，而不是只写风险标签。
