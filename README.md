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
python3 .claude/skills/ripple/scripts/ripple_scan.py --range HEAD~1..HEAD --codegraph-mode required
```

默认必须使用 CodeGraph，不允许降级到 `rg`。如果 CodeGraph 不可用，扫描会失败。

```bash
python3 .claude/skills/ripple/scripts/ripple_scan.py --range HEAD~1..HEAD --codegraph-mode required
```

如果允许初始化 CodeGraph：

```bash
python3 .claude/skills/ripple/scripts/ripple_scan.py --range HEAD~1..HEAD --codegraph-mode required --init-codegraph
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

默认运行方式就是 interactive guided workflow。内网模型能力较弱或仓库较大时，不要一次跑完整流程；应把分析拆成 scope discovery、triage、focused expansion、report 四步，避免模型一次性消化过多上下文。

默认交互规则：

- 用户只说“分析最近一次修改对已有功能的影响”或“重新分析本项目”时，默认走交互式分步流程。
- Step 0 不再要求用户选择 subsystem、symbol、风险项或忽略路径；默认先读取当前分支最后一个 commit 的 git 修改路径，再实时推断完整 subsystem 路径，并使用内置风险项。
- 每次新分析开始前会主动清空输出目录里的旧分析结果；`discover` 和 one-shot 会重建 `.impact-scan/`，后续 `triage` / `expand` / `report` 不会清空前一步产物。
- Step 1 `discover` 完成后，Claude Code 应该展示变更范围摘要，并等待你确认扫描范围。
- Step 2 `triage` 完成后，Claude Code 应该展示风险数量和 expansion candidates，并等待你确认是否继续。
- Step 3 `expand` 完成后，Claude Code 应该展示 CodeGraph 命中和 reference evidence，并等待你确认是否生成报告。
- Step 4 `report` 完成后，才算最终完成，必须生成 `.impact-scan/risk_report.md`。

只有当你明确说“直接生成报告”、“全自动”、“不用确认”、“one-shot” 或用于 CI 时，才允许跳过中间确认。

```bash
python3 .claude/skills/ripple/scripts/ripple_scan.py --step discover --range HEAD~1..HEAD --codegraph-mode required
python3 .claude/skills/ripple/scripts/ripple_scan.py --step triage --range HEAD~1..HEAD --codegraph-mode required
python3 .claude/skills/ripple/scripts/ripple_scan.py --step expand --range HEAD~1..HEAD --codegraph-mode required
python3 .claude/skills/ripple/scripts/ripple_scan.py --step report --range HEAD~1..HEAD --codegraph-mode required
```

四步输出的核心文件：

- `scope_discovery.json`：变更范围、C/header 文件、推断 subsystem。
- `triage_summary.json`：快速风险分级、用户关注项覆盖情况、建议展开的 symbol。
- `expansion_summary.json`：实际展开的 symbol、CodeGraph 命中情况、业务入口聚类和分叉点数量。
- `call_chain_analysis.json`：CodeGraph 深调用链证据，包含 business entry groups、branch points、上游 fan-in、下游 fan-out 和需要源码语义复核的路径。
- `step3a_call_paths.json` 到 `step3f_completion.json`：Step 3 固化子产物，分别覆盖 call paths、business entries、branch points、state flow、evidence gaps 和 completion。
- `workflow_state.json`：记录已完成步骤和下一步，弱模型应按 `next_required_step` 执行。
- `risk_report.md`：最终中文 Markdown 检测报告。

`expand` 步不会默认展开所有 changed symbols，而是优先展开用户指定 symbol、高风险 symbol、public interface symbol、memory-lifetime symbol 和 pointer-alias-lifetime symbol。它会对这些 symbol 做深调用链分析，兼顾本函数内分叉、近层 caller 分叉、深层业务入口 fan-in 和下游 fan-out。这样更适合百万级仓库和慢速内网模型。

调用链不能由 agent 主观判断“够了”就停止，也不能把固定层级当成分析目标。Step 3 的目标是沿调用关系追到顶层 business entry 或 root caller；深度参数只是 CodeGraph 搜索预算。每条 business entry path 必须标记为 `complete_to_entry`、`complete_to_root`、`incomplete_depth_limit`、`truncated_path_budget` 或 `evidence_gap`，其中只有前两者表示成功闭合，后三者都是 evidence gap。如果 Step 3 没有生成 `step3f_completion.json`，或其中 `step3_complete` 不是 `true`，Step 4 `report` 会拒绝生成最终报告。

如果 Claude Code 在 `triage` 或 `expand` 后只在终端里回复了分析结论，没有生成 `.impact-scan/risk_report.md`，说明 agent 没有继续执行 `--step report`。可直接补跑：

```bash
python3 .claude/skills/ripple/scripts/ripple_scan.py --step report --range HEAD~1..HEAD --codegraph-mode required
```

如果前面的 JSON 中间文件也不存在，则直接运行 one-shot：

```bash
python3 .claude/skills/ripple/scripts/ripple_scan.py --range HEAD~1..HEAD --codegraph-mode required
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

当 `discover` 根据最新一次 git 修改推断出 scope，例如：

```text
subsys/net
```

配置里的：

```text
include/
```

会被解释为：

```text
subsys/net/include/
```

如果不传 `--subsystem`，`discover` 会先读取 `HEAD~1..HEAD` 的 changed files；若本次变更只落在一个完整 subsystem 前缀下，例如：

```text
fosip/nbm/api.c
```

脚本会直接推断扫描范围为：

```text
fosip/nbm
```

如果只传入叶子目录名，例如：

```text
--subsystem nbm
```

而当前分支最后一个 commit 的真实变更路径是：

```text
fosip/nbm/api.c
```

`discover` 同样会先读取 `HEAD~1..HEAD` 的 changed files，并自动解析为：

```text
--subsystem fosip/nbm
```

如果同一个叶子目录在本次变更里命中多个候选路径，例如 `fosip/nbm` 和 `product/nbm`，脚本不会猜测；候选会写入 `scope_discovery.json` 的 `subsystem_resolution_candidates`，等待用户确认完整路径。

脚本也支持在子系统目录下使用 `.impact-scan.json`。

## 输出文件

默认输出目录为：

```text
.impact-scan/
```

开始新分析时，脚本会先清空并重建输出目录，避免读取上一次分析留下的 JSON 或报告。清理只发生在 `--step discover` 或 one-shot 入口；`triage`、`expand`、`report` 会保留并读取当前分析的前序产物。

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
- `Lifecycle Risk Evidence`
- `Memory Leak Focus`
- `Pointer Alias Lifetime Focus`
- `Suggested Regression Checks`
- `Limitations`

报告格式、风险评分、生命周期证据和指针别名规则已经下沉到 reference 文件，避免 README 与 skill 执行规则重复维护：

- `ripple/references/report-format.md`：报告章节、中文表达、confidence 和限制说明。
- `ripple/references/risk-rules.md`：风险类别、评分、局部变量归属 enclosing function、堆对象生命周期、pointer alias 规则。

弱模型或内网 Claude Code 可以优先读取 `.impact-scan/risk_items.json` 和 `.impact-scan/subsystem_analysis.json`，再按 `report-format.md` 整理最终 Markdown 报告。

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
- 架构风险类别主要基于关键词和路径规则，需要结合生命周期风险证据验证高风险项。

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
