# CodeGraph MCP Checklist

Use this reference during Step 3. The goal is to make model reasoning evidence-driven while still letting the model decide what the evidence means.

## Required Query Set

For every selected changed subject, call CodeGraph MCP tools for these evidence types when available:

```text
definition
references
callers
callees
callchain
```

The exact MCP tool names depend on the local CodeGraph server. Use the closest available tool and record the actual tool name in `.impact-scan/codegraph-evidence.md`.

## Minimum Evidence Per Subject

For each subject, record:

- subject name and file
- definition location
- reference files/functions
- direct callers
- direct callees
- call-chain paths
- whether each path reached `complete_to_entry`, `complete_to_root`, or an evidence gap

## Call-Chain Expansion Rule

Do not stop at the first caller.

Continue expanding callers until one of these is true:

- a top-level business entry is reached
- a root/dispatch/service/main/task/event entry is reached
- the MCP tool cannot return more evidence
- path explosion makes the result unreadable

If expansion stops before an entry/root, record `evidence_gap`. Missing evidence is not low risk.

## Branch and Shared-Flow Rule

For changed low-level/common functions, explicitly look for:

- branch points inside the changed function
- near callers that share the function directly
- deeper upstream fan-in where business flows split many wrappers above
- downstream fan-out into state, queue, callback, lifecycle, or error helpers

## Function Pointer and Callback Rule

For `callback_dispatch` or `pointer_alias_lifetime` risks, ordinary caller chains are not enough.

Also look for:

- address-taken references: `func`, `&func`
- assignments into ops/handler/callback tables
- registration APIs
- storage owner: global table, struct field, queue/list node, context object
- indirect call sites
- trigger business entry

If registration is found but trigger path is not found, record `indirect_call_evidence_gap`.

## Evidence Notes Format

Use this format inside `.impact-scan/codegraph-evidence.md`:

```markdown
### subject_name

- Definition: ...
- References: ...
- Callers: ...
- Callees: ...
- Call stacks:
  - entry -> wrapper -> subject (`complete_to_entry`)
  - middle_caller -> subject (`evidence_gap`, shallow ordinary caller)
- Callback/function pointer evidence:
  - registration: ...
  - storage owner: ...
  - indirect call site: ...
  - trigger entry: ...
- Evidence gaps:
  - ...
```
