# Linux Intranet Deployment

Use this reference when installing the scan workflow on an offline or intranet Linux server.

## Recommended Tools

Required:

- Git
- Python 3.6 or newer
- `codegraph`

Do not depend on online installers during normal agent runs. Package approved Linux binaries in an internal artifact repository or shared directory. Pin tool versions after validation.

## Suggested Layout

```text
/opt/tools/codegraph/bin/codegraph
/opt/tools/python/bin/python3
```

Add these directories to the service account `PATH`, or configure the agent runtime environment with absolute tool paths.

## CodeGraph Setup

1. Install the Linux `codegraph` binary on the target server.
2. Verify checksum according to internal policy.
3. Ensure the Claude Code service account can run `codegraph --help`.
4. For large repositories, build or refresh the CodeGraph index during a scheduled window or CI preparation step.
5. Keep `.codegraph` inside the repository unless internal policy requires a separate cache path.

Claude Code should run the scan in CodeGraph required mode:

```bash
python3 .claude/skills/ripple/scripts/ripple_scan.py --range HEAD~1..HEAD --subsystem subsys/net --codegraph-mode required
```

Required mode fails fast when CodeGraph is unavailable:

```bash
python3 .claude/skills/ripple/scripts/ripple_scan.py --range HEAD~1..HEAD --subsystem subsys/net --codegraph-mode required
```

## Path and Shell Rules

- Prefer Python `subprocess` argument arrays over shell strings.
- Keep `git`, `python3`, and `codegraph` available on `PATH`.
- Normalize paths to `/` in reports and configuration.
- Run commands from the target repository root.

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
