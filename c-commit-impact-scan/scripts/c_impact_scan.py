#!/usr/bin/env python3
"""Deterministic C commit impact scanner for weak intranet agents.

The script favors portable Windows behavior: no shell pipelines, no Unix-only
tools, bounded output, and JSON artifacts for model summarization.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable


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


@dataclass
class ChangedFile:
    path: str
    status: str
    added: int = 0
    deleted: int = 0
    is_c: bool = False
    is_header: bool = False
    is_public_path: bool = False
    is_build_file: bool = False


@dataclass
class ChangedSymbol:
    name: str
    file: str
    kind: str
    evidence: str


@dataclass
class ReferenceResult:
    symbol: str
    backend: str
    files: list[str]
    file_count: int
    subsystem_count: int


@dataclass
class RiskItem:
    subject: str
    kind: str
    score: int
    level: str
    reasons: list[str]
    evidence_files: list[str]


@dataclass
class CodeGraphStatus:
    mode: str
    available: bool
    executable: str | None
    index_present: bool
    init_attempted: bool
    init_succeeded: bool
    used_for_symbols: int
    fallback_used_for_symbols: int
    errors: list[str]


def run(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args,
            cwd=str(cwd),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=check,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"missing command: {args[0]}") from exc


def git(args: list[str], cwd: Path) -> str:
    result = run(["git", *args], cwd)
    return result.stdout


def ensure_git_repo(cwd: Path) -> Path:
    root = git(["rev-parse", "--show-toplevel"], cwd).strip()
    return Path(root)


def normalize(path: str) -> str:
    return path.replace("\\", "/")


def subsystem_for(path: str, depth: int = 2) -> str:
    parts = [p for p in normalize(path).split("/") if p]
    if not parts:
        return "."
    return "/".join(parts[:depth])


def parse_changed_files(repo: Path, commit_range: str) -> list[ChangedFile]:
    output = git(["diff", "--numstat", "--name-status", commit_range], repo)
    files: dict[str, ChangedFile] = {}
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 3 and parts[0].isdigit():
            added = int(parts[0])
            deleted = int(parts[1]) if parts[1].isdigit() else 0
            path = normalize(parts[2])
            files.setdefault(path, ChangedFile(path=path, status="M"))
            files[path].added = added
            files[path].deleted = deleted
        elif len(parts) >= 2:
            status = parts[0]
            path = normalize(parts[-1])
            files.setdefault(path, ChangedFile(path=path, status=status))

    for item in files.values():
        item.is_c = bool(C_FILE_RE.search(item.path))
        item.is_header = bool(HEADER_RE.search(item.path))
        item.is_public_path = bool(PUBLIC_PATH_RE.search(item.path))
        item.is_build_file = bool(BUILD_FILE_RE.search(item.path))
    return sorted(files.values(), key=lambda x: x.path)


def diff_lines(repo: Path, commit_range: str) -> Iterable[tuple[str, str]]:
    output = git(["diff", "--unified=0", commit_range, "--", "*.c", "*.h"], repo)
    current_file = ""
    for line in output.splitlines():
        if line.startswith("+++ b/"):
            current_file = normalize(line[6:])
            continue
        if line.startswith("+") and not line.startswith("+++"):
            yield current_file, line[1:]
        elif line.startswith("-") and not line.startswith("---"):
            yield current_file, line[1:]


def extract_symbols(repo: Path, commit_range: str, max_symbols: int) -> list[ChangedSymbol]:
    symbols: dict[tuple[str, str, str], ChangedSymbol] = {}
    for file_path, line in diff_lines(repo, commit_range):
        if not file_path:
            continue
        stripped = line.strip()
        if not stripped:
            continue

        kind = ""
        name = ""
        if MACRO_RE.search(stripped):
            kind = "macro-or-conditional"
            match = re.match(r"^\s*#\s*(?:define|undef)\s+([A-Za-z_]\w*)", stripped)
            if match:
                name = match.group(1)
        elif TYPE_RE.search(stripped):
            kind = "type"
            ids = IDENT_RE.findall(stripped)
            for token in ids:
                if token not in {"typedef", "struct", "union", "enum", "const", "volatile"}:
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
            symbols[key] = ChangedSymbol(name=name, file=file_path, kind=kind, evidence=stripped[:240])
            if len(symbols) >= max_symbols:
                break
    return list(symbols.values())


def find_codegraph() -> str | None:
    return shutil.which("codegraph") or shutil.which("codegraph.exe")


def has_codegraph_index(repo: Path) -> bool:
    return (repo / ".codegraph").exists()


def prepare_codegraph(repo: Path, mode: str, init_codegraph: bool) -> CodeGraphStatus:
    exe = find_codegraph()
    status = CodeGraphStatus(
        mode=mode,
        available=bool(exe),
        executable=exe,
        index_present=has_codegraph_index(repo),
        init_attempted=False,
        init_succeeded=False,
        used_for_symbols=0,
        fallback_used_for_symbols=0,
        errors=[],
    )
    if mode == "off":
        return status
    if not exe:
        status.errors.append("codegraph executable not found")
        return status
    if status.index_present:
        return status
    if not init_codegraph:
        status.errors.append("CodeGraph index directory .codegraph was not found; rerun with --init-codegraph if indexing is approved")
        return status

    status.init_attempted = True
    init_commands = [
        [exe, "init"],
        [exe, "index"],
    ]
    any_success = False
    for command in init_commands:
        result = subprocess.run(
            command,
            cwd=str(repo),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode == 0:
            any_success = True
        elif result.stderr.strip():
            status.errors.append(f"{' '.join(command)} failed: {result.stderr.strip()[:500]}")
    status.index_present = has_codegraph_index(repo)
    status.init_succeeded = any_success or status.index_present
    if not status.index_present:
        status.errors.append("CodeGraph init/index did not create a .codegraph directory")
    return status


def run_codegraph_impact(repo: Path, symbol: str, limit: int, status: CodeGraphStatus) -> list[str]:
    if status.mode == "off" or not status.executable:
        return []
    commands = [
        [status.executable, "impact", symbol],
        [status.executable, "impact", "--symbol", symbol],
    ]
    for command in commands:
        result = subprocess.run(
            command,
            cwd=str(repo),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return extract_paths_from_text(result.stdout, limit)
    return []


def extract_paths_from_text(text: str, limit: int) -> list[str]:
    paths: list[str] = []
    seen = set()
    for match in re.finditer(r"[\w./\\:-]+\.(?:c|h)\b", text, re.I):
        path = normalize(match.group(0))
        if path not in seen:
            paths.append(path)
            seen.add(path)
        if len(paths) >= limit:
            break
    return paths


def rg_references(repo: Path, symbol: str, limit: int) -> list[str]:
    exe = shutil.which("rg") or shutil.which("rg.exe")
    if not exe:
        return []
    pattern = rf"\b{re.escape(symbol)}\b"
    result = subprocess.run(
        [exe, "--files-with-matches", "--glob", "*.c", "--glob", "*.h", pattern, "."],
        cwd=str(repo),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
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


def gather_references(
    repo: Path, symbols: list[ChangedSymbol], limit: int, codegraph_status: CodeGraphStatus
) -> list[ReferenceResult]:
    results = []
    for symbol in symbols:
        backend = "none"
        files = run_codegraph_impact(repo, symbol.name, limit, codegraph_status)
        if files:
            backend = "codegraph"
            codegraph_status.used_for_symbols += 1
        else:
            files = rg_references(repo, symbol.name, limit)
            if files:
                backend = "rg"
                codegraph_status.fallback_used_for_symbols += 1
        subsystems = {subsystem_for(path) for path in files}
        results.append(
            ReferenceResult(
                symbol=symbol.name,
                backend=backend,
                files=files,
                file_count=len(files),
                subsystem_count=len(subsystems),
            )
        )
    return results


def score_file(item: ChangedFile) -> tuple[int, list[str]]:
    score = 0
    reasons = []
    if item.is_header:
        score += 4
        reasons.append("header file changed")
    if item.is_public_path:
        score += 3
        reasons.append("public/shared path changed")
    if item.is_build_file:
        score += 3
        reasons.append("build or feature switch file changed")
    if item.added + item.deleted >= 80:
        score += 2
        reasons.append("large change size")
    return score, reasons


def score_symbol(symbol: ChangedSymbol, refs: ReferenceResult | None) -> tuple[int, list[str]]:
    score = 0
    reasons = []
    if symbol.kind == "function":
        score += 4
        reasons.append("function declaration or definition changed")
    elif symbol.kind == "type":
        score += 4
        reasons.append("struct/union/enum/typedef changed")
    elif symbol.kind == "macro-or-conditional":
        score += 3
        reasons.append("macro or conditional compilation changed")
    elif symbol.kind == "callback-or-function-pointer":
        score += 4
        reasons.append("callback/function pointer pattern changed")
    elif symbol.kind == "global":
        score += 2
        reasons.append("global data changed")
    if PUBLIC_PATH_RE.search(symbol.file):
        score += 3
        reasons.append("symbol is in public/shared path")
    if refs:
        if refs.file_count >= 10:
            score += 3
            reasons.append(f"referenced by {refs.file_count} files")
        if refs.subsystem_count >= 3:
            score += 3
            reasons.append(f"spans {refs.subsystem_count} subsystems")
    return score, reasons


def level_for(score: int) -> str:
    if score >= 8:
        return "high"
    if score >= 4:
        return "medium"
    return "low"


def build_risk_items(
    files: list[ChangedFile], symbols: list[ChangedSymbol], refs: list[ReferenceResult]
) -> list[RiskItem]:
    risk_items: list[RiskItem] = []
    refs_by_symbol = {r.symbol: r for r in refs}
    for item in files:
        score, reasons = score_file(item)
        if score:
            risk_items.append(
                RiskItem(
                    subject=item.path,
                    kind="file",
                    score=score,
                    level=level_for(score),
                    reasons=reasons,
                    evidence_files=[item.path],
                )
            )
    for symbol in symbols:
        ref = refs_by_symbol.get(symbol.name)
        score, reasons = score_symbol(symbol, ref)
        evidence = [symbol.file]
        if ref:
            evidence.extend(ref.files[:10])
        risk_items.append(
            RiskItem(
                subject=symbol.name,
                kind=symbol.kind,
                score=score,
                level=level_for(score),
                reasons=reasons,
                evidence_files=list(dict.fromkeys(evidence)),
            )
        )
    return sorted(risk_items, key=lambda x: (-x.score, x.subject))


def subsystem_impact(files: list[ChangedFile], refs: list[ReferenceResult]) -> dict[str, object]:
    counter: Counter[str] = Counter()
    evidence: dict[str, set[str]] = defaultdict(set)
    for item in files:
        sub = subsystem_for(item.path)
        counter[sub] += 1
        evidence[sub].add(item.path)
    for ref in refs:
        for path in ref.files:
            sub = subsystem_for(path)
            counter[sub] += 1
            evidence[sub].add(path)
    return {
        "subsystems": [
            {"name": name, "count": count, "evidence_files": sorted(evidence[name])[:20]}
            for name, count in counter.most_common()
        ]
    }


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def markdown_report(
    commit_range: str,
    codegraph_status: CodeGraphStatus,
    files: list[ChangedFile],
    symbols: list[ChangedSymbol],
    refs: list[ReferenceResult],
    risks: list[RiskItem],
    subsystems: dict[str, object],
) -> str:
    top_level = risks[0].level if risks else "low"
    max_score = risks[0].score if risks else 0
    backends = {r.backend for r in refs if r.backend != "none"}
    confidence = "high" if "codegraph" in backends else "medium" if "rg" in backends else "low"
    lines = [
        "# C Commit Impact Scan Report",
        "",
        "## Summary",
        f"- Range: `{commit_range}`",
        f"- Overall risk: **{top_level}**",
        f"- Max score: {max_score}",
        f"- Confidence: **{confidence}**",
        f"- CodeGraph mode: `{codegraph_status.mode}`",
        f"- CodeGraph available: {'yes' if codegraph_status.available else 'no'}",
        f"- CodeGraph used for symbols: {codegraph_status.used_for_symbols}",
        f"- Fallback used for symbols: {codegraph_status.fallback_used_for_symbols}",
        f"- Changed files: {len(files)}",
        f"- Changed symbols detected: {len(symbols)}",
        "",
        "## High And Medium Risk Items",
        "",
        "| Subject | Kind | Score | Level | Reasons |",
        "|---|---|---:|---|---|",
    ]
    for item in risks[:30]:
        if item.level == "low":
            continue
        reasons = "; ".join(item.reasons)
        lines.append(f"| `{item.subject}` | {item.kind} | {item.score} | {item.level} | {reasons} |")
    if all(item.level == "low" for item in risks):
        lines.append("| None detected | - | 0 | low | No deterministic high-risk rule matched |")

    lines.extend(["", "## Affected Subsystem Candidates", ""])
    for sub in subsystems.get("subsystems", [])[:20]:
        lines.append(f"- `{sub['name']}`: {sub['count']} evidence hits")

    lines.extend(["", "## Reference Evidence", ""])
    for ref in refs[:30]:
        if not ref.files:
            continue
        sample = ", ".join(f"`{p}`" for p in ref.files[:8])
        lines.append(
            f"- `{ref.symbol}` via {ref.backend}: {ref.file_count} files, "
            f"{ref.subsystem_count} subsystems. {sample}"
        )

    lines.extend(
        [
            "",
            "## Suggested Regression Checks",
            "- Review high-risk public headers and shared modules listed above.",
            "- Run legacy tests for affected subsystem candidates.",
            "- Manually inspect struct layout, enum values, macros, callbacks, and function pointer tables.",
            "- For symbols with broad references, test at least one old feature path per affected subsystem.",
            "",
            "## Limitations",
            "- This is a triage scan, not a proof of compatibility.",
            "- Without a compile database or semantic C index, macro-expanded and conditional-compilation paths may be incomplete.",
            "- Function pointer and callback relationships are heuristic unless CodeGraph captures them in the local index.",
        ]
    )
    if codegraph_status.errors:
        lines.extend(["", "## CodeGraph Notes"])
        for error in codegraph_status.errors[:8]:
            lines.append(f"- {error}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan C commit impact for legacy feature risk.")
    parser.add_argument("--range", default="HEAD~1..HEAD", help="git commit range to scan")
    parser.add_argument("--out", default=".impact-scan", help="output directory")
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
        print(f"error: not a git repository or git failed: {exc}", file=sys.stderr)
        return 2

    out = repo / args.out
    out.mkdir(parents=True, exist_ok=True)

    codegraph_status = prepare_codegraph(repo, args.codegraph_mode, args.init_codegraph)
    if args.codegraph_mode == "required" and not codegraph_status.available:
        write_json(out / "codegraph_status.json", asdict(codegraph_status))
        print("error: CodeGraph is required but codegraph executable was not found", file=sys.stderr)
        return 3

    files = parse_changed_files(repo, args.range)
    symbols = extract_symbols(repo, args.range, args.max_symbols)
    refs = gather_references(repo, symbols, args.max_refs, codegraph_status)
    risks = build_risk_items(files, symbols, refs)
    subsystems = subsystem_impact(files, refs)

    write_json(out / "codegraph_status.json", asdict(codegraph_status))
    write_json(out / "diff_summary.json", [asdict(item) for item in files])
    write_json(out / "changed_symbols.json", [asdict(item) for item in symbols])
    write_json(out / "references.json", [asdict(item) for item in refs])
    write_json(out / "risk_items.json", [asdict(item) for item in risks])
    write_json(out / "subsystem_impact.json", subsystems)
    (out / "risk_report.md").write_text(
        markdown_report(args.range, codegraph_status, files, symbols, refs, risks, subsystems),
        encoding="utf-8",
    )

    print(f"wrote {out / 'risk_report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
