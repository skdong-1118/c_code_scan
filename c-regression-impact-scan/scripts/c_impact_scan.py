#!/usr/bin/env python3
"""Deterministic C regression impact scanner for weak intranet agents.

Python 3.6 compatible. The script favors portable Windows behavior:
no shell pipelines, no Unix-only tools, bounded output, and JSON artifacts
for Claude Code summarization.
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
MACRO_RE = re.compile(r"^\s*#\s*(define|if|ifdef|ifndef|elif|undef)\b")
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
SEMANTIC_RE = re.compile(r"\b(return|NULL|nullptr|errno|error|goto|timeout|retry|len|length|size|owner|lock|unlock)\b", re.I)
ARCH_RISK_PATTERNS = [
    ("memory_safety", re.compile(r"\b(memcpy|memmove|memset|strcpy|strncpy|strcat|sprintf|snprintf|overflow|underflow|bounds?|index|len|length|size)\b", re.I)),
    ("memory_leak", re.compile(r"\b(malloc|calloc|realloc|strdup|free|release|destroy|cleanup|refcount|refcnt|retain|alloc|dealloc|list_(add|add_tail|del|del_init)|hlist_(add|del)|rb_(insert|erase|link)|tree_(insert|remove|erase|delete)|hash_(add|del|remove|insert)|queue_(push|pop|remove)|enqueue|dequeue|cache_(add|insert|remove|delete)|map_(put|insert|remove|erase))\b", re.I)),
    ("abi_layout", re.compile(r"\b(struct|union|enum|typedef|sizeof|pragma\s+pack|packed|__attribute__|dllexport|visibility|export)\b", re.I)),
    ("concurrency", re.compile(r"\b(mutex|lock|unlock|spin|rwlock|atomic|thread|task|timer|interrupt|semaphore|sem_|wait|signal|pthread)\b", re.I)),
    ("error_handling", re.compile(r"\b(return|errno|error|err_|goto|fail|cleanup|NULL|nullptr|invalid|denied)\b", re.I)),
    ("ownership_lifetime", re.compile(r"\b(owner|ownership|refcount|refcnt|retain|release|destroy|init|deinit|close|open|cleanup|lifetime|list_(add|add_tail|del|del_init)|hlist_(add|del)|rb_(insert|erase|link)|tree_(insert|remove|erase|delete)|hash_(add|del|remove|insert)|queue_(push|pop|remove)|enqueue|dequeue|cache_(add|insert|remove|delete)|map_(put|insert|remove|erase))\b", re.I)),
    ("macro_config", re.compile(r"^\s*#\s*(define|if|ifdef|ifndef|elif|undef)\b|\b(CONFIG_|FEATURE_|ENABLE_|DISABLE_)\w*", re.I)),
    ("protocol_compatibility", re.compile(r"\b(protocol|version|endian|hton|ntoh|tlv|json|field|opcode|message|packet|frame|cmd_|schema)\b", re.I)),
    ("state_machine_timing", re.compile(r"\b(state|event|timer|timeout|retry|transition|start|stop|order|sequence|schedule|delay)\b", re.I)),
    ("callback_dispatch", re.compile(r"\b(callback|cb|ops|vtable|handler|dispatch|command|cmd_table|register|unregister|hook)\b|(?:\*\s*[A-Za-z_]\w*\s*\()", re.I)),
    ("performance_resource", re.compile(r"\b(cpu|memory|socket|fd|file|thread|timer|poll|select|epoll|loop|while|for|cache|alloc|queue)\b", re.I)),
    ("security_boundary", re.compile(r"\b(auth|permission|privilege|token|password|credential|path|command|injection|validate|sanitize|overflow|acl|role)\b", re.I)),
    ("build_deploy", re.compile(r"\b(makefile|cmakelists|target_link_libraries|install|deploy|link|library|ldflags|cflags|symbol|export)\b", re.I)),
]
ARCH_CATEGORY_WEIGHTS = {
    "memory_safety": 5,
    "memory_leak": 5,
    "abi_layout": 5,
    "concurrency": 4,
    "error_handling": 3,
    "ownership_lifetime": 4,
    "macro_config": 3,
    "protocol_compatibility": 4,
    "state_machine_timing": 4,
    "callback_dispatch": 4,
    "performance_resource": 3,
    "security_boundary": 5,
    "build_deploy": 3,
}


def detect_risk_categories(evidence, file_path, kind):
    text = "{} {} {}".format(evidence or "", file_path or "", kind or "")
    categories = []
    for name, pattern in ARCH_RISK_PATTERNS:
        if pattern.search(text) and name not in categories:
            categories.append(name)
    if kind == "type" and "abi_layout" not in categories:
        categories.append("abi_layout")
    if kind == "macro-or-conditional" and "macro_config" not in categories:
        categories.append("macro_config")
    if kind == "callback-or-function-pointer" and "callback_dispatch" not in categories:
        categories.append("callback_dispatch")
    if kind == "memory-lifetime":
        for name in ("memory_leak", "ownership_lifetime"):
            if name not in categories:
                categories.append(name)
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
        stripped = line.strip()
        if current_key and stripped.startswith("- "):
            data.setdefault(current_key, []).append(stripped[2:].strip().strip("'\""))
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
        "fallback_used_for_symbols": 0,
        "errors": [],
    }


def decode_process_output(data):
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    for encoding in ("utf-8-sig", "utf-8", "gbk", "mbcs"):
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
    for line in output.splitlines():
        if line.startswith("+++ b/"):
            current_file = normalize(line[6:])
            continue
        if line.startswith("+") and not line.startswith("+++"):
            yield current_file, line[1:]
        elif line.startswith("-") and not line.startswith("---"):
            yield current_file, line[1:]


def extract_symbols(repo, commit_range, max_symbols, config=None):
    symbols = {}
    for file_path, line in diff_lines(repo, commit_range, config):
        if not file_path:
            continue
        if config and (not C_FILE_RE.search(file_path) or not path_in_scope(file_path, config)):
            continue
        stripped = line.strip()
        if not stripped:
            continue

        kind = ""
        name = ""
        if MEMORY_RE.search(stripped):
            kind = "memory-lifetime"
            ids = IDENT_RE.findall(stripped)
            name = ids[0] if ids else "memory_change"
        elif MACRO_RE.search(stripped):
            kind = "macro-or-conditional"
            match = re.match(r"^\s*#\s*(?:define|undef)\s+([A-Za-z_]\w*)", stripped)
            if match:
                name = match.group(1)
        elif TYPE_RE.search(stripped):
            kind = "type"
            ids = IDENT_RE.findall(stripped)
            for token in ids:
                if token not in ("typedef", "struct", "union", "enum", "const", "volatile"):
                    name = token
                    break
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
                kind = "global"
                ids = IDENT_RE.findall(stripped)
                if ids:
                    name = ids[-1]

        if name and kind:
            key = (name, file_path, kind)
            symbols[key] = changed_symbol(name, file_path, kind, stripped[:240])
            if len(symbols) >= max_symbols:
                break
    return list(symbols.values())


def find_codegraph():
    return shutil.which("codegraph") or shutil.which("codegraph.exe")


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


def rg_references(repo, symbol, limit):
    exe = shutil.which("rg") or shutil.which("rg.exe")
    if not exe:
        return []
    pattern = r"\b{}\b".format(re.escape(symbol))
    result = run(
        [exe, "--files-with-matches", "--glob", "*.c", "--glob", "*.h", pattern, "."],
        repo,
        check=False,
    )
    paths = []
    seen = set()
    for line in result.stdout.splitlines():
        path = normalize(line.strip().lstrip("./"))
        if path and path not in seen:
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
        else:
            files = rg_references(repo, symbol["name"], limit)
            if files:
                backend = "rg"
                codegraph["fallback_used_for_symbols"] += 1
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
    if item["is_build_file"]:
        score += 3
        reasons.append("build or feature switch file changed")
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
    elif symbol["kind"] == "macro-or-conditional":
        score += 3
        reasons.append("macro or conditional compilation changed")
    elif symbol["kind"] == "callback-or-function-pointer":
        score += 4
        reasons.append("callback/function pointer pattern changed")
    elif symbol["kind"] == "global":
        score += 2
        reasons.append("global data changed")
    elif symbol["kind"] == "memory-lifetime":
        score += 5
        if re.search(r"\b(list_|hlist_|rb_|tree_|hash_|queue_|enqueue|dequeue|cache_|map_)", symbol.get("evidence", ""), re.I):
            reasons.append("container ownership/lifetime related change")
        else:
            reasons.append("memory allocation/lifetime related change")
    for category in symbol.get("risk_categories", []):
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
                symbol.get("risk_categories", []),
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
    if "memory_safety" in categories or "memory_leak" in categories or "ownership_lifetime" in categories:
        checks.append("执行 memory-lifetime 检查，覆盖 allocation/free、refcount、cleanup 和 error paths。")
    if "concurrency" in categories:
        checks.append("压测 concurrency paths，并 review lock/unlock、atomic、timer 和 thread interactions。")
    if "protocol_compatibility" in categories:
        checks.append("验证 protocol compatibility，覆盖旧 peer/client data 和 version negotiation。")
    if "state_machine_timing" in categories:
        checks.append("回放 state-machine、timeout、retry、start/stop 和 event-order scenarios。")
    if "callback_dispatch" in categories:
        checks.append("Review callback、ops table、handler registration 和 dispatch table behavior。")
    if "performance_resource" in categories:
        checks.append("检查 CPU、memory、file/socket/thread/timer resources 和 loop complexity。")
    if "security_boundary" in categories:
        checks.append("Review auth、permission、input validation 和 path/command handling。")
    if "build_deploy" in categories:
        checks.append("验证 build variants、link flags、exported symbols 和 deployment packaging。")
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
        entry["why_impacted"].append("CodeGraph/fallback impact path reaches this subsystem")
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
    path.write_text(text, encoding="utf-8-sig")


def manual_review_items(risks):
    review = []
    keywords = (
        "header file changed",
        "struct/union/enum/typedef changed",
        "macro or conditional compilation changed",
        "callback/function pointer pattern changed",
        "memory allocation/lifetime related change",
        "semantic behavior keyword changed",
        "architecture risk",
    )
    for item in risks:
        reasons = "; ".join(item["reasons"])
        if item["level"] == "high" or any(keyword in reasons for keyword in keywords):
            review.append({"subject": item["subject"], "kind": item["kind"], "level": item["level"], "reasons": item["reasons"]})
    return review[:30]


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
    confidence = "high" if "codegraph" in backends else "medium" if "rg" in backends else "low"
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
        "- fallback 命中的 symbol 数: {}".format(codegraph["fallback_used_for_symbols"]),
        "- changed files: {}".format(len(files)),
        "- changed symbols: {}".format(len(symbols)),
        "- public interface paths: {}".format(", ".join(config["public_interfaces"][:8])),
        "- legacy paths: {}".format(", ".join(config["legacy_paths"][:8])),
        "",
        "## 分析分层",
        "- CodeGraph 层：用于查找 function/symbol reference、callers/callees、include/import 关系和 subsystem 影响面；它提供影响路径 evidence，但不单独证明变更安全。",
        "- Heuristic 层：根据变量名、函数名、路径、diff 内容、risk category 和 deterministic scoring 识别风险信号；这些结论是 risk triage，不是完整 data-flow proof。",
        "- Manual Review 层：对内存 ownership、callback/async flow、struct field 传递、alias/data-flow、error cleanup path 等静态工具难以确认的项目，输出到报告的 `必须人工 Review`，要求人工排查。",
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

    review = manual_review_items(risks)
    lines.extend(["", "## 必须人工 Review", ""])
    if review:
        for item in review:
            lines.append("- `{}` ({}, {}): {}".format(item["subject"], item["kind"], item["level"], "; ".join(item["reasons"])))
    else:
        lines.append("- deterministic rules 未发现必须人工 Review 的项目。")

    memory_items = [item for item in risks if item["kind"] == "memory-lifetime"]
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
            "- 人工检查 struct layout、enum values、macros、callbacks 和 function pointer tables。",
            "- 对 memory-lifetime 变更执行内存泄漏专项检查，尤其关注分配/释放和错误路径。",
            "- 对引用范围较广的 symbol，每个受影响 subsystem 至少验证一条 legacy feature path。",
            "",
            "## 局限性",
            "- 这是 regression risk triage scan，不是 compatibility proof。",
            "- 如果没有 compile database 或 semantic C index，macro expansion 和 conditional compilation paths 可能不完整。",
            "- 除非 CodeGraph 本地索引捕获了 function pointer 和 callback 关系，否则相关判断属于 heuristic analysis。",
        ]
    )
    if codegraph["errors"]:
        lines.extend(["", "## CodeGraph 说明"])
        for error in codegraph["errors"][:8]:
            lines.append("- {}".format(error))
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Scan C change impact for architecture regression risk.")
    parser.add_argument("--range", default="HEAD~1..HEAD", help="git commit range to scan")
    parser.add_argument("--out", default=".impact-scan", help="output directory")
    parser.add_argument("--subsystem", default="", help="repo-relative subsystem directory to scan, such as subsys/net")
    parser.add_argument("--max-symbols", type=int, default=200, help="maximum changed symbols to analyze")
    parser.add_argument("--max-refs", type=int, default=50, help="maximum reference files per symbol")
    parser.add_argument(
        "--codegraph-mode",
        choices=["prefer", "required", "off"],
        default="prefer",
        help="CodeGraph usage mode. Default prefers CodeGraph and falls back to rg.",
    )
    parser.add_argument(
        "--init-codegraph",
        action="store_true",
        help="Attempt non-destructive CodeGraph init/index commands when .codegraph is absent.",
    )
    args = parser.parse_args()

    cwd = Path.cwd()
    try:
        repo = ensure_git_repo(cwd)
    except Exception as exc:
        print("error: not a git repository or git failed: {}".format(exc), file=sys.stderr)
        return 2

    out = repo / args.out
    out.mkdir(parents=True, exist_ok=True)
    config = load_scan_config(repo, args.subsystem)

    codegraph = prepare_codegraph(repo, args.codegraph_mode, args.init_codegraph)
    if args.codegraph_mode == "required" and not codegraph["available"]:
        write_json(out / "codegraph_status.json", codegraph)
        print("error: CodeGraph is required but codegraph executable was not found", file=sys.stderr)
        return 3

    files = parse_changed_files(repo, args.range, config)
    symbols = extract_symbols(repo, args.range, args.max_symbols, config)
    refs = gather_references(repo, symbols, args.max_refs, codegraph, config)
    risks = build_risk_items(files, symbols, refs, config)
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
    write_json(out / "manual_review.json", manual_review_items(risks))
    write_json(out / "subsystem_impact.json", subsystems)
    write_json(out / "subsystem_analysis.json", subsystem_analysis)
    write_markdown_report(
        out / "risk_report.md",
        markdown_report(
            args.range,
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
        ),
    )

    print("wrote {}".format(out / "risk_report.md"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
