#!/usr/bin/env python3
"""Deterministic C regression impact scanner for weak intranet agents.

Python 3.6 compatible. The script is designed for Linux deployment with
bounded subprocess output and JSON artifacts for Claude Code summarization.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path


PUBLIC_PATH_RE = re.compile(
    r"(^|/)(include|inc|common|public|api|lib|platform|protocol|sdk|adapter)(/|$)",
    re.I,
)
BUILD_FILE_RE = re.compile(r"(^|/)(makefile|cmakelists\.txt|.*\.mk|.*\.cmake)$", re.I)
C_FILE_RE = re.compile(r"\.(c|h)$", re.I)
HEADER_RE = re.compile(r"\.h$", re.I)
IDENT_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
FUNC_DEF_RE = re.compile(
    r"^\s*(?:[A-Za-z_][\w\s\*\(\),]*\s+)+(?P<name>[A-Za-z_]\w*)\s*\([^;{}]*\)\s*(?:\{|$)"
)
DECL_RE = re.compile(
    r"^\s*(?:extern\s+)?(?:[A-Za-z_][\w\s\*\(\),]*\s+)+(?P<name>[A-Za-z_]\w*)\s*\([^{}]*\)\s*;"
)
TYPE_RE = re.compile(r"\b(struct|union|enum|typedef)\b")
CALLBACK_RE = re.compile(r"\b(callback|cb|ops|vtable|handler|hook)\b|(?:\*\s*[A-Za-z_]\w*\s*\()", re.I)
GLOBAL_RE = re.compile(r"^\s*(?:extern\s+)?[A-Za-z_][\w\s\*]*\s+[A-Za-z_]\w*(?:\s*=|\s*;)")
MEMORY_RE = re.compile(
    r"\b(malloc|calloc|realloc|strdup|free|alloc|dealloc|release|destroy|cleanup|refcount|refcnt|retain|"
    r"memcpy|memmove|memset|sizeof|"
    r"list_(add|add_tail|del|del_init|move|move_tail)|hlist_(add|del)|rb_(insert|erase|link)|"
    r"tree_(insert|remove|erase|delete)|hash_(add|del|remove|insert)|queue_(push|pop|remove)|"
    r"enqueue|dequeue|cache_(add|insert|remove|delete)|map_(put|insert|remove|erase))\b",
    re.I,
)
POINTER_ALIAS_RE = re.compile(
    r"(\bvoid\s*\*\s*(opaque|ctx|context|user_data|userdata|priv|private|cookie)\b)"
    r"|(\b(callback|cb|handler|hook|register|unregister)\b.*\b(opaque|ctx|context|user_data|userdata|priv|private|cookie)\b)"
    r"|(->\s*[A-Za-z_]\w*\s*=\s*[A-Za-z_]\w*)"
    r"|(\b[A-Za-z_]\w*\s*=\s*[A-Za-z_]\w*\s*;)"
    r"|(\b(list_(add|add_tail)|hlist_add|hash_(add|insert)|map_(put|insert)|queue_push|enqueue|cache_(add|insert)|rb_(insert|link)|tree_(insert))\b)"
    r"|(\b(callback_register|register_cb)\b)",
    re.I,
)
FIELD_ACCESS_RE = re.compile(r"(->|\.)\s*[A-Za-z_]\w*\b|\boffsetof\s*\(|\bcontainer_of\s*\(|\bsizeof\s*\(", re.I)
SEMANTIC_RE = re.compile(r"\b(return|NULL|nullptr|errno|error|goto|len|length|size|owner)\b", re.I)
CONTROL_KEYWORDS = set(["if", "for", "while", "switch", "return", "sizeof", "case", "else", "do"])
ARCH_RISK_PATTERNS = [
    ("memory_safety", re.compile(r"\b(memcpy|memmove|memset|strcpy|strncpy|strcat|sprintf|snprintf|overflow|underflow|bounds?|index|len|length|size)\b", re.I)),
    ("memory_leak", re.compile(r"\b(malloc|calloc|realloc|strdup|free|release|destroy|cleanup|refcount|refcnt|retain|alloc|dealloc|list_(add|add_tail|del|del_init)|hlist_(add|del)|rb_(insert|erase|link)|tree_(insert|remove|erase|delete)|hash_(add|del|remove|insert)|queue_(push|pop|remove)|enqueue|dequeue|cache_(add|insert|remove|delete)|map_(put|insert|remove|erase))\b", re.I)),
    ("abi_layout", re.compile(r"\b(struct|union|enum|typedef|sizeof|pragma\s+pack|packed|__attribute__|dllexport|visibility|export)\b", re.I)),
    ("error_handling", re.compile(r"\b(return|errno|error|err_|goto|fail|cleanup|NULL|nullptr|invalid|denied)\b", re.I)),
    ("pointer_alias_lifetime", re.compile(r"\b(void\s*\*|opaque|ctx|context|user_data|userdata|priv|private|cookie|container_of|offsetof|list_(add|add_tail)|hlist_add|hash_(add|insert)|map_(put|insert)|queue_push|enqueue|cache_(add|insert)|callback_register|register_cb)\b|->\s*[A-Za-z_]\w*\s*=", re.I)),
    ("callback_dispatch", re.compile(r"\b(callback|cb|ops|vtable|handler|dispatch|command|cmd_table|register|unregister|hook)\b|(?:\*\s*[A-Za-z_]\w*\s*\()", re.I)),
]
ARCH_CATEGORY_WEIGHTS = {
    "memory_safety": 5,
    "memory_leak": 5,
    "abi_layout": 5,
    "error_handling": 3,
    "pointer_alias_lifetime": 5,
    "callback_dispatch": 4,
}
LATEST_COMMIT_RANGE = "HEAD~1..HEAD"
DEFAULT_ENABLED_RISK_CATEGORIES = [
    "memory_leak",
    "memory_safety",
    "abi_layout",
    "pointer_alias_lifetime",
    "error_handling",
    "callback_dispatch",
]


def detect_risk_categories(evidence, file_path, kind):
    text = "{} {} {}".format(evidence or "", file_path or "", kind or "")
    categories = []
    for name, pattern in ARCH_RISK_PATTERNS:
        if pattern.search(text) and name not in categories:
            categories.append(name)
    if kind == "type" and "abi_layout" not in categories:
        categories.append("abi_layout")
    if kind == "callback-or-function-pointer" and "callback_dispatch" not in categories:
        categories.append("callback_dispatch")
    if kind == "memory-lifetime":
        if "memory_leak" not in categories:
            categories.append("memory_leak")
    if kind == "pointer-alias-lifetime":
        if "pointer_alias_lifetime" not in categories:
            categories.append("pointer_alias_lifetime")
    return categories


def scoped_prefix(scope_path, value):
    raw_value = normalize(str(value)).strip()
    value = raw_value
    scope_path = normalize(scope_path or "").strip().strip("/")
    if not scope_path or not value:
        return value
    trailing = "/" if raw_value.endswith("/") else ""
    value = value.strip("/")
    if value == scope_path or value.startswith(scope_path + "/"):
        return value + trailing
    return scope_path + "/" + value + trailing


def default_scan_config(scope_path=None):
    scope_path = normalize(scope_path or "").strip().strip("/")
    return {
        "scope_path": scope_path,
        "public_interfaces": [scoped_prefix(scope_path, p) for p in ["include/", "inc/", "common/", "public/", "api/", "sdk/include/"]],
        "legacy_paths": [scoped_prefix(scope_path, p) for p in ["legacy/", "old/", "stable/"]],
        "high_risk_paths": [scoped_prefix(scope_path, p) for p in ["platform/", "protocol/", "storage/", "upgrade/", "adapter/", "common/"]],
        "memory_sensitive_paths": [scoped_prefix(scope_path, p) for p in ["memory/", "mem/", "buffer/", "session/", "core/"]],
        "low_risk_paths": [scoped_prefix(scope_path, p) for p in ["test/", "tests/", "doc/", "docs/"]],
        "enabled_risk_categories": list(DEFAULT_ENABLED_RISK_CATEGORIES),
        "subsystems": {},
    }


def parse_simple_yaml_lists(text):
    data = {}
    current_key = None
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if not line.startswith(" ") and line.endswith(":"):
            current_key = line[:-1].strip()
            data.setdefault(current_key, [])
            continue
        if not line.startswith(" ") and ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip().strip("'\"")
            if value:
                data[key] = value
                current_key = key
            else:
                current_key = key
                data.setdefault(current_key, [])
            continue
        stripped = line.strip()
        if current_key and stripped.startswith("- "):
            existing = data.get(current_key, [])
            if not isinstance(existing, list):
                existing = [existing] if existing else []
                data[current_key] = existing
            existing.append(stripped[2:].strip().strip("'\""))
    return data


def load_scan_config(repo, scope_path=None):
    scope_path = normalize(scope_path or "").strip().strip("/")
    config = default_scan_config(scope_path)
    config_root = repo / scope_path if scope_path else repo
    json_path = config_root / ".impact-scan.json"
    yaml_paths = [config_root / ".impact-scan.yml", config_root / ".impact-scan.yaml"]
    loaded = {}
    if json_path.exists():
        loaded = json.loads(json_path.read_text(encoding="utf-8"))
    else:
        for path in yaml_paths:
            if path.exists():
                loaded = parse_simple_yaml_lists(path.read_text(encoding="utf-8"))
                break
    for key in (
        "public_interfaces",
        "legacy_paths",
        "high_risk_paths",
        "memory_sensitive_paths",
        "low_risk_paths",
    ):
        values = loaded.get(key)
        if isinstance(values, list):
            for value in values:
                normalized = scoped_prefix(scope_path, str(value))
                if normalized and normalized not in config[key]:
                    config[key].append(normalized)
    if isinstance(loaded.get("subsystems"), dict):
        config["subsystems"] = loaded["subsystems"]
    return config


def path_matches_prefix(path, prefixes):
    normalized = normalize(path).lower()
    for prefix in prefixes:
        normalized_prefix = normalize(prefix).lower().strip()
        if not normalized_prefix:
            continue
        if normalized.startswith(normalized_prefix.rstrip("/") + "/") or normalized == normalized_prefix.rstrip("/"):
            return True
    return False


def path_in_scope(path, config):
    scope_path = normalize(config.get("scope_path", "")).strip().strip("/")
    if not scope_path:
        return True
    normalized = normalize(path).lower()
    scope = scope_path.lower()
    return normalized == scope or normalized.startswith(scope + "/")


def filter_files_by_scope(files, config):
    return [item for item in files if path_in_scope(item["path"], config)]


def configured_subsystem_for(path, config):
    normalized = normalize(path)
    for name, value in config.get("subsystems", {}).items():
        paths = value.get("paths", []) if isinstance(value, dict) else value
        if isinstance(paths, list) and path_matches_prefix(normalized, paths):
            return name
    return subsystem_for(normalized)


def apply_config_to_file(item, config):
    item["is_public_interface"] = item["is_public_path"] or path_matches_prefix(item["path"], config["public_interfaces"])
    item["is_legacy_path"] = path_matches_prefix(item["path"], config["legacy_paths"])
    item["is_high_risk_path"] = path_matches_prefix(item["path"], config["high_risk_paths"])
    item["is_memory_sensitive_path"] = path_matches_prefix(item["path"], config["memory_sensitive_paths"])
    item["is_low_risk_path"] = path_matches_prefix(item["path"], config["low_risk_paths"])
    item["subsystem"] = configured_subsystem_for(item["path"], config)
    return item


def changed_file(path, status, added=0, deleted=0):
    path = normalize(path)
    return {
        "path": path,
        "status": status,
        "added": added,
        "deleted": deleted,
        "is_c": bool(C_FILE_RE.search(path)),
        "is_header": bool(HEADER_RE.search(path)),
        "is_public_path": bool(PUBLIC_PATH_RE.search(path)),
        "is_build_file": bool(BUILD_FILE_RE.search(path)),
        "is_public_interface": False,
        "is_legacy_path": False,
        "is_high_risk_path": False,
        "is_memory_sensitive_path": False,
        "is_low_risk_path": False,
        "subsystem": subsystem_for(path),
    }


def changed_symbol(name, file_path, kind, evidence):
    return {
        "name": name,
        "file": normalize(file_path),
        "kind": kind,
        "evidence": evidence,
        "risk_categories": detect_risk_categories(evidence, file_path, kind),
    }


def reference_result(symbol, backend, files, config=None):
    if config:
        subsystems = set(configured_subsystem_for(path, config) for path in files)
        legacy_file_count = len([path for path in files if path_matches_prefix(path, config["legacy_paths"])])
    else:
        subsystems = set(subsystem_for(path) for path in files)
        legacy_file_count = 0
    return {
        "symbol": symbol,
        "backend": backend,
        "files": files,
        "file_count": len(files),
        "subsystem_count": len(subsystems),
        "legacy_file_count": legacy_file_count,
    }


def risk_item(subject, kind, score, reasons, evidence_files, categories=None):
    return {
        "subject": subject,
        "kind": kind,
        "score": score,
        "level": level_for(score),
        "reasons": reasons,
        "evidence_files": evidence_files,
        "risk_categories": categories or [],
    }


def codegraph_status(mode):
    exe = find_codegraph()
    return {
        "mode": mode,
        "available": bool(exe),
        "executable": exe,
        "index_present": False,
        "init_attempted": False,
        "init_succeeded": False,
        "used_for_symbols": 0,
        "errors": [],
    }


def validate_commit_range(commit_range):
    normalized = (commit_range or "").strip()
    if normalized == LATEST_COMMIT_RANGE:
        return True, ""
    return False, "only the current branch latest commit is supported; use --range {}".format(LATEST_COMMIT_RANGE)


def enabled_risk_categories(config=None):
    if not config:
        return None
    values = config.get("enabled_risk_categories")
    if not values:
        return None
    return set(values)


def filter_enabled_risk_categories(categories, config=None):
    enabled = enabled_risk_categories(config)
    if enabled is None:
        return categories
    return [category for category in categories if category in enabled]


def apply_focus_to_scan_config(config, subsystem, focus):
    for key in ("legacy_paths", "public_interfaces"):
        values = focus.get(key, [])
        if values:
            for value in values:
                normalized = scoped_prefix(subsystem, str(value))
                if normalized and normalized not in config.setdefault(key, []):
                    config[key].append(normalized)
    return config


FOCUS_CONFIG_NAME = ".impact-scan-focus.yml"
FOCUS_CONFIG_NAME_JSON = ".impact-scan-focus.json"
FOCUS_CONFIG_NAME_YAML_ALT = ".impact-scan-focus.yaml"


def load_focus_config(source, cli_focus_symbols=None, cli_ignore_paths=None):
    """Load user-provided focus config from file and/or CLI flags.

    Supports two file formats:
      Flat YAML (preferred):
        focus_symbols:
          - api_open
        subsystem: subsys/net

      JSON:
        {"focus": {"focus_symbols": ["api_open"], ...}}

    CLI flags take precedence over file config.
    """
    source = Path(source)
    focus = {
        "focus_symbols": [],
        "ignore_paths": [],
        "legacy_paths": [],
        "public_interfaces": [],
        "notes": [],
        "scope_override": None,
    }

    if source.is_file():
        candidates = [source]
    else:
        candidates = [source / FOCUS_CONFIG_NAME_JSON, source / FOCUS_CONFIG_NAME, source / FOCUS_CONFIG_NAME_YAML_ALT]

    for candidate in candidates:
        if candidate.exists():
            text = candidate.read_text(encoding="utf-8")
            if candidate.suffix == ".json":
                data = json.loads(text)
            else:
                data = parse_simple_yaml_lists(text)
            # Support both nested {"focus": {...}} and flat format
            raw = data.get("focus", None)
            if isinstance(raw, dict):
                pass  # use raw directly
            elif isinstance(raw, list):
                # Nested format where focus: is a list — use data as flat
                raw = data
            else:
                raw = data
            if isinstance(raw, dict):
                focus["focus_symbols"] = _list_value(raw, "focus_symbols")
                focus["ignore_paths"] = _list_value(raw, "ignore_paths")
                focus["legacy_paths"] = _list_value(raw, "legacy_paths")
                focus["public_interfaces"] = _list_value(raw, "public_interfaces")
                focus["notes"] = _list_value(raw, "notes")
                scope = raw.get("subsystem")
                if scope:
                    focus["scope_override"] = scope
            break

    if cli_focus_symbols:
        focus["focus_symbols"] = [s.strip() for s in cli_focus_symbols.split(",") if s.strip()]
    if cli_ignore_paths:
        focus["ignore_paths"] = [p.strip() for p in cli_ignore_paths.split(",") if p.strip()]

    return focus


def _list_value(data, key):
    """Extract a list value from a dict, handling nested dict with list children."""
    val = data.get(key, [])
    if isinstance(val, list):
        return val
    return []


def path_matches_any_prefix(path, prefixes):
    """Check if path matches any of the given prefixes."""
    if not prefixes:
        return False
    return path_matches_prefix(path, prefixes)


def select_symbols_for_expansion(symbols, risks, focus):
    """Select which symbols should have references expanded.

    Expands: focus_symbols, high-risk symbols, public-interface symbols, memory-lifetime symbols.
    Does NOT expand all changed symbols by default.
    """
    focus_names = set(focus.get("focus_symbols", []))
    selected = set()
    reasons = {}

    for sym in symbols:
        name = sym["name"]
        if name in focus_names:
            selected.add(name)
            reasons[name] = "user-specified focus symbol"
            continue
        categories = sym.get("risk_categories", [])
        if "memory_leak" in categories or "memory_safety" in categories:
            selected.add(name)
            reasons[name] = "memory-lifetime symbol"
            continue
        if sym.get("kind") == "local-function-context":
            selected.add(name)
            reasons[name] = "local change in enclosing function"
            continue
        if sym.get("evidence_role"):
            selected.add(name)
            reasons[name] = sym["evidence_role"]
            continue

    for risk in risks:
        name = risk["subject"]
        if risk["kind"] == "file":
            continue
        if risk["level"] == "high":
            selected.add(name)
            reasons.setdefault(name, "high-risk symbol (score >= 8)")
        elif any("public" in r.lower() or "header" in r.lower() for r in risk.get("reasons", [])):
            selected.add(name)
            reasons.setdefault(name, "public interface symbol")

    return selected, reasons


def should_ignore_path(path, focus):
    """Check if a path should be ignored based on user focus config."""
    return path_matches_any_prefix(path, focus.get("ignore_paths", []))


def filter_ignored_paths(items, focus, key="path"):
    """Remove items whose paths match ignore_paths."""
    ignore = focus.get("ignore_paths", [])
    if not ignore:
        return items
    return [item for item in items if not path_matches_any_prefix(item.get(key, ""), ignore)]


def filter_symbols_by_focus(symbols, focus):
    """Remove changed symbols from ignored paths."""
    if not focus.get("ignore_paths"):
        return symbols
    return [symbol for symbol in symbols if not should_ignore_path(symbol.get("file", ""), focus)]


def filter_files_by_focus(files, focus):
    """Remove changed files from ignored paths."""
    return filter_ignored_paths(files, focus, "path")


def filter_risks_by_focus(risks, focus):
    """Remove or trim risk items whose evidence only comes from ignored paths."""
    if not focus.get("ignore_paths"):
        return risks
    filtered = []
    for risk in risks:
        subject = risk.get("subject", "")
        if should_ignore_path(subject, focus):
            continue
        evidence = risk.get("evidence_files", [])
        trimmed = [path for path in evidence if not should_ignore_path(path, focus)]
        if evidence and not trimmed:
            continue
        item = dict(risk)
        item["evidence_files"] = trimmed
        filtered.append(item)
    return filtered


def filter_references_by_focus(refs, focus, config=None):
    """Trim reference files that match ignore_paths and recalculate counts."""
    if not focus.get("ignore_paths"):
        return refs
    filtered = []
    for ref in refs:
        files = [path for path in ref.get("files", []) if not should_ignore_path(path, focus)]
        item = dict(ref)
        item["files"] = files
        item["file_count"] = len(files)
        if config:
            item["subsystem_count"] = len(set(configured_subsystem_for(path, config) for path in files))
            item["legacy_file_count"] = len([path for path in files if path_matches_prefix(path, config["legacy_paths"])])
        else:
            item["subsystem_count"] = len(set(subsystem_for(path) for path in files))
            item["legacy_file_count"] = 0
        filtered.append(item)
    return filtered


def decode_process_output(data):
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            pass
    return data.decode("utf-8", errors="replace")


def run(args, cwd, check=True):
    try:
        completed = subprocess.run(
            args,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except FileNotFoundError:
        raise RuntimeError("missing command: {}".format(args[0]))
    result = subprocess.CompletedProcess(
        completed.args,
        completed.returncode,
        decode_process_output(completed.stdout),
        decode_process_output(completed.stderr),
    )
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, result.args, output=result.stdout, stderr=result.stderr)
    return result


def git(args, cwd):
    result = run(["git"] + args, cwd)
    return result.stdout


def ensure_git_repo(cwd):
    root = git(["rev-parse", "--show-toplevel"], cwd).strip()
    return Path(root)


def normalize(path):
    return path.replace("\\", "/")


def subsystem_for(path, depth=2):
    parts = [p for p in normalize(path).split("/") if p]
    if not parts:
        return "."
    return "/".join(parts[:depth])


def pathspec_args_for_scope(config):
    scope_path = normalize(config.get("scope_path", "")).strip().strip("/") if config else ""
    return ["--", scope_path] if scope_path else []


def resolve_subsystem_from_changed_files(repo, commit_range, requested_subsystem):
    requested = normalize(requested_subsystem or "").strip().strip("/")
    result = {
        "requested_subsystem": requested,
        "resolved_subsystem": requested,
        "subsystem_auto_resolved": False,
        "subsystem_resolution_candidates": [],
    }
    raw_files = parse_changed_files(repo, commit_range, None)
    if not requested:
        inferred = []
        seen = set()
        for item in raw_files:
            candidate = subsystem_for(item["path"])
            if candidate and candidate != "." and candidate not in seen:
                inferred.append(candidate)
                seen.add(candidate)
        result["subsystem_resolution_candidates"] = inferred
        if len(inferred) == 1:
            result["resolved_subsystem"] = inferred[0]
            result["subsystem_auto_resolved"] = True
        return result
    if (repo / requested).exists():
        return result

    candidates = []
    seen = set()
    requested_parts = [part for part in requested.split("/") if part]
    requested_leaf = requested_parts[-1] if requested_parts else requested
    for item in raw_files:
        parts = [part for part in item["path"].split("/") if part]
        for index, part in enumerate(parts[:-1]):
            if part != requested_leaf:
                continue
            candidate = "/".join(parts[: index + 1])
            if requested_parts and len(requested_parts) > 1:
                tail = parts[index - len(requested_parts) + 1 : index + 1]
                if tail != requested_parts:
                    continue
            if candidate not in seen:
                candidates.append(candidate)
                seen.add(candidate)

    result["subsystem_resolution_candidates"] = candidates
    if len(candidates) == 1:
        result["resolved_subsystem"] = candidates[0]
        result["subsystem_auto_resolved"] = candidates[0] != requested
    return result


def parse_changed_files(repo, commit_range, config=None):
    output = git(["diff", "--numstat", "--name-status", commit_range] + pathspec_args_for_scope(config), repo)
    files = {}
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 3 and parts[0].isdigit():
            added = int(parts[0])
            deleted = int(parts[1]) if parts[1].isdigit() else 0
            path = normalize(parts[2])
            item = files.setdefault(path, changed_file(path, "M"))
            item["added"] = added
            item["deleted"] = deleted
        elif len(parts) >= 2:
            status = parts[0]
            path = normalize(parts[-1])
            files.setdefault(path, changed_file(path, status))
    if config:
        for item in files.values():
            apply_config_to_file(item, config)
        return sorted(filter_files_by_scope(files.values(), config), key=lambda x: x["path"])
    return sorted(files.values(), key=lambda x: x["path"])


def diff_lines(repo, commit_range, config=None):
    scope_path = normalize(config.get("scope_path", "")).strip().strip("/") if config else ""
    pathspec = ["--", scope_path] if scope_path else ["--", "*.c", "*.h"]
    output = git(["diff", "--unified=0", commit_range] + pathspec, repo)
    current_file = ""
    new_line = None
    for line in output.splitlines():
        if line.startswith("+++ b/"):
            current_file = normalize(line[6:])
            continue
        if line.startswith("@@"):
            match = re.search(r"\+(\d+)(?:,(\d+))?", line)
            new_line = int(match.group(1)) if match else None
            continue
        if line.startswith("+") and not line.startswith("+++"):
            yield current_file, line[1:], new_line
            if new_line is not None:
                new_line += 1
        elif line.startswith("-") and not line.startswith("---"):
            yield current_file, line[1:], new_line


def enclosing_function_for_line(repo, file_path, line_number):
    if not file_path or not line_number:
        return ""
    path = repo / file_path
    if not path.exists():
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except TypeError:
        lines = path.read_text(encoding="utf-8").splitlines()
    current = ""
    for raw_line in lines[:line_number]:
        match = FUNC_DEF_RE.match(raw_line.strip())
        if match:
            name = match.group("name")
            if name not in CONTROL_KEYWORDS:
                current = name
    return current


def annotate_local_context(symbol, role):
    item = dict(symbol)
    item["evidence_role"] = role
    return item


def has_pointer_lifecycle_evidence(line):
    return bool(
        re.search(
            r"\b(void\s*\*|opaque|ctx|context|user_data|userdata|priv|private|cookie|callback|cb|handler|hook|register|unregister)\b"
            r"|->|\.\s*[A-Za-z_]\w*\b"
            r"|\b(list_|hlist_|hash_|map_|queue_|enqueue|dequeue|cache_|rb_|tree_)\w*\b"
            r"|\b(container_of|offsetof)\s*\(",
            line,
            re.I,
        )
    )


def extract_symbols(repo, commit_range, max_symbols, config=None):
    symbols = {}
    for file_path, line, line_number in diff_lines(repo, commit_range, config):
        if not file_path:
            continue
        if config and (not C_FILE_RE.search(file_path) or not path_in_scope(file_path, config)):
            continue
        stripped = line.strip()
        if not stripped:
            continue

        kind = ""
        name = ""
        evidence_role = ""
        enclosing = enclosing_function_for_line(repo, file_path, line_number)
        if MEMORY_RE.search(stripped):
            kind = "memory-lifetime"
            name = enclosing or (IDENT_RE.findall(stripped)[0] if IDENT_RE.findall(stripped) else "memory_change")
            if enclosing:
                evidence_role = "heap/object lifetime evidence in enclosing function"
        elif has_pointer_lifecycle_evidence(stripped) and (
            POINTER_ALIAS_RE.search(stripped)
            or FIELD_ACCESS_RE.search(stripped)
            and re.search(r"\b(void|struct|union|typedef|memcpy|memmove|memset)\b|->\s*[A-Za-z_]\w*\s*=", stripped, re.I)
        ):
            kind = "pointer-alias-lifetime"
            if enclosing:
                name = enclosing
                evidence_role = "pointer/object escape evidence in enclosing function"
            else:
                ids = IDENT_RE.findall(stripped)
                preferred = [token for token in ids if token.lower() not in ("void", "struct", "union", "const", "volatile", "static", "return", "sizeof", "offsetof", "container_of")]
                name = preferred[0] if preferred else "pointer_alias_change"
        elif TYPE_RE.search(stripped) and not enclosing:
            kind = "type"
            ids = IDENT_RE.findall(stripped)
            for token in ids:
                if token not in ("typedef", "struct", "union", "enum", "const", "volatile"):
                    name = token
                    break
        elif TYPE_RE.search(stripped) and enclosing:
            kind = "local-function-context"
            name = enclosing
            evidence_role = "local variable evidence in enclosing function"
        else:
            match = FUNC_DEF_RE.match(stripped) or DECL_RE.match(stripped)
            if match:
                kind = "function"
                name = match.group("name")
            elif CALLBACK_RE.search(stripped):
                kind = "callback-or-function-pointer"
                ids = IDENT_RE.findall(stripped)
                if ids:
                    name = ids[-1]
            elif GLOBAL_RE.match(stripped):
                if enclosing:
                    kind = "local-function-context"
                    name = enclosing
                    evidence_role = "local variable evidence in enclosing function"
                else:
                    kind = "global"
                    ids = IDENT_RE.findall(stripped)
                    if ids:
                        name = ids[-1]
            elif enclosing and IDENT_RE.search(stripped):
                kind = "local-function-context"
                name = enclosing
                evidence_role = "local variable evidence in enclosing function"

        if name and kind:
            key = (name, file_path, kind)
            symbol = changed_symbol(name, file_path, kind, stripped[:240])
            if evidence_role:
                symbol = annotate_local_context(symbol, evidence_role)
            if key in symbols:
                existing = symbols[key]
                if stripped[:240] not in existing.get("evidence", ""):
                    existing["evidence"] = "{}; {}".format(existing.get("evidence", ""), stripped[:240]).strip("; ")
                for category in symbol.get("risk_categories", []):
                    if category not in existing["risk_categories"]:
                        existing["risk_categories"].append(category)
                if evidence_role and evidence_role not in existing.get("evidence_role", ""):
                    existing["evidence_role"] = "; ".join(
                        [value for value in [existing.get("evidence_role", ""), evidence_role] if value]
                    )
            else:
                symbols[key] = symbol
            if len(symbols) >= max_symbols:
                break
    return list(symbols.values())


def find_codegraph():
    return shutil.which("codegraph")


def has_codegraph_index(repo):
    return (repo / ".codegraph").exists()


def prepare_codegraph(repo, mode, init_codegraph):
    status = codegraph_status(mode)
    status["index_present"] = has_codegraph_index(repo)
    if mode == "off":
        return status
    if not status["executable"]:
        status["errors"].append("codegraph executable not found")
        return status
    if status["index_present"]:
        return status
    if not init_codegraph:
        status["errors"].append(
            "CodeGraph index directory .codegraph was not found; rerun with --init-codegraph if indexing is approved"
        )
        return status

    status["init_attempted"] = True
    init_commands = [
        [status["executable"], "init"],
        [status["executable"], "index"],
    ]
    any_success = False
    for command in init_commands:
        result = run(command, repo, check=False)
        if result.returncode == 0:
            any_success = True
        elif result.stderr.strip():
            status["errors"].append("{} failed: {}".format(" ".join(command), result.stderr.strip()[:500]))
    status["index_present"] = has_codegraph_index(repo)
    status["init_succeeded"] = any_success or status["index_present"]
    if not status["index_present"]:
        status["errors"].append("CodeGraph init/index did not create a .codegraph directory")
    return status


def run_codegraph_impact(repo, symbol, limit, status):
    if status["mode"] == "off" or not status["executable"]:
        return []
    commands = [
        [status["executable"], "impact", symbol],
        [status["executable"], "impact", "--symbol", symbol],
    ]
    for command in commands:
        result = run(command, repo, check=False)
        if result.returncode == 0 and result.stdout.strip():
            return extract_paths_from_text(result.stdout, limit)
    return []


def extract_paths_from_text(text, limit):
    paths = []
    seen = set()
    for match in re.finditer(r"[\w./\\:-]+\.(?:c|h)\b", text, re.I):
        path = normalize(match.group(0))
        if path not in seen:
            paths.append(path)
            seen.add(path)
        if len(paths) >= limit:
            break
    return paths


def gather_references(repo, symbols, limit, codegraph, config=None):
    results = []
    for symbol in symbols:
        backend = "none"
        files = run_codegraph_impact(repo, symbol["name"], limit, codegraph)
        if files:
            backend = "codegraph"
            codegraph["used_for_symbols"] += 1
        results.append(reference_result(symbol["name"], backend, files, config))
    return results


def score_file(item):
    score = 0
    reasons = []
    if item["is_header"]:
        score += 4
        reasons.append("header file changed")
    if item.get("is_public_interface") or item["is_public_path"]:
        score += 3
        reasons.append("public/shared interface path changed")
    if item.get("is_high_risk_path"):
        score += 3
        reasons.append("architecturally high-risk path changed")
    if item.get("is_legacy_path"):
        score += 3
        reasons.append("legacy path changed")
    if item.get("is_memory_sensitive_path"):
        score += 2
        reasons.append("memory-sensitive path changed")
    if item["added"] + item["deleted"] >= 80:
        score += 2
        reasons.append("large change size")
    return score, reasons


def score_symbol(symbol, refs, config=None):
    score = 0
    reasons = []
    if symbol["kind"] == "function":
        score += 4
        reasons.append("function declaration or definition changed")
    elif symbol["kind"] == "type":
        score += 4
        reasons.append("struct/union/enum/typedef changed")
    elif symbol["kind"] == "callback-or-function-pointer":
        score += 4
        reasons.append("callback/function pointer pattern changed")
    elif symbol["kind"] == "global":
        score += 2
        reasons.append("global data changed")
    elif symbol["kind"] == "local-function-context":
        score += 4
        reasons.append("local change in enclosing function")
    elif symbol["kind"] == "memory-lifetime":
        score += 5
        if re.search(r"\b(list_|hlist_|rb_|tree_|hash_|queue_|enqueue|dequeue|cache_|map_)", symbol.get("evidence", ""), re.I):
            reasons.append("container ownership/lifetime related change")
        else:
            reasons.append("memory allocation/lifetime related change")
    elif symbol["kind"] == "pointer-alias-lifetime":
        score += 5
        evidence = symbol.get("evidence", "")
        if re.search(r"\b(opaque|ctx|context|user_data|userdata|priv|private|cookie|callback|register_cb|callback_register)\b", evidence, re.I):
            reasons.append("callback opaque/context pointer alias lifetime change")
        elif re.search(r"\b(list_|hlist_|hash_|map_|queue_|enqueue|cache_|rb_|tree_)", evidence, re.I):
            reasons.append("container pointer escape ownership change")
        else:
            reasons.append("pointer alias/field ownership lifetime change")
    for category in filter_enabled_risk_categories(symbol.get("risk_categories", []), config):
        weight = ARCH_CATEGORY_WEIGHTS.get(category, 0)
        if weight:
            score += weight
            reasons.append("architecture risk {} detected".format(category))
    if SEMANTIC_RE.search(symbol.get("evidence", "")):
        score += 2
        reasons.append("semantic behavior keyword changed")
    if config and path_matches_prefix(symbol["file"], config["memory_sensitive_paths"]):
        score += 3
        reasons.append("memory-sensitive path changed")
    if PUBLIC_PATH_RE.search(symbol["file"]) or (config and path_matches_prefix(symbol["file"], config["public_interfaces"])):
        score += 3
        reasons.append("symbol is in public/shared path")
    if config and path_matches_prefix(symbol["file"], config["high_risk_paths"]):
        score += 3
        reasons.append("symbol is in architecturally high-risk path")
    if refs:
        legacy_file_count = refs.get("legacy_file_count", 0)
        if config and not legacy_file_count:
            legacy_file_count = len([path for path in refs.get("files", []) if path_matches_prefix(path, config["legacy_paths"])])
        if legacy_file_count:
            score += 4
            reasons.append("referenced by {} legacy files".format(legacy_file_count))
        if refs["file_count"] >= 10:
            score += 3
            reasons.append("referenced by {} files".format(refs["file_count"]))
        if refs["subsystem_count"] >= 3:
            score += 3
            reasons.append("spans {} subsystems".format(refs["subsystem_count"]))
    return score, reasons


def level_for(score):
    if score >= 8:
        return "high"
    if score >= 4:
        return "medium"
    return "low"


def build_risk_items(files, symbols, refs, config=None):
    risk_items = []
    refs_by_symbol = {r["symbol"]: r for r in refs}
    for item in files:
        score, reasons = score_file(item)
        if score:
            risk_items.append(risk_item(item["path"], "file", score, reasons, [item["path"]]))
    for symbol in symbols:
        ref = refs_by_symbol.get(symbol["name"])
        score, reasons = score_symbol(symbol, ref, config)
        evidence = [symbol["file"]]
        if ref:
            evidence.extend(ref["files"][:10])
        risk_items.append(
            risk_item(
                symbol["name"],
                symbol["kind"],
                score,
                reasons,
                list(dict.fromkeys(evidence)),
                filter_enabled_risk_categories(symbol.get("risk_categories", []), config),
            )
        )
    return sorted(risk_items, key=lambda x: (-x["score"], x["subject"]))


def subsystem_impact(files, refs, config=None):
    counter = Counter()
    evidence = defaultdict(set)
    for item in files:
        sub = item.get("subsystem") or (configured_subsystem_for(item["path"], config) if config else subsystem_for(item["path"]))
        counter[sub] += 1
        evidence[sub].add(item["path"])
    for ref in refs:
        for path in ref["files"]:
            sub = configured_subsystem_for(path, config) if config else subsystem_for(path)
            counter[sub] += 1
            evidence[sub].add(path)
    return {
        "subsystems": [
            {"name": name, "count": count, "evidence_files": sorted(evidence[name])[:20]}
            for name, count in counter.most_common()
        ]
    }


def build_impact_paths(refs, config):
    paths = []
    for ref in refs:
        for file_path in ref.get("files", [])[:50]:
            paths.append(
                {
                    "symbol": ref["symbol"],
                    "backend": ref["backend"],
                    "target_file": file_path,
                    "subsystem": configured_subsystem_for(file_path, config),
                    "is_legacy": path_matches_prefix(file_path, config["legacy_paths"]),
                }
            )
    return paths


def unique_limited(values, limit=20):
    result = []
    seen = set()
    for value in values:
        if value and value not in seen:
            result.append(value)
            seen.add(value)
        if len(result) >= limit:
            break
    return result


def checks_for_categories(categories, legacy_hit):
    checks = []
    if legacy_hit:
        checks.append("运行该 subsystem 的 legacy tests，重点验证老功能路径和兼容行为。")
    if "abi_layout" in categories:
        checks.append("Review ABI/layout compatibility，检查 public structs、enums、typedefs 和 exported headers。")
    if "memory_safety" in categories or "memory_leak" in categories:
        checks.append("执行 memory-lifetime 检查，覆盖 allocation/free、refcount、cleanup 和 error paths。")
    if "pointer_alias_lifetime" in categories:
        checks.append("执行 pointer alias/lifetime 检查：按对象类型、字段访问、ownership API 和逃逸点追踪，不依赖变量名。")
    if "callback_dispatch" in categories:
        checks.append("Review callback、ops table、handler registration 和 dispatch table behavior。")
    if not checks:
        checks.append("针对该 subsystem 的 changed files 和 referenced files 运行 focused regression tests。")
    return checks


def build_subsystem_analysis(files, refs, risks, impact_paths, config):
    by_name = {}

    def entry_for(name):
        return by_name.setdefault(
            name,
            {
                "name": name,
                "changed_files": [],
                "referenced_files": [],
                "symbols": [],
                "risk_categories": [],
                "max_score": 0,
                "legacy_hit": False,
                "why_impacted": [],
                "suggested_checks": [],
            },
        )

    for item in files:
        name = item.get("subsystem") or configured_subsystem_for(item["path"], config)
        entry = entry_for(name)
        entry["changed_files"].append(item["path"])
        entry["why_impacted"].append("本次提交直接修改了该 subsystem 内文件 (direct changed file)")
        if item.get("is_public_interface"):
            entry["why_impacted"].append("修改了 public interface file，可能影响老功能的 include/API contract")
        if item.get("is_high_risk_path"):
            entry["why_impacted"].append("修改了 high-risk architecture path，需要关注跨模块行为")
        if item.get("is_memory_sensitive_path"):
            entry["why_impacted"].append("修改了 memory-sensitive path，需要关注 ownership/lifetime 和 leak risk")
        if item.get("is_legacy_path"):
            entry["legacy_hit"] = True
            entry["why_impacted"].append("直接修改 legacy path，老功能行为可能被改变")

    for ref in refs:
        for path in ref.get("files", []):
            name = configured_subsystem_for(path, config)
            entry = entry_for(name)
            entry["referenced_files"].append(path)
            entry["symbols"].append(ref["symbol"])
            entry["why_impacted"].append("changed symbol 被该 subsystem 文件引用，存在 reference impact")
            if path_matches_prefix(path, config["legacy_paths"]):
                entry["legacy_hit"] = True
                entry["why_impacted"].append("changed symbol referenced by legacy path，需重点验证老功能路径")

    for path in impact_paths:
        entry = entry_for(path["subsystem"])
        entry["symbols"].append(path["symbol"])
        entry["referenced_files"].append(path["target_file"])
        entry["why_impacted"].append("CodeGraph impact path reaches this subsystem")
        if path.get("is_legacy"):
            entry["legacy_hit"] = True
            entry["why_impacted"].append("impact path reaches legacy path，存在回归风险放大点")

    for risk in risks:
        for file_path in risk.get("evidence_files", []):
            name = configured_subsystem_for(file_path, config)
            entry = entry_for(name)
            entry["max_score"] = max(entry["max_score"], risk["score"])
            entry["risk_categories"].extend(risk.get("risk_categories", []))
            entry["why_impacted"].extend(risk.get("reasons", [])[:5])
            if risk["kind"] != "file":
                entry["symbols"].append(risk["subject"])

    for entry in by_name.values():
        entry["changed_files"] = unique_limited(entry["changed_files"], 10)
        entry["referenced_files"] = unique_limited(entry["referenced_files"], 10)
        entry["symbols"] = unique_limited(entry["symbols"], 10)
        entry["risk_categories"] = unique_limited(entry["risk_categories"], 10)
        entry["why_impacted"] = unique_limited(entry["why_impacted"], 10)
        entry["suggested_checks"] = checks_for_categories(entry["risk_categories"], entry["legacy_hit"])

    return sorted(by_name.values(), key=lambda item: (-item["max_score"], not item["legacy_hit"], item["name"]))


def build_architecture_risk_summary(risks):
    summary = {}
    for item in risks:
        for category in item.get("risk_categories", []):
            entry = summary.setdefault(category, {"count": 0, "max_score": 0, "subjects": []})
            entry["count"] += 1
            entry["max_score"] = max(entry["max_score"], item["score"])
            if len(entry["subjects"]) < 20:
                entry["subjects"].append(item["subject"])
    return [
        {"category": category, "count": data["count"], "max_score": data["max_score"], "subjects": data["subjects"]}
        for category, data in sorted(summary.items(), key=lambda item: (-item[1]["max_score"], item[0]))
    ]


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def write_markdown_report(path, text):
    path.write_text(text, encoding="utf-8")


def reset_output_dir(repo, out):
    repo_root = repo.resolve()
    out_path = out.resolve()
    if out_path == repo_root or repo_root not in out_path.parents:
        raise RuntimeError("refuse to clear unsafe output directory: {}".format(out))
    if out.exists():
        if out.is_dir():
            shutil.rmtree(str(out))
        else:
            out.unlink()
    out.mkdir(parents=True, exist_ok=True)


def markdown_report(
    commit_range,
    codegraph,
    files,
    symbols,
    refs,
    risks,
    subsystems,
    config,
    impact_paths,
    arch_summary,
    subsystem_analysis,
):
    top_level = risks[0]["level"] if risks else "low"
    max_score = risks[0]["score"] if risks else 0
    backends = set(r["backend"] for r in refs if r["backend"] != "none")
    confidence = "high" if "codegraph" in backends else "low"
    lines = [
        "# C 回归影响扫描报告",
        "",
        "## 概要",
        "- Scan range: `{}`".format(commit_range),
        "- Overall risk: **{}**".format(top_level),
        "- Max score: {}".format(max_score),
        "- Confidence: **{}**".format(confidence),
        "- CodeGraph 模式: `{}`".format(codegraph["mode"]),
        "- CodeGraph 可用: {}".format("是" if codegraph["available"] else "否"),
        "- CodeGraph 命中的 symbol 数: {}".format(codegraph["used_for_symbols"]),
        "- changed files: {}".format(len(files)),
        "- changed symbols: {}".format(len(symbols)),
        "- public interface paths: {}".format(", ".join(config["public_interfaces"][:8])),
        "- legacy paths: {}".format(", ".join(config["legacy_paths"][:8])),
        "",
        "## 分析分层",
        "- CodeGraph 层：用于查找 function/symbol reference、callers/callees、include/import 关系和 subsystem 影响面；局部变量改动会先归属到 enclosing function，再用该函数做 CodeGraph 扩展。",
        "- Heuristic 层：根据函数、路径、diff 内容、risk category、对象类型、字段访问和逃逸点识别风险信号；这些结论是 risk triage，不是完整 data-flow proof。",
        "- 生命周期证据层：记录 heap allocation、container insert/remove、callback opaque、struct field escape、error cleanup path 等对象生命周期证据，辅助定位泄漏、UAF、double free 和 ownership 转移风险。",
        "",
        "## 高/中风险项",
        "",
        "| Subject | Kind | Score | Level | Reasons |",
        "|---|---|---:|---|---|",
    ]
    for item in risks[:30]:
        if item["level"] == "low":
            continue
        reasons = "; ".join(item["reasons"])
        lines.append(
            "| `{}` | {} | {} | {} | {} |".format(
                item["subject"], item["kind"], item["score"], item["level"], reasons
            )
        )
    if all(item["level"] == "low" for item in risks):
        lines.append("| 未发现 | - | 0 | low | 未命中 deterministic high-risk rule |")

    lines.extend(["", "## 架构风险类别", ""])
    if arch_summary:
        lines.extend(["| Category | Count | Max Score | Example Subjects |", "|---|---:|---:|---|"])
        for item in arch_summary:
            lines.append(
                "| `{}` | {} | {} | {} |".format(
                    item["category"], item["count"], item["max_score"], ", ".join("`{}`".format(s) for s in item["subjects"][:5])
                )
            )
    else:
        lines.append("- 未检测到 architecture-specific risk category。")

    lines.extend(["", "## 受影响 subsystem 候选", ""])
    if subsystem_analysis:
        counts = {item["name"]: item["count"] for item in subsystems.get("subsystems", [])}
        for sub in subsystem_analysis[:20]:
            lines.extend(
                [
                    "### `{}`".format(sub["name"]),
                    "- Evidence count: {}".format(counts.get(sub["name"], 0)),
                    "- Max score: {}".format(sub["max_score"]),
                    "- Legacy hit: {}".format("是" if sub["legacy_hit"] else "否"),
                ]
            )
            if sub["why_impacted"]:
                lines.append("- Impact reason:")
                for reason in sub["why_impacted"][:8]:
                    lines.append("  - {}".format(reason))
            if sub["changed_files"]:
                lines.append("- Changed files:")
                for file_path in sub["changed_files"][:8]:
                    lines.append("  - `{}`".format(file_path))
            if sub["referenced_files"]:
                lines.append("- Referenced/impact files:")
                for file_path in sub["referenced_files"][:8]:
                    lines.append("  - `{}`".format(file_path))
            if sub["symbols"]:
                lines.append("- Symbols: {}".format(", ".join("`{}`".format(symbol) for symbol in sub["symbols"][:10])))
            if sub["risk_categories"]:
                lines.append(
                    "- Risk categories: {}".format(
                        ", ".join("`{}`".format(category) for category in sub["risk_categories"][:10])
                    )
                )
            lines.append("- Suggested checks:")
            for check in sub["suggested_checks"][:8]:
                lines.append("  - {}".format(check))
            lines.append("")
    else:
        lines.append("- 未发现受影响 subsystem 候选。")

    lines.extend(["", "## Reference Evidence", ""])
    for ref in refs[:30]:
        if not ref["files"]:
            continue
        sample = ", ".join("`{}`".format(p) for p in ref["files"][:8])
        lines.append(
            "- `{}` via {}: {} files, {} subsystems. {}".format(
                ref["symbol"], ref["backend"], ref["file_count"], ref["subsystem_count"], sample
            )
        )

    lines.extend(["", "## Impact Paths", ""])
    if impact_paths:
        for path in impact_paths[:30]:
            legacy = "legacy path" if path["is_legacy"] else "non-legacy path"
            lines.append(
                "- `{}` -> `{}` -> `{}` ({})".format(
                    path["symbol"], path["target_file"], path["subsystem"], legacy
                )
            )
    else:
        lines.append("- 未发现 symbol-to-file impact path。")

    memory_items = [item for item in risks if item["kind"] == "memory-lifetime"]
    pointer_alias_items = [item for item in risks if item["kind"] == "pointer-alias-lifetime" or "pointer_alias_lifetime" in item.get("risk_categories", [])]
    local_context_items = [item for item in risks if item["kind"] == "local-function-context"]
    lifecycle_items = [item for item in risks if item["kind"] in ("memory-lifetime", "pointer-alias-lifetime")]
    lines.extend(["", "## 生命周期风险证据", ""])
    if lifecycle_items or local_context_items:
        for item in (lifecycle_items + local_context_items)[:30]:
            lines.append("- `{}` ({}, {}): {}".format(item["subject"], item["kind"], item["level"], "; ".join(item["reasons"])))
        lines.extend(
            [
                "- 对堆对象检查 allocation/free、init/destroy、ref/unref 和 error cleanup 是否成对。",
                "- 对进入 list/hash/map/queue/cache 的对象检查插入后异常路径是否摘除或释放。",
                "- 对 `void *opaque/user_data/ctx/priv` 和 callback 注册检查对象是否在触发期间仍然有效。",
                "- 对 struct field/global/container 逃逸点检查 ownership 是否转移，以及销毁路径是否覆盖。",
            ]
        )
    else:
        lines.append("- deterministic rules 未发现局部函数上下文或对象生命周期证据。")

    lines.extend(["", "## 内存泄漏关注点", ""])
    if memory_items:
        for item in memory_items[:20]:
            lines.append("- `{}`: {}".format(item["subject"], "; ".join(item["reasons"])))
        lines.extend(
            [
                "- 验证 allocation success/failure paths。",
                "- 检查 early return 和 goto-error cleanup paths。",
                "- 检查 ownership transfer、refcount balance、container insert/remove balance 以及 legacy repeated-call paths。",
                "- 重点检查 list/tree/hash/queue/map/cache 插入后，异常路径是否摘除或释放对象。",
            ]
        )
    else:
        lines.append("- deterministic rules 未发现 memory-lifetime 类型的 changed symbol。")

    lines.extend(
        [
            "",
            "## 建议回归检查",
            "- Review 上方列出的 high-risk public headers 和 shared modules。",
            "- 针对受影响 subsystem 候选运行 legacy tests。",
            "- 人工检查 struct layout、enum values、callbacks 和 function pointer tables。",
            "- 对 memory-lifetime 变更执行内存泄漏专项检查，尤其关注分配/释放和错误路径。",
            "- 对 pointer alias/lifetime 变更按对象类型、字段访问、ownership API、callback opaque 和逃逸点做生命周期验证。",
            "- 对引用范围较广的 symbol，每个受影响 subsystem 至少验证一条 legacy feature path。",
            "",
            "## 局限性",
            "- 这是 regression risk triage scan，不是 compatibility proof。",
            "- 如果没有 compile database 或 semantic C index，function pointer 和 callback paths 可能不完整。",
            "- 除非 CodeGraph 本地索引捕获了 function pointer 和 callback 关系，否则相关判断属于 heuristic analysis。",
        ]
    )

    lines.extend(["", "## 指针别名与生命周期关注点", ""])
    if pointer_alias_items:
        for item in pointer_alias_items[:20]:
            lines.append("- `{}`: {}".format(item["subject"], "; ".join(item["reasons"])))
        lines.extend(
            [
                "- 不要只按变量名判断安全性；按对象类型、struct 字段、ownership API 和逃逸点追踪。",
                "- 检查 `void *opaque/user_data/ctx/priv` 是否 cast 回变更对象类型，callback 触发时对象是否仍然存活。",
                "- 检查对象是否进入 global、struct field、list/hash/map/queue/cache 或 callback 注册表。",
                "- 检查新增/修改指针字段是否同步更新 destroy/copy/clone/error-cleanup 路径，避免泄漏、UAF、double free 或浅拷贝。",
                "- 对 `memcpy/memset/sizeof/offsetof/container_of` 作用于含指针/refcount/list node 的结构体进行生命周期验证。",
            ]
        )
    else:
        lines.append("- deterministic rules 未发现 pointer-alias-lifetime 类型的 changed symbol。")

    if codegraph["errors"]:
        lines.extend(["", "## CodeGraph 说明"])
        for error in codegraph["errors"][:8]:
            lines.append("- {}".format(error))
    return "\n".join(lines) + "\n"

def _step_discover(repo, out, config, codegraph, args, focus):
    """Step 1: Scope discovery. Output changed files and inferred subsystems."""
    files = parse_changed_files(repo, args.range, config)
    files = filter_files_by_focus(files, focus)
    subsystems_inferred = sorted(set(
        configured_subsystem_for(item["path"], config) for item in files
    ))

    write_json(out / "scan_config.json", config)
    write_json(out / "codegraph_status.json", codegraph)
    write_json(out / "diff_summary.json", files)
    write_json(out / "scope_discovery.json", {
        "range": args.range,
        "requested_subsystem": config.get("requested_subsystem", config.get("scope_path", "")),
        "resolved_subsystem": config.get("scope_path", ""),
        "subsystem_auto_resolved": bool(config.get("subsystem_auto_resolved", False)),
        "subsystem_resolution_candidates": config.get("subsystem_resolution_candidates", []),
        "changed_file_count": len(files),
        "changed_files": [item["path"] for item in files],
        "inferred_subsystems": subsystems_inferred,
        "c_files": [item["path"] for item in files if item["is_c"]],
        "header_files": [item["path"] for item in files if item["is_header"]],
        "public_interface_files": [item["path"] for item in files if item.get("is_public_interface")],
        "build_files": [item["path"] for item in files if item["is_build_file"]],
    })

    print("Scope discovery complete.")
    print("  Changed files: {}".format(len(files)))
    print("  Inferred subsystems: {}".format(", ".join(subsystems_inferred) if subsystems_inferred else "none"))
    print("  C/header files: {}".format(len([f for f in files if f["is_c"]])))
    print("wrote {}".format(out / "scope_discovery.json"))
    return 0


def _step_triage(repo, out, config, codegraph, args, focus):
    """Step 2: Quick risk triage. Score files and symbols WITHOUT reference search."""
    files = parse_changed_files(repo, args.range, config)
    files = filter_files_by_focus(files, focus)
    symbols = extract_symbols(repo, args.range, args.max_symbols, config)
    symbols = filter_symbols_by_focus(symbols, focus)

    # Build risk items without references
    risks = build_risk_items(files, symbols, [], config)

    # Apply focus: mark which items are user-priority
    focus_names = set(focus.get("focus_symbols", []))
    for risk in risks:
        is_focus = risk["subject"] in focus_names
        risk["user_focus"] = is_focus

    # Filter out ignored paths from risk items and evidence
    risks = filter_risks_by_focus(risks, focus)

    high_count = sum(1 for r in risks if r["level"] == "high")
    medium_count = sum(1 for r in risks if r["level"] == "medium")
    arch_summary = build_architecture_risk_summary(risks)

    write_json(out / "scan_config.json", config)
    write_json(out / "codegraph_status.json", codegraph)
    write_json(out / "diff_summary.json", files)
    write_json(out / "changed_symbols.json", symbols)
    write_json(out / "risk_items.json", risks)
    write_json(out / "architecture_risk_summary.json", arch_summary)
    write_json(out / "triage_summary.json", {
        "range": args.range,
        "total_risks": len(risks),
        "high": high_count,
        "medium": medium_count,
        "low": len(risks) - high_count - medium_count,
        "symbol_count": len(symbols),
        "focus_coverage": {
            "focus_symbols_found": [s["name"] for s in symbols if s["name"] in focus_names],
            "focus_symbols_missing": list(focus_names - set(s["name"] for s in symbols)),
        },
        "expansion_candidates": _expansion_candidates(risks, symbols, focus),
    })

    print("Triage complete.")
    print("  Risk items: {} (high={}, medium={}, low={})".format(
        len(risks), high_count, medium_count, len(risks) - high_count - medium_count))
    print("  Symbols extracted: {}".format(len(symbols)))
    if focus_names:
        print("  Focus symbols found: {}".format(
            ", ".join(s["name"] for s in symbols if s["name"] in focus_names) or "none"))
    print("wrote {}".format(out / "triage_summary.json"))
    return 0


def _expansion_candidates(risks, symbols, focus):
    """Build list of symbols that would be expanded in the expand step."""
    selected, reasons = select_symbols_for_expansion(symbols, risks, focus)
    return [
        {"symbol": name, "reason": reasons.get(name, "unknown")}
        for name in sorted(selected)
    ]


def _step_expand(repo, out, config, codegraph, args, focus):
    """Step 3: Focused reference expansion. Only search refs for selected symbols."""
    files = _load_json_artifact(out, "diff_summary.json", [])
    symbols = _load_json_artifact(out, "changed_symbols.json", [])
    risks = _load_json_artifact(out, "risk_items.json", [])
    files = filter_files_by_focus(files, focus)
    symbols = filter_symbols_by_focus(symbols, focus)
    risks = filter_risks_by_focus(risks, focus)

    if not symbols:
        symbols = extract_symbols(repo, args.range, args.max_symbols, config)
        symbols = filter_symbols_by_focus(symbols, focus)
        write_json(out / "changed_symbols.json", symbols)

    selected, reasons = select_symbols_for_expansion(symbols, risks, focus)

    # Gather references only for selected symbols
    refs = []
    for sym in symbols:
        if sym["name"] in selected:
            backend = "none"
            files_found = run_codegraph_impact(repo, sym["name"], args.max_refs, codegraph)
            if files_found:
                backend = "codegraph"
                codegraph["used_for_symbols"] += 1
            refs.append(reference_result(sym["name"], backend, files_found, config))
        else:
            refs.append(reference_result(sym["name"], "skipped", [], config))
    refs = filter_references_by_focus(refs, focus, config)

    # Rebuild risks with reference data
    risks = build_risk_items(files, symbols, refs, config)
    risks = filter_risks_by_focus(risks, focus)
    impact_paths = build_impact_paths(refs, config)

    write_json(out / "codegraph_status.json", codegraph)
    write_json(out / "references.json", refs)
    write_json(out / "impact_paths.json", impact_paths)
    write_json(out / "risk_items.json", risks)
    write_json(out / "expansion_summary.json", {
        "total_symbols": len(symbols),
        "expanded_symbols": len(selected),
        "skipped_symbols": len(symbols) - len(selected),
        "expanded": [
            {"symbol": name, "reason": reasons.get(name, "unknown"),
             "ref_count": next((r["file_count"] for r in refs if r["symbol"] == name), 0)}
            for name in sorted(selected)
        ],
        "codegraph_hits": codegraph["used_for_symbols"],
    })

    print("Expansion complete.")
    print("  Expanded {} / {} symbols".format(len(selected), len(symbols)))
    print("  CodeGraph hits: {}".format(codegraph["used_for_symbols"]))
    print("wrote {}".format(out / "expansion_summary.json"))
    return 0


def _step_report(repo, out, config, codegraph, args, focus):
    """Step 5: Generate final Chinese Markdown report from all collected artifacts."""
    files = _load_json_artifact(out, "diff_summary.json", [])
    symbols = _load_json_artifact(out, "changed_symbols.json", [])
    refs = _load_json_artifact(out, "references.json", [])
    risks = _load_json_artifact(out, "risk_items.json", [])
    files = filter_files_by_focus(files, focus)
    symbols = filter_symbols_by_focus(symbols, focus)
    refs = filter_references_by_focus(refs, focus, config)
    risks = filter_risks_by_focus(risks, focus)

    # If we have no artifacts yet, run a quick one-shot
    if not files and not symbols:
        files = parse_changed_files(repo, args.range, config)
        files = filter_files_by_focus(files, focus)
        symbols = extract_symbols(repo, args.range, args.max_symbols, config)
        symbols = filter_symbols_by_focus(symbols, focus)
        write_json(out / "diff_summary.json", files)
        write_json(out / "changed_symbols.json", symbols)

    if not refs:
        refs = gather_references(repo, symbols, args.max_refs, codegraph, config)
        refs = filter_references_by_focus(refs, focus, config)
        write_json(out / "references.json", refs)

    if not risks:
        risks = build_risk_items(files, symbols, refs, config)
        risks = filter_risks_by_focus(risks, focus)
        write_json(out / "risk_items.json", risks)

    impact_paths = build_impact_paths(refs, config)
    subsystems = subsystem_impact(files, refs, config)
    subsystem_analysis = build_subsystem_analysis(files, refs, risks, impact_paths, config)
    arch_summary = build_architecture_risk_summary(risks)

    report_text = markdown_report_with_focus(
        args.range, codegraph, files, symbols, refs, risks,
        subsystems, config, impact_paths, arch_summary,
        subsystem_analysis, focus,
    )

    write_json(out / "codegraph_status.json", codegraph)
    write_json(out / "impact_paths.json", impact_paths)
    write_json(out / "risk_items.json", risks)
    write_json(out / "architecture_risk_summary.json", arch_summary)
    write_json(out / "subsystem_impact.json", subsystems)
    write_json(out / "subsystem_analysis.json", subsystem_analysis)
    write_markdown_report(out / "risk_report.md", report_text)

    print("Report complete.")
    top_level = risks[0]["level"] if risks else "low"
    print("  Overall risk: {}".format(top_level))
    print("wrote {}".format(out / "risk_report.md"))
    return 0


def _load_json_artifact(out, filename, default):
    path = out / filename
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            return default
    return default


def markdown_report_with_focus(
    commit_range, codegraph, files, symbols, refs, risks,
    subsystems, config, impact_paths, arch_summary,
    subsystem_analysis, focus,
):
    """Generate markdown report with user focus coverage section."""
    base = markdown_report(
        commit_range, codegraph, files, symbols, refs, risks,
        subsystems, config, impact_paths, arch_summary,
        subsystem_analysis,
    )

    focus_names = set(focus.get("focus_symbols", []))
    notes = focus.get("notes", [])

    if not focus_names and not notes:
        return base

    extra = ["", "## 用户重点关注覆盖", ""]

    if focus_names:
        found = [s["name"] for s in symbols if s["name"] in focus_names]
        missing = focus_names - set(found)
        extra.append("- 指定关注 symbol: {}".format(", ".join("`{}`".format(n) for n in sorted(focus_names))))
        if found:
            extra.append("- 已分析: {}".format(", ".join("`{}`".format(n) for n in sorted(found))))
        if missing:
            extra.append("- 未在变更中发现: {}".format(", ".join("`{}`".format(n) for n in sorted(missing))))

    if notes:
        extra.append("- 用户备注:")
        for note in notes:
            extra.append("  - {}".format(note))

    ignore = focus.get("ignore_paths", [])
    if ignore:
        extra.append("- 已排除路径: {}".format(", ".join("`{}`".format(p) for p in ignore)))

    return base + "\n".join(extra) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Scan C change impact for architecture regression risk.")
    parser.add_argument(
        "--range",
        default=LATEST_COMMIT_RANGE,
        help="git commit range to scan. Restricted to the current branch latest commit: {}".format(LATEST_COMMIT_RANGE),
    )
    parser.add_argument("--out", default=".impact-scan", help="output directory")
    parser.add_argument("--subsystem", default="", help="repo-relative subsystem directory to scan, such as subsys/net")
    parser.add_argument("--max-symbols", type=int, default=200, help="maximum changed symbols to analyze")
    parser.add_argument("--max-refs", type=int, default=50, help="maximum reference files per symbol")
    parser.add_argument(
        "--codegraph-mode",
        choices=["required", "off"],
        default="required",
        help="CodeGraph usage mode. Default requires CodeGraph. No reference-search fallback is used.",
    )
    parser.add_argument(
        "--init-codegraph",
        action="store_true",
        help="Attempt non-destructive CodeGraph init/index commands when .codegraph is absent.",
    )
    parser.add_argument(
        "--step",
        choices=["discover", "triage", "expand", "report"],
        default=None,
        help="Run a single guided-workflow step. Omit for one-shot full scan.",
    )
    parser.add_argument(
        "--focus",
        default=None,
        help="Path to focus config file (.impact-scan-focus.yml or .json).",
    )
    parser.add_argument(
        "--focus-symbols",
        default=None,
        help="Comma-separated list of symbols the user cares most about.",
    )
    parser.add_argument(
        "--ignore-paths",
        default=None,
        help="Comma-separated list of path prefixes to exclude from reports.",
    )
    args = parser.parse_args(argv)

    range_ok, range_error = validate_commit_range(args.range)
    if not range_ok:
        print("error: {}".format(range_error), file=sys.stderr)
        return 4

    cwd = Path.cwd()
    try:
        repo = ensure_git_repo(cwd)
    except Exception as exc:
        print("error: not a git repository or git failed: {}".format(exc), file=sys.stderr)
        return 2

    out = repo / args.out
    starts_new_analysis = args.step in (None, "discover")
    if starts_new_analysis:
        try:
            reset_output_dir(repo, out)
        except Exception as exc:
            print("error: failed to clear previous scan artifacts: {}".format(exc), file=sys.stderr)
            return 5
    else:
        out.mkdir(parents=True, exist_ok=True)

    # Resolve focus: --focus file takes precedence, CLI flags override
    focus_source = repo
    if args.focus:
        focus_path = Path(args.focus)
        if not focus_path.is_absolute():
            focus_path = cwd / focus_path
        focus_source = focus_path
    focus = load_focus_config(focus_source, args.focus_symbols, args.ignore_paths)

    # Scope override from focus config
    subsystem = args.subsystem or focus.get("scope_override") or ""
    subsystem_resolution = resolve_subsystem_from_changed_files(repo, args.range, subsystem)
    subsystem = subsystem_resolution["resolved_subsystem"]
    config = load_scan_config(repo, subsystem)
    config.update(subsystem_resolution)
    apply_focus_to_scan_config(config, subsystem, focus)

    codegraph = prepare_codegraph(repo, args.codegraph_mode, args.init_codegraph)
    if args.codegraph_mode == "required" and (not codegraph["available"] or codegraph["errors"]):
        write_json(out / "codegraph_status.json", codegraph)
        if not codegraph["available"]:
            print("error: CodeGraph is required but codegraph executable was not found", file=sys.stderr)
        else:
            print("error: CodeGraph is required but not ready: {}".format("; ".join(codegraph["errors"])), file=sys.stderr)
        return 3

    if args.step == "discover":
        return _step_discover(repo, out, config, codegraph, args, focus)
    elif args.step == "triage":
        return _step_triage(repo, out, config, codegraph, args, focus)
    elif args.step == "expand":
        return _step_expand(repo, out, config, codegraph, args, focus)
    elif args.step == "report":
        return _step_report(repo, out, config, codegraph, args, focus)

    # --- One-shot mode (no --step): backward compatible ---
    files = parse_changed_files(repo, args.range, config)
    files = filter_files_by_focus(files, focus)
    symbols = extract_symbols(repo, args.range, args.max_symbols, config)
    symbols = filter_symbols_by_focus(symbols, focus)
    refs = gather_references(repo, symbols, args.max_refs, codegraph, config)
    refs = filter_references_by_focus(refs, focus, config)
    risks = build_risk_items(files, symbols, refs, config)
    risks = filter_risks_by_focus(risks, focus)
    subsystems = subsystem_impact(files, refs, config)
    impact_paths = build_impact_paths(refs, config)
    subsystem_analysis = build_subsystem_analysis(files, refs, risks, impact_paths, config)
    arch_summary = build_architecture_risk_summary(risks)

    write_json(out / "scan_config.json", config)
    write_json(out / "codegraph_status.json", codegraph)
    write_json(out / "diff_summary.json", files)
    write_json(out / "changed_symbols.json", symbols)
    write_json(out / "references.json", refs)
    write_json(out / "impact_paths.json", impact_paths)
    write_json(out / "risk_items.json", risks)
    write_json(out / "architecture_risk_summary.json", arch_summary)
    write_json(out / "subsystem_impact.json", subsystems)
    write_json(out / "subsystem_analysis.json", subsystem_analysis)
    write_markdown_report(
        out / "risk_report.md",
        markdown_report_with_focus(
            args.range, codegraph, files, symbols, refs, risks,
            subsystems, config, impact_paths, arch_summary,
            subsystem_analysis, focus,
        ),
    )

    print("wrote {}".format(out / "risk_report.md"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
