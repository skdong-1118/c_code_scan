# Risk Rules Reference

Use this reference when you need scoring details, lifecycle reasoning, or pointer alias explanation for `ripple`.

## Enabled Categories

Default enabled risk categories:

```text
memory_leak
memory_safety
abi_layout
pointer_alias_lifetime
error_handling
callback_dispatch
```

The target systems are single-threaded. Do not add threading, multiprocess, or execution-model analysis.

## File Weights

- changed public `.h` file: +4
- changed public/shared path: +3
- configured high-risk path: +3
- configured legacy path: +3
- configured memory-sensitive path: +2
- large change (>= 80 lines): +2

## Symbol Weights

- function declaration/definition changed: +4
- struct/union/enum/typedef changed: +4
- callback/function pointer pattern changed: +4
- global data changed: +2
- local function context changed: +4
- memory allocation/lifetime change: +5
- container ownership change: +5
- pointer alias / escaped lifetime change: +5
- callback opaque/context pointer alias change: +5
- semantic behavior keyword changed: +2
- symbol in public/shared path: +3
- symbol in high-risk path: +3
- symbol in memory-sensitive path: +3
- legacy file reference: +4
- referenced by >= 10 files: +3
- spans >= 3 subsystems: +3

Risk levels:

- high: score >= 8
- medium: score 4-7
- low: score 0-3

Scores are triage signals, not proof of defects.

## Local Function Context

If a diff only changes a function-body local variable or field, do not query CodeGraph with local names such as `ret`, `ctx`, `tmp`, or `flag`.

Map the diff line to the enclosing function, preserve the local evidence, and use the enclosing function as the Step 3 CodeGraph expansion subject.

Examples:

```c
ret = flag + 1;
ctx->state = READY;
```

These should expand the enclosing function, not `ret`, `flag`, `ctx`, or `state`.

## Heap/Object Lifetime Evidence

Heap and escaped objects need special evidence because C pointer names often change across functions.

Track:

- `malloc`, `calloc`, `realloc`, `strdup`
- `free`, `destroy`, `cleanup`, `release`
- `ref`, `unref`, `retain`, `get`, `put`
- container insert/remove: `list`, `hash`, `map`, `queue`, `cache`, `tree`
- `obj->field = ptr`, globals/statics, callback registration
- `void *opaque`, `user_data`, `ctx`, `priv`, `cookie`
- `goto error`, `cleanup`, early return, partial initialization

Questions to preserve in report evidence:

- Is allocation/free paired on success and failure paths?
- Does ownership transfer after container insert or callback registration?
- Is an escaped object still alive when callbacks fire?
- Do destroy/copy/clone/error-cleanup paths cover new pointer fields?
- Does `realloc` failure preserve the original pointer?

## Pointer Alias Guidance

Do not rely on variable names for C pointer safety. The same object can appear as `s`, `ctx`, `priv`, `opaque`, `user_data`, a struct field, a global, or a container element.

Track by object identity:

- type / struct identity
- field access
- ownership API pairs
- escape points
- error paths

When explaining this risk, phrase it as lifecycle evidence and suggested validation paths.
