# C 回归影响扫描 Skill

`c-regression-impact-scan` 是一个面向 Claude Code 的 C 语言回归影响分析 skill，用来判断**最近一次代码修改是否可能影响已有功能、老功能或稳定子系统行为**。

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

在大型 C 工程中，新功能开发经常会修改公共接口、公共模块、宏、结构体、回调表、状态机或生命周期逻辑，从而影响已有功能。这个 skill 把这类回归风险分析固化为一个可重复流程：

```text
git diff
  -> 提取变更文件和 C 符号
  -> 优先调用 CodeGraph 查询影响面
  -> rg 作为兜底引用搜索
  -> 按子系统聚合影响范围
  -> 按架构风险规则打分
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
检查 C 代码改动是否可能导致内存泄漏
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
.impact-scan/diff_summary.json
.impact-scan/changed_symbols.json
.impact-scan/impact_paths.json
.impact-scan/references.json
.impact-scan/subsystem_impact.json
.impact-scan/risk_items.json
.impact-scan/architecture_risk_summary.json
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
- `High And Medium Risk Items`
- `Architecture Risk Categories`
- `Affected Subsystem Candidates`
- `Reference Evidence`
- `Impact Paths`
- `Must Review Manually`
- `Memory Leak Focus`
- `Suggested Regression Checks`
- `Limitations`

报告语言风格为中文描述为主，但专业术语保留英文，例如 `changed symbols`、`subsystem`、`legacy path`、`memory-lifetime`、`ABI`、`callback`、`dispatch table`、`compile database`、`CodeGraph`。这样便于工程团队阅读，也避免强行翻译造成歧义。

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

已有功能可能依赖这些稳定声明、宏、结构体或函数签名。

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

风险原因：

长期运行的老功能、循环调用路径和异常路径更容易暴露泄漏、引用计数不平衡或释放顺序问题。

### 并发和锁

风险类别：`concurrency`

检查内容：

- mutex / spinlock / rwlock / semaphore
- lock / unlock 对称性
- atomic / refcount 操作
- thread / task / timer / interrupt 交互

风险原因：

小范围改动也可能引入竞态、死锁、引用计数原子性问题或对象生命周期错乱。

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

### 宏和配置行为

风险类别：`macro_config`

检查内容：

- `#define`
- `#ifdef`
- `#ifndef`
- `#if`
- `#elif`
- `#undef`
- `CONFIG_*`
- `FEATURE_*`
- `ENABLE_*` / `DISABLE_*`
- 平台相关编译开关

风险原因：

宏变化可能只影响某些平台、产品形态、编译配置或内网定制版本。

### 协议和数据兼容

风险类别：`protocol_compatibility`

检查内容：

- 协议版本
- 字节序转换
- TLV / packet 字段
- opcode / command
- message / frame 解析
- 类 schema 字段变化
- 持久化数据格式

风险原因：

老客户端、旧设备、历史数据、升级回退路径可能依赖旧格式。

### 状态机和时序

风险类别：`state_machine_timing`

检查内容：

- 状态跳转
- event 顺序
- timer 行为
- timeout 值
- retry 行为
- start / stop 顺序

风险原因：

老功能常常依赖隐含的状态顺序、事件顺序和时序假设。

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

### 性能和资源消耗

风险类别：`performance_resource`

检查内容：

- CPU 密集循环
- 内存峰值
- 文件描述符
- socket
- thread
- timer
- queue
- lock contention

风险原因：

回归不一定表现为功能错误，也可能表现为延迟、资源耗尽、吞吐下降或系统不稳定。

### 安全边界

风险类别：`security_boundary`

检查内容：

- auth / permission
- token / credential
- path / command 处理
- 输入校验
- sanitize
- overflow 风险

风险原因：

安全边界相关改动即使功能可用，也应该按高风险处理。

### 构建和部署行为

风险类别：`build_deploy`

检查内容：

- Makefile
- CMake
- link flags
- exported symbols
- install / deploy 行为
- 默认编译选项

风险原因：

C 工程经常存在多个产品形态和构建变体，构建配置变化可能只在部分环境暴露问题。

## 风险评分

默认风险等级：

```text
high    score >= 8
medium  score 4-7
low     score 0-3
```

部分风险权重：

```text
memory_safety           +5
memory_leak             +5
abi_layout              +5
security_boundary       +5
concurrency             +4
ownership_lifetime      +4
protocol_compatibility  +4
state_machine_timing    +4
callback_dispatch       +4
error_handling          +3
macro_config            +3
performance_resource    +3
build_deploy            +3
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
- 没有完整 C 编译信息时，宏展开和条件编译路径可能不完整。
- 函数指针和 callback 关系依赖 CodeGraph 能力，否则只能启发式判断。
- 简单 YAML 解析器只支持顶层 list。
- 架构风险类别主要基于关键词和路径规则，需要人工 review 高风险项。

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
