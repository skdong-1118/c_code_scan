# Linux Intranet Deployment

Use this reference when installing the pure MCP `ripple` workflow on an offline or intranet Linux server.

## Required Tools

- Git
- Claude Code or a compatible agent runtime
- CodeGraph MCP server configured for the agent
- Read access to the target C repository

Python is not required for the `ripple` workflow in this version.

## CodeGraph MCP Expectations

The agent must have CodeGraph MCP tools that can provide, or approximate:

```text
definition
references
callers
callees
callchain
```

For function pointer and callback analysis, the MCP server should ideally expose evidence for:

```text
address-taken references
registration sites
handler table assignments
indirect call sites
```

If those tools are unavailable, the agent must record the missing evidence as `indirect_call_evidence_gap`.

## Repository Preparation

Run the agent from the target repository root. The repository must have enough source context for:

```bash
git diff --name-status HEAD~1..HEAD
git diff --stat HEAD~1..HEAD
git diff --unified=80 HEAD~1..HEAD -- '*.c' '*.h'
```

The workflow writes Markdown artifacts under:

```text
.impact-scan/
```

## Operational Notes

- Do not rely on shell `codegraph` commands for this version.
- Do not rely on `rg` or Grep as substitutes for CodeGraph evidence.
- Keep MCP tool names documented in `.impact-scan/codegraph-evidence.md`.
- If MCP is unavailable, stop before Step 3 and report that this skill version cannot complete the analysis.
