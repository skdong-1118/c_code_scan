# Windows Intranet Deployment

Use this reference when installing the scan workflow on an offline or intranet Windows server.

## Recommended Tools

Required:

- Git for Windows
- Python 3.6 or newer

Required for the preferred scan path:

- `codegraph.exe`

Recommended fallback tools:

- `rg.exe` from ripgrep
- Universal Ctags, optional

Do not depend on online installers during normal agent runs. Package approved binaries in an internal artifact repository or shared directory. Pin tool versions after validation.

## Suggested Layout

```text
C:\Tools\codegraph\codegraph.exe
C:\Tools\ripgrep\rg.exe
C:\Tools\ctags\ctags.exe
C:\Tools\Python\python.exe
```

Add these directories to the service account `PATH`, or configure the agent to call full paths.

## Offline CodeGraph Setup

1. Download the Windows build on an internet-connected machine.
2. Verify checksum according to internal policy.
3. Copy the binary into the intranet artifact store.
4. Install to a fixed tool directory on the Windows server.
5. Run `codegraph --help` from the same account used by Claude Code.

For a large repository, index during a scheduled window or CI preparation step. Keep `.codegraph` inside the repository unless internal policy requires a separate cache path.

Claude Code can run the scan in preferred mode:

```powershell
python C:\skills\ripple\scripts\ripple_scan.py --range HEAD~1..HEAD --subsystem subsys\net --codegraph-mode prefer
```

Use required mode when you want the scan to fail instead of silently falling back:

```powershell
python C:\skills\ripple\scripts\ripple_scan.py --range HEAD~1..HEAD --subsystem subsys\net --codegraph-mode required
```

## Path and Shell Rules

- Prefer Python `subprocess` argument arrays over shell strings.
- Do not assume `bash`, `sed`, `awk`, `xargs`, or `find`.
- Normalize paths to `/` only in reports. Preserve native paths for command execution.
- Quote paths with spaces when running manually in PowerShell.

## Operational Limits

For million-line repositories, keep result sizes bounded:

- impact depth: 2 by default
- references per symbol: 50 by default
- files listed per subsystem: 20 by default
- generated report directory: `.impact-scan`

The scanner is designed to produce an actionable triage report, not a proof of behavioral compatibility.

## Optional Repository Config

Place `.impact-scan.yml` or `.impact-scan.json` in each C subsystem directory to define:

- public interface paths
- legacy feature paths
- architecture high-risk paths
- memory-sensitive paths
- low-risk paths

This keeps each scan bounded to one subsystem and makes Claude Code less dependent on whole-repository inference.
