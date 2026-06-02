# C 回归影响扫描 Skill

`ripple` 是一个面向 Claude Code 的 C 语言回归影响分析 skill，用来判断**当前分支最后一个 commit 是否可能影响已有功能、老功能或稳定子系统行为**。

硬性限制：本工具只分析当前分支最后一个 commit，也就是固定范围：

```text
HEAD~1..HEAD
```

不要把它用于历史区间、多个 commit、其他分支或任意自定义 commit range。脚本会拒绝非 `HEAD~1..HEAD` 的 `--range`，防止 agent 误扫其他提交。

它适合以下场景：

- 大型商用 C 工程
- 代码量较大，按子系统拆分
- 内网部署 Claude Code / AI Agent
- Linux 服务器部署运行
- AI Agent 能力较弱，需要脚本补齐确定性分析能力
- CodeGraph 已部署在 Linux 上，优先使用 CodeGraph 做影响面分析

最终输出是 Markdown 检测报告，默认路径：

```text
.impact-scan/risk_report.md
```

注意：终端或 Claude Code 对话里的总结不等于最终交付。一次分析只有在 `.impact-scan/risk_report.md` 已生成后才算完成。

## 解决什么问题

在大型 C 工程中，新功能开发经常会修改公共接口、公共模块、结构体、回调表或生命周期逻辑，从而影响已有功能。这个 skill 把这类回归风险分析固化为一个可重复流程：

```text
git diff
  -> 提取变更文件和 C 符号
  -> 优先调用 CodeGraph 查询影响面
  -> 按子系统聚合影响范围
  -> 按架构风险规则打分
  -> 生成 Markdown 检测报告
```

Claude Code 不需要直接阅读百万级仓库。Python 扫描脚本负责生成结构化 JSON 和 Markdown 报告，Claude Code 只需要基于结果做总结和判断。

## 目录结构

```text
ripple/
  SKILL.md
  agents/openai.yaml
  references/linux-deployment.md
  scripts/ripple_scan.py
  tests/test_ripple_scan.py
```

## 环境要求

必需：

- Claude Code
- Git
- Python 3.6 或更高版本

优先推荐：

- `codegraph`

该工具按 Linux 部署运行设计。脚本使用 Python `subprocess` 参数数组调用 `git` 和 `codegraph`，只查找 Linux 命令名。

## 安装方式

把 `ripple` 目录复制到 Claude Code 的 skills 目录。

推荐使用项目级安装：

```text
你的C工程/
  .claude/
    skills/
      ripple/
        SKILL.md
        scripts/ripple_scan.py
```

也可以安装到用户级目录：

```text
~/.claude/skills/ripple
```

安装或修改 skill 后，需要重启 Claude Code。

## 触发方式

这个 skill 的描述已经针对自然语言触发优化。用户输入类似下面的话时，Claude Code 应该触发该 skill：

```text
分析最近一次修改对已有功能的影响
检查最近提交有没有影响老功能
看这次改动是否有回归风险
分析这个子系统最近修改的影响
检查 C 代码改动是否可能导致内存泄漏
```

如果自动触发失败，可以显式指定：

```text
使用 ripple skill，分析最近一次修改对已有功能的影响。
```

## 基本用法

在目标 C 工程的仓库根目录执行。

```bash
python3 .claude/skills/ripple/scripts/ripple_scan.py --range HEAD~1..HEAD --subsystem subsys/net --codegraph-mode required
```

默认必须使用 CodeGraph，不允许降级到 `rg`。如果 CodeGraph 不可用，扫描会失败。

```bash
python3 .claude/skills/ripple/scripts/ripple_scan.py --range HEAD~1..HEAD --subsystem subsys/net --codegraph-mode required
```

如果允许初始化 CodeGraph：

```bash
python3 .claude/skills/ripple/scripts/ripple_scan.py --range HEAD~1..HEAD --subsystem subsys/net --codegraph-mode required --init-codegraph
```

当前脚本初始化时会尝试：

```text
codegraph init
codegraph index
```

如果你们内网安装的 CodeGraph 要求使用：

```text
codegraph init -i
```

可以先手工初始化 CodeGraph，或者后续把脚本初始化逻辑调整为优先执行 `codegraph init -i`。

## 推荐分步流程

内网模型能力较弱或仓库较大时，推荐使用 interactive guided workflow。它把一次完整分析拆成 scope discovery、triage、focused expansion、report 四步，避免模型一次性消化过多上下文。

默认交互规则：

- 用户只说“分析最近一次修改对已有功能的影响”时，默认走交互式分步流程。
- Step 0 不再要求用户选择 subsystem、symbol、风险项或忽略路径；默认从当前分支最后一个 commit 自动推断，并使用内置风险项。
- Step 1 `discover` 完成后，Claude Code 应该展示变更范围摘要，并等待你确认扫描范围。
- Step 2 `triage` 完成后，Claude Code 应该展示风险数量和 expansion candidates，并等待你确认是否继续。
- Step 3 `expand` 完成后，Claude Code 应该展示 CodeGraph 命中和 reference evidence，并等待你确认是否生成报告。
- Step 5 `report` 完成后，才算最终完成，必须生成 `.impact-scan/risk_report.md`。

只有当你明确说“直接生成报告”、“全自动”、“不用确认”、“one-shot” 或用于 CI 时，才允许跳过中间确认。

```bash
python3 .claude/skills/ripple/scripts/ripple_scan.py --step discover --range HEAD~1..HEAD --subsystem subsys/net --codegraph-mode required
python3 .claude/skills/ripple/scripts/ripple_scan.py --step triage --range HEAD~1..HEAD --subsystem subsys/net --codegraph-mode required
python3 .claude/skills/ripple/scripts/ripple_scan.py --step expand --range HEAD~1..HEAD --subsystem subsys/net --codegraph-mode required
python3 .claude/skills/ripple/scripts/ripple_scan.py --step report --range HEAD~1..HEAD --subsystem subsys/net --codegraph-mode required
```

四步输出的核心文件：

- `scope_discovery.json`：变更范围、C/header 文件、推断 subsystem。
- `triage_summary.json`：快速风险分级、用户关注项覆盖情况、建议展开的 symbol。
- `expansion_summary.json`：实际展开的 symbol、CodeGraph 命中情况。
- `risk_report.md`：最终中文 Markdown 检测报告。

`expand` 步不会默认展开所有 changed symbols，而是优先展开用户指定 symbol、高风险 symbol、public interface symbol、memory-lifetime symbol 和 pointer-alias-lifetime symbol。这样更适合百万级仓库和慢速内网模型。

如果 Claude Code 在 `triage` 或 `expand` 后只在终端里回复了分析结论，没有生成 `.impact-scan/risk_report.md`，说明 agent 没有继续执行 `--step report`。可直接补跑：

```bash
python3 .claude/skills/ripple/scripts/ripple_scan.py --step report --range HEAD~1..HEAD --subsystem subsys/net --codegraph-mode required
```

如果前面的 JSON 中间文件也不存在，则直接运行 one-shot：

```bash
python3 .claude/skills/ripple/scripts/ripple_scan.py --range HEAD~1..HEAD --subsystem subsys/net --codegraph-mode required
```

## Focus 配置

默认情况下，Claude Code 不需要询问你 Step 0 的关注重点：

- subsystem 从当前分支最后一个 commit 的变更文件自动推断；
- focus symbol 默认不需要填写；
- ignore paths 根据变更文件和低风险路径配置自动处理；
- 风险项使用内置默认集合。

内置默认检查的风险项：

```text
memory_leak
memory_safety
abi_layout
pointer_alias_lifetime
error_handling
callback_dispatch
```

目标系统按单线程模型处理。

如果你确实需要覆盖默认行为，可以在仓库根目录或子系统目录放置 `.impact-scan-focus.yml`，也可以通过 `--focus path\to\focus.yml` 指定任意配置文件。

```yaml
subsystem: subsys/net
focus_symbols:
  - api_open
  - session_alloc
ignore_paths:
  - tests/
  - docs/
legacy_paths:
  - legacy/
  - stable/
public_interfaces:
  - include/
  - exported/
notes:
  - old client must not change
```

字段说明：

- `subsystem`：默认扫描的子系统路径；没有显式传 `--subsystem` 时会使用它。
- `focus_symbols`：用户最关心的 function/symbol，`expand` 会优先查这些 symbol 的 impact。
- `ignore_paths`：从 changed files、changed symbols、reference evidence、risk items 和最终报告中排除的路径前缀。
- `legacy_paths`：补充老功能路径，用来识别 legacy hit 和老功能影响面。
- `public_interfaces`：补充公共接口路径，用来识别 public interface 变更。
- `notes`：会写入报告的人工关注备注。

命令行参数 `--focus-symbols`、`--ignore-paths` 会覆盖配置文件中的同名字段。

## 子系统配置

建议把 `.impact-scan.yml` 放在每个子系统目录下，而不是仓库根目录。

```text
repo/
  subsys/net/
    .impact-scan.yml
    include/
    legacy/
```

示例配置：

```yaml
public_interfaces:
  - include/
  - sdk/include/
legacy_paths:
  - legacy/
  - stable/
high_risk_paths:
  - platform/
  - protocol/
  - storage/
  - upgrade/
memory_sensitive_paths:
  - core/session/
  - buffer/
  - memory/
low_risk_paths:
  - tests/
  - docs/
```

当指定：

```text
--subsystem subsys/net
```

配置里的：

```text
include/
```

会被解释为：

```text
subsys/net/include/
```

脚本也支持在子系统目录下使用 `.impact-scan.json`。

## 输出文件

默认输出目录为：

```text
.impact-scan/
```

主要输出文件：

```text
.impact-scan/risk_report.md
.impact-scan/scan_config.json
.impact-scan/codegraph_status.json
.impact-scan/scope_discovery.json
.impact-scan/triage_summary.json
.impact-scan/expansion_summary.json
.impact-scan/diff_summary.json
.impact-scan/changed_symbols.json
.impact-scan/impact_paths.json
.impact-scan/references.json
.impact-scan/subsystem_impact.json
.impact-scan/subsystem_analysis.json
.impact-scan/risk_items.json
.impact-scan/architecture_risk_summary.json
.impact-scan/manual_review.json
```

最终交付物是 Markdown 报告：

```text
.impact-scan/risk_report.md
```

编码说明：

- `risk_report.md` 使用标准 UTF-8 写入。
- JSON 中间文件仍使用标准 UTF-8。
- 脚本调用 Git、CodeGraph 等子进程时，按 UTF-8 解码输出，并在异常字节出现时使用替换字符兜底。

## Markdown 报告内容

生成的检测报告通常包含：

- `Summary`
- `Analysis Layers`
- `High And Medium Risk Items`
- `Architecture Risk Categories`
- `Affected Subsystem Candidates`
- `Reference Evidence`
- `Impact Paths`
- `Must Review Manually`
- `Memory Leak Focus`
- `Pointer Alias Lifetime Focus`
- `Suggested Regression Checks`
- `Limitations`

报告语言风格为中文描述为主，但专业术语保留英文，例如 `changed symbols`、`subsystem`、`legacy path`、`memory-lifetime`、`ABI`、`callback`、`dispatch table`、`compile database`、`CodeGraph`。这样便于工程团队阅读，也避免强行翻译造成歧义。

报告会明确区分三层分析：

- `CodeGraph 层`：查找 function/symbol reference、callers/callees、include/import 关系和 subsystem 影响面，提供 impact evidence。
- `Heuristic 层`：根据变量名、函数名、路径、diff 内容、risk category 和 deterministic scoring 识别风险信号，只作为 risk triage。
- `Manual Review 层`：对同一地址不同变量名、pointer alias、ownership transfer、callback/async flow、struct field 传递、error cleanup path 等工具难以证明的问题，输出到报告里的 `必须人工 Review`，让工程师按清单人工排查。对于 C 指针风险，不依赖局部变量名做判断，而是按对象类型、struct 字段、ownership API 和逃逸点追踪。

其中 `Affected Subsystem Candidates` 不只列出命中数量，还会按 subsystem 展开：

- `Impact reason`：说明为什么该 subsystem 可能受影响，例如 public interface 变更、legacy path 引用、high-risk architecture path、memory-sensitive path 或跨 subsystem reference。
- `Changed files`：列出本次提交在该 subsystem 内直接修改的文件。
- `Referenced/impact files`：列出 CodeGraph 搜索命中的引用文件，用于定位老功能调用链。
- `Symbols`：列出把本次修改与该 subsystem 关联起来的 changed symbol。
- `Risk categories`：列出 `memory_leak`、`abi_layout`、`pointer_alias_lifetime`、`callback_dispatch` 等架构风险类别。
- `Suggested checks`：给出该 subsystem 推荐的 legacy tests、ABI/layout review、memory-lifetime check、protocol compatibility 验证等检查动作。

弱模型或内网 Claude Code 可以优先读取 `.impact-scan/subsystem_analysis.json`，再把其中内容整理进最终 Markdown 报告。

## 检查项说明

### 公共接口变化

检查内容：

- `.h` 文件
- `include/`
- `public/`
- `api/`
- `sdk/include/`
- 共享 `common/` 路径

风险原因：

已有功能可能依赖这些稳定声明、结构体或函数签名。

### ABI 和结构体布局风险

风险类别：`abi_layout`

检查内容：

- `struct`
- `union`
- `enum`
- `typedef`
- 字段顺序变化
- 字段类型变化
- `sizeof`
- packing / alignment
- 导出符号或可见性变化

风险原因：

即使函数名不变，二进制布局变化也可能破坏老模块、动态库接口或跨模块数据访问。

### 内存安全

风险类别：`memory_safety`

检查内容：

- `memcpy`
- `memmove`
- `memset`
- 字符串拷贝和格式化函数
- 长度、大小、边界处理
- overflow / bounds 相关逻辑

风险原因：

这类改动可能引入越界访问、内存破坏、use-after-free、double free 或数据损坏。

### 内存泄漏和生命周期

风险类别：`memory_leak`、`ownership_lifetime`

检查内容：

- `malloc`
- `calloc`
- `realloc`
- `strdup`
- `free`
- `release`
- `destroy`
- `cleanup`
- `refcount` / `refcnt`
- 所有权转移
- init / destroy 顺序
- 错误路径释放逻辑
- 插入链表、树、hash、queue、map、cache 等数据结构
- `list_add` / `list_del`
- `rb_insert` / `rb_erase`
- `hash_add` / `hash_del`
- `queue_push` / `queue_remove`
- `map_put` / `cache_insert`

风险原因：

长期运行的老功能、循环调用路径和异常路径更容易暴露泄漏、引用计数不平衡或释放顺序问题。对象插入容器后通常发生 ownership 转移，如果异常路径没有从容器摘除、重复插入未处理、销毁路径没有遍历释放，也会造成泄漏。

### 指针别名与生命周期

风险类别：`pointer_alias_lifetime`

检查内容：

- `void *opaque` / `void *ctx` / `void *user_data` / `void *priv` / `void *cookie` 被 cast 回变更对象类型
- struct 字段赋值（`->field = ...`）、全局变量赋值、容器插入操作
- callback 注册或 dispatch table 中传递的对象指针
- 新增或修改指针字段、refcount 字段、list-node 字段时，destroy/copy/clone/error-cleanup 路径是否同步更新
- `memcpy` / `memset` / `sizeof` / `offsetof` / `container_of` 作用于含指针/refcount/list node 的结构体

风险原因：

C 语言中同一个对象可能以不同变量名出现（如 `s` → `ctx` → `opaque` → `user_data`），经过 struct 字段赋值、容器插入、callback 注册或模块级 registry 后逃逸出当前函数作用域。仅靠局部变量名 grep 无法正确追踪对象生命周期。必须在报告里按对象类型、字段访问、ownership API 和逃逸点追踪，而非按变量名判断安全性。

### 错误处理路径

风险类别：`error_handling`

检查内容：

- return 值
- errno / error code
- `goto error`
- `NULL` 判断
- cleanup 路径
- retry / failure 行为

风险原因：

老功能可能依赖历史错误码、返回值语义、容错行为或 cleanup 副作用。

### 回调和分发表

风险类别：`callback_dispatch`

检查内容：

- 函数指针
- callback 注册
- ops table
- handler table
- dispatch table
- command table

风险原因：

这类关系在普通调用图中容易漏掉，但在 C 架构中经常是核心扩展点。

## 风险评分

默认风险等级：

```text
high    score >= 8
medium  score 4-7
low     score 0-3
```

部分风险权重：

默认只启用以下风险类别参与评分和报告汇总：

```text
memory_safety           +5
memory_leak             +5
abi_layout              +5
pointer_alias_lifetime  +5
callback_dispatch       +4
error_handling          +3
```

评分只是 triage 信号，不等价于已经证明存在缺陷。

## CodeGraph 行为

CodeGraph 是优先使用的影响面后端。脚本会尝试：

```text
codegraph impact <symbol>
codegraph impact --symbol <symbol>
```

当使用：

```text
--codegraph-mode required
```

如果 CodeGraph 不可用，扫描会失败。默认就是 `required`，不会降级使用 `rg`。

## 局限性

- 这是回归风险 triage 工具，不是兼容性证明工具。
- 没有完整 C 编译信息时，跨文件类型关系和 include 路径可能不完整。
- 函数指针和 callback 关系依赖 CodeGraph 能力，否则只能启发式判断。
- 简单 YAML 解析器只支持顶层 list。
- 架构风险类别主要基于关键词和路径规则，需要人工 review 高风险项。

## 开发验证

运行单元测试：

```bash
python3 -m unittest ripple/tests/test_ripple_scan.py
```

检查 Python 3.6 语法兼容：

```bash
python3 - <<'PY'
import ast
from pathlib import Path
for name in ['ripple/scripts/ripple_scan.py', 'ripple/tests/test_ripple_scan.py']:
    ast.parse(Path(name).read_text(encoding='utf-8'), filename=name, feature_version=(3, 6))
print('parsed as Python 3.6 grammar')
PY
```
