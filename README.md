# C 回归影响扫描 Skill

`c-regression-impact-scan` 是一个面向 Claude Code 的 C 工程架构流程影响分析 skill，用来判断**最近一次代码修改是否可能影响已有功能、老功能或稳定子系统行为**。

它适合以下场景：

- 大型商用 C 工程
- 代码量较大，按子系统拆分
- 内网部署 Claude Code / AI Agent
- Windows 服务器优先
- AI Agent 能力较弱，需要脚本补齐确定性分析能力
- 优先使用 CodeGraph 做影响面分析

最终输出是 Markdown 检测报告，默认路径：

```text
.impact-scan/risk_report.md
```

## 解决什么问题

在大型 C 工程中，新功能开发经常会修改公共模块、流程入口、跨 subsystem 协作路径或老功能依赖路径，从而影响已有功能。这个 skill 把这类回归影响分析固化为一个可重复流程：

```text
git diff
  -> 提取变更文件和 C 符号
  -> 优先调用 CodeGraph 查询影响面
  -> rg 作为兜底引用搜索
  -> 按子系统聚合影响范围
  -> 按架构流程影响规则打分
  -> 生成 Markdown 检测报告
```

Claude Code 不需要直接阅读百万级仓库。Python 扫描脚本负责生成结构化 JSON 和 Markdown 报告，Claude Code 只需要基于结果做总结和判断。

## 目录结构

```text
c-regression-impact-scan/
  SKILL.md
  agents/openai.yaml
  references/windows-deployment.md
  scripts/c_impact_scan.py
  tests/test_c_impact_scan.py
```

## 环境要求

必需：

- Claude Code
- Git
- Python 3.6 或更高版本

优先推荐：

- `codegraph` / `codegraph.exe`

可选兜底：

- `rg` / `rg.exe`

该工具按 Windows 优先设计，同时兼容 macOS 和 Linux。脚本不依赖 `sed`、`awk`、`xargs`、`find` 等类 Unix 命令。

## 安装方式

把 `c-regression-impact-scan` 目录复制到 Claude Code 的 skills 目录。

推荐使用项目级安装：

```text
你的C工程/
  .claude/
    skills/
      c-regression-impact-scan/
        SKILL.md
        scripts/c_impact_scan.py
```

也可以安装到用户级目录：

```text
C:\Users\<用户名>\.claude\skills\c-regression-impact-scan
```

安装或修改 skill 后，需要重启 Claude Code。

## 触发方式

这个 skill 的描述已经针对自然语言触发优化。用户输入类似下面的话时，Claude Code 应该触发该 skill：

```text
分析最近一次修改对已有功能的影响
检查最近提交有没有影响老功能
看这次改动是否有回归风险
分析这个子系统最近修改的影响
分析这个子系统最近修改是否影响老功能流程
```

如果自动触发失败，可以显式指定：

```text
使用 c-regression-impact-scan skill，分析最近一次修改对已有功能的影响。
```

## 基本用法

在目标 C 工程的仓库根目录执行。

Windows 示例：

```powershell
python .claude\skills\c-regression-impact-scan\scripts\c_impact_scan.py --range HEAD~1..HEAD --subsystem subsys\net --codegraph-mode prefer
```

macOS / Linux 示例：

```bash
python3 .claude/skills/c-regression-impact-scan/scripts/c_impact_scan.py --range HEAD~1..HEAD --subsystem subsys/net --codegraph-mode prefer
```

如果要求必须使用 CodeGraph，不允许降级：

```powershell
python .claude\skills\c-regression-impact-scan\scripts\c_impact_scan.py --range HEAD~1..HEAD --subsystem subsys\net --codegraph-mode required
```

如果允许初始化 CodeGraph：

```powershell
python .claude\skills\c-regression-impact-scan\scripts\c_impact_scan.py --range HEAD~1..HEAD --subsystem subsys\net --codegraph-mode prefer --init-codegraph
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
legacy_paths:
  - legacy/
  - stable/
high_risk_paths:
  - platform/
  - protocol/
  - storage/
  - upgrade/
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
.impact-scan/diff_summary.json
.impact-scan/changed_symbols.json
.impact-scan/impact_paths.json
.impact-scan/references.json
.impact-scan/subsystem_impact.json
.impact-scan/subsystem_analysis.json
.impact-scan/risk_items.json
.impact-scan/architecture_risk_summary.json  # 兼容保留，flow-focused 模式通常为空
.impact-scan/manual_review.json
```

最终交付物是 Markdown 报告：

```text
.impact-scan/risk_report.md
```

编码说明：

- `risk_report.md` 使用 `UTF-8 with BOM` 写入，便于 Windows 记事本、部分旧版编辑器和内网工具正确识别中文。
- JSON 中间文件仍使用标准 UTF-8。
- 脚本调用 Git、CodeGraph、rg 等子进程时，会优先按 UTF-8 解码输出，再做宽容降级，避免 Windows 默认 GBK 解码触发 `UnicodeDecodeError`。

## Markdown 报告内容

生成的检测报告通常包含：

- `Summary`
- `Analysis Layers`
- `High And Medium Risk Items`
- `Architecture Flow Impact Categories`
- `Affected Subsystem Candidates`
- `Reference Evidence`
- `Impact Paths`
- `Must Review Manually`
- `Suggested Regression Checks`
- `Limitations`

报告语言风格为中文描述为主，但专业术语保留英文，例如 `changed tokens`、`subsystem`、`legacy path`、`impact path`、`business flow`、`compile database`、`CodeGraph`。这样便于工程团队阅读，也避免强行翻译造成歧义。

报告会明确区分三层分析：

- `CodeGraph 层`：查找 function/symbol reference、callers/callees、include/import 关系和 subsystem 影响面，提供 impact evidence。
- `Heuristic 层`：根据 changed files、legacy paths、architecture flow paths、reference count 和 subsystem spread 识别流程影响信号，只作为 flow impact triage。
- `Manual Review 层`：对跨 subsystem 流程、legacy feature path、异步/回调流程和人工业务路径确认项，输出到报告里的 `必须人工 Review`，让工程师按清单人工排查。

其中 `Affected Subsystem Candidates` 不只列出命中数量，还会按 subsystem 展开：

- `Impact reason`：说明为什么该 subsystem 可能受影响，例如 legacy path 引用、architecture flow path 或跨 subsystem reference。
- `Changed files`：列出本次提交在该 subsystem 内直接修改的文件。
- `Referenced/impact files`：列出 CodeGraph 或 fallback 搜索命中的引用文件，用于定位老功能调用链。
- `Symbols`：列出把本次修改与该 subsystem 关联起来的 changed token。
- `Suggested checks`：给出该 subsystem 推荐的 legacy tests、business flow replay、跨 subsystem 联调等检查动作。

弱模型或内网 Claude Code 可以优先读取 `.impact-scan/subsystem_analysis.json`，再把其中内容整理进最终 Markdown 报告。

## 检查项说明

### Legacy Feature Path

检查内容：

- 是否直接修改 `legacy_paths`
- changed token 是否被 legacy feature files 引用
- Impact Paths 是否到达老功能路径

风险原因：

老功能路径通常承载稳定行为，任何引用命中都需要优先做回归验证。

### Architecture Flow Path

检查内容：

- 是否修改 `high_risk_paths`
- 是否修改平台、协议、存储、升级、适配、公共流程模块
- 是否影响跨模块流程入口或流程编排点

风险原因：

这些路径往往不是单点功能，而是多个 subsystem 共用的流程节点。

### Cross-Subsystem Impact

检查内容：

- changed token 是否跨 3 个以上 subsystem
- 影响文件是否分布在多个业务域
- 是否需要端到端业务流程回放

风险原因：

跨 subsystem 影响更容易造成局部测试无法覆盖的老功能回归。

### Broad Reference Impact

检查内容：

- changed token 是否被 10 个以上文件引用
- 引用是否集中在稳定路径或老功能路径
- 是否需要按引用分布选择重点回归场景

风险原因：

引用范围越广，越需要用业务流程而不是单文件视角做评估。

## 风险评分

默认风险等级：

```text
high    score >= 8
medium  score 4-7
low     score 0-3
```

部分流程影响权重：

```text
legacy feature path changed        +5
legacy reference from CodeGraph    +5
architecture flow path changed     +4
broad reference impact             +3
cross-subsystem flow impact        +3
large change size                  +2
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
--codegraph-mode prefer
```

如果 CodeGraph 没有结果，会降级使用 `rg`。

当使用：

```text
--codegraph-mode required
```

如果 CodeGraph 不可用，扫描会失败。

## 局限性

- 这是回归风险 triage 工具，不是兼容性证明工具。
- CodeGraph 索引不完整时，Impact Paths 可能不完整。
- 简单 YAML 解析器只支持顶层 list。
- 当前版本聚焦架构流程和功能影响，不做 C 语言语法级 memory、macro、concurrency 等专项风险判断。

## 开发验证

运行单元测试：

```bash
python3 -m unittest c-regression-impact-scan/tests/test_c_impact_scan.py
```

检查 Python 3.6 语法兼容：

```bash
python3 - <<'PY'
import ast
from pathlib import Path
for name in ['c-regression-impact-scan/scripts/c_impact_scan.py', 'c-regression-impact-scan/tests/test_c_impact_scan.py']:
    ast.parse(Path(name).read_text(encoding='utf-8'), filename=name, feature_version=(3, 6))
print('parsed as Python 3.6 grammar')
PY
```
