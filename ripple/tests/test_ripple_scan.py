import importlib.util
import json
from unittest import mock
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ripple_scan.py"
SPEC = importlib.util.spec_from_file_location("ripple_scan", str(SCRIPT))
scan = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scan)


class CImpactScanTests(unittest.TestCase):
    def test_loads_architecture_config_from_subsystem_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subsystem = repo / "subsys" / "net"
            subsystem.mkdir(parents=True)
            (subsystem / ".impact-scan.yml").write_text(
                "\n".join(
                    [
                        "public_interfaces:",
                        "  - include/",
                        "legacy_paths:",
                        "  - legacy/",
                        "high_risk_paths:",
                        "  - platform/",
                        "memory_sensitive_paths:",
                        "  - core/session/",
                    ]
                ),
                encoding="utf-8",
            )

            config = scan.load_scan_config(repo, "subsys/net")

        self.assertEqual("subsys/net", config["scope_path"])
        self.assertIn("subsys/net/include/", config["public_interfaces"])
        self.assertIn("subsys/net/legacy/", config["legacy_paths"])
        self.assertIn("subsys/net/platform/", config["high_risk_paths"])
        self.assertIn("subsys/net/core/session/", config["memory_sensitive_paths"])

    def test_subsystem_scope_filters_changed_files(self):
        config = scan.default_scan_config("subsys/net")
        files = [
            scan.changed_file("subsys/net/include/api.h", "M"),
            scan.changed_file("subsys/storage/include/api.h", "M"),
        ]

        scoped = scan.filter_files_by_scope(files, config)

        self.assertEqual(["subsys/net/include/api.h"], [item["path"] for item in scoped])

    def test_config_marks_public_legacy_and_high_risk_files(self):
        config = scan.default_scan_config()
        config["public_interfaces"].append("sdk/include/")
        config["legacy_paths"].append("legacy/http/")
        config["high_risk_paths"].append("platform/")

        public_file = scan.changed_file("sdk/include/foo.h", "M")
        legacy_file = scan.changed_file("legacy/http/client.c", "M")
        platform_file = scan.changed_file("platform/os/mem.c", "M")

        scan.apply_config_to_file(public_file, config)
        scan.apply_config_to_file(legacy_file, config)
        scan.apply_config_to_file(platform_file, config)

        self.assertTrue(public_file["is_public_interface"])
        self.assertTrue(legacy_file["is_legacy_path"])
        self.assertTrue(platform_file["is_high_risk_path"])

    def test_memory_lifetime_change_scores_high_and_requires_review(self):
        config = scan.default_scan_config()
        config["memory_sensitive_paths"].append("core/session/")
        symbol = scan.changed_symbol(
            "session_alloc",
            "core/session/session.c",
            "memory-lifetime",
            "ctx = malloc(sizeof(*ctx));",
        )

        score, reasons = scan.score_symbol(symbol, None, config)

        self.assertGreaterEqual(score, 8)
        self.assertTrue(any("memory" in reason.lower() for reason in reasons))

    def test_default_enabled_risks_exclude_unneeded_categories(self):
        config = scan.default_scan_config()

        self.assertEqual(
            [
                "memory_leak",
                "memory_safety",
                "abi_layout",
                "pointer_alias_lifetime",
                "error_handling",
                "callback_dispatch",
            ],
            config["enabled_risk_categories"],
        )

    def test_single_thread_model_ignores_parallelism_signals(self):
        config = scan.default_scan_config()
        removed_category = "con" + "currency"
        removed_timing_category = "state_machine" + "_timing"
        parallelism_evidence = (
            "p" + "thread_" + "mu" + "tex_unlock(&ctx->lock); "
            "timer_start(ctx->timer, timeout);"
        )
        symbol = scan.changed_symbol(
            "timer_start",
            "nio/timer.c",
            "function",
            parallelism_evidence,
        )

        score, reasons = scan.score_symbol(symbol, None, config)
        risks = scan.build_risk_items([], [symbol], [], config)

        self.assertNotIn(removed_category, symbol["risk_categories"])
        self.assertNotIn(removed_timing_category, symbol["risk_categories"])
        self.assertFalse(any(removed_category in reason for reason in reasons))
        self.assertFalse(any("semantic behavior keyword" in reason for reason in reasons))
        self.assertFalse(any(removed_timing_category in reason for reason in reasons))
        self.assertNotIn(removed_category, risks[0]["risk_categories"])
        self.assertNotIn(removed_timing_category, risks[0]["risk_categories"])

    def test_normalize_strips_ansi_color_codes_from_paths(self):
        self.assertEqual(
            "fosip/nbm/xpath1.c",
            scan.normalize("\x1b[36mfosip\\nbm\\xpath1.c\x1b[0m"),
        )

    def test_normalize_strips_visible_ansi_fragments_from_paths(self):
        self.assertEqual("fosip/nbm", scan.normalize("36mfosip/nbm"))
        self.assertEqual("xpath1.c", scan.normalize("0mxpath1.c"))

    def test_subsystem_inference_ignores_ansi_fragments(self):
        item = scan.changed_file("36mfosip/nbm/xpath1.c", "M")

        self.assertEqual("fosip/nbm", scan.subsystem_for(item["path"]))

    def test_container_insert_change_is_memory_lifetime_risk(self):
        symbol = scan.changed_symbol(
            "list_add_tail",
            "core/session/cache.c",
            "function",
            "list_add_tail(&ctx->node, &cache->active_list);",
        )

        categories = scan.detect_risk_categories(symbol["evidence"], symbol["file"], symbol["kind"])
        score, reasons = scan.score_symbol(symbol, None, scan.default_scan_config())

        self.assertIn("memory_leak", categories)
        self.assertNotIn("ownership" + "_lifetime", categories)
        self.assertGreaterEqual(score, 8)
        self.assertTrue(any("container" in reason.lower() or "memory" in reason.lower() for reason in reasons))

    def test_legacy_reference_increases_symbol_risk(self):
        config = scan.default_scan_config()
        config["legacy_paths"].append("legacy/http/")
        symbol = scan.changed_symbol("api_open", "common/api/session.h", "function", "int api_open(void);")
        refs = scan.reference_result("api_open", "codegraph", ["legacy/http/client.c", "new/feature.c"])

        score, reasons = scan.score_symbol(symbol, refs, config)

        self.assertGreaterEqual(score, 8)
        self.assertTrue(any("legacy" in reason.lower() for reason in reasons))

    def test_impact_paths_mark_legacy_and_subsystem(self):
        config = scan.default_scan_config()
        config["legacy_paths"].append("legacy/http/")
        refs = [scan.reference_result("api_open", "codegraph", ["legacy/http/client.c"], config)]

        paths = scan.build_impact_paths(refs, config)

        self.assertEqual(paths[0]["symbol"], "api_open")
        self.assertEqual(paths[0]["target_file"], "legacy/http/client.c")
        self.assertTrue(paths[0]["is_legacy"])
        self.assertEqual(paths[0]["subsystem"], "legacy/http")

    def test_subsystem_analysis_expands_impact_reason_and_checks(self):
        config = scan.default_scan_config("subsys/net")
        config["legacy_paths"].append("subsys/net/legacy/")
        files = [scan.changed_file("subsys/net/include/api.h", "M", added=3, deleted=1)]
        for item in files:
            scan.apply_config_to_file(item, config)
        refs = [scan.reference_result("api_open", "codegraph", ["subsys/net/legacy/client.c"], config)]
        risks = [
            scan.risk_item(
                "api_open",
                "function",
                12,
                ["symbol is in public/shared path", "referenced by 1 legacy files"],
                ["subsys/net/include/api.h", "subsys/net/legacy/client.c"],
                ["abi_layout", "error_handling"],
            )
        ]
        impact_paths = scan.build_impact_paths(refs, config)

        analysis = scan.build_subsystem_analysis(files, refs, risks, impact_paths, config)

        self.assertEqual("subsys/net", analysis[0]["name"])
        self.assertIn("subsys/net/include/api.h", analysis[0]["changed_files"])
        self.assertIn("subsys/net/legacy/client.c", analysis[0]["referenced_files"])
        self.assertIn("api_open", analysis[0]["symbols"])
        self.assertIn("abi_layout", analysis[0]["risk_categories"])
        self.assertTrue(analysis[0]["legacy_hit"])
        self.assertTrue(any("public interface" in reason for reason in analysis[0]["why_impacted"]))
        self.assertTrue(any("legacy tests" in check for check in analysis[0]["suggested_checks"]))

    def test_markdown_report_documents_three_analysis_layers(self):
        config = scan.default_scan_config("subsys/net")
        codegraph = scan.codegraph_status("required")
        report = scan.markdown_report(
            "HEAD~1..HEAD",
            codegraph,
            [],
            [],
            [],
            [],
            {"subsystems": []},
            config,
            [],
            [],
            [],
        )

        self.assertIn("## 分析分层", report)
        self.assertIn("CodeGraph 层", report)
        self.assertIn("Heuristic 层", report)
        self.assertIn("生命周期证据层", report)

    def test_detects_architecture_risk_categories_from_c_evidence(self):
        cases = {
            "memory_safety": "memcpy(dst, src, len + 1);",
            "memory_leak": "ctx = malloc(sizeof(*ctx)); return -1;",
            "abi_layout": "struct api_msg { int version; long size; };",
            "error_handling": "if (!ctx) return ERR_INVALID;",
            "callback_dispatch": "ops->open = handler; register_callback(cb);",
        }

        for expected, evidence in cases.items():
            categories = scan.detect_risk_categories(evidence, "subsys/net/api.c", "function")
            self.assertIn(expected, categories, evidence)

    def test_architecture_categories_increase_score(self):
        config = scan.default_scan_config("subsys/net")
        symbol = scan.changed_symbol(
            "parse_packet",
            "subsys/net/protocol/parser.c",
            "function",
            "memcpy(buf, pkt->payload, pkt->len); if (!auth_check(token)) return ERR_DENIED;",
        )

        score, reasons = scan.score_symbol(symbol, None, config)

        self.assertGreaterEqual(score, 8)
        self.assertTrue(any("memory_safety" in reason for reason in reasons))
        self.assertNotIn("security" + "_boundary", symbol["risk_categories"])

    def test_shallow_non_entry_caller_is_not_complete_root(self):
        status = scan.call_chain_termination_status(
            ["middle_helper", "changed_func"],
            "middle_helper",
            "changed_func",
            max_depth=12,
        )

        self.assertEqual("evidence_gap", status)

    def test_step3_completion_requires_successful_call_chain_path(self):
        analysis = {
            "symbols": [
                {
                    "symbol": "changed_func",
                    "business_entry_groups": [
                        {
                            "entry": "middle_helper",
                            "path": ["middle_helper", "changed_func"],
                            "depth": 1,
                            "termination_status": "evidence_gap",
                            "legacy_hit": False,
                            "needs_source_review": True,
                        }
                    ],
                    "branch_points": [],
                    "file": "fosip/nbm/x.c",
                    "kind": "function",
                }
            ]
        }

        artifacts = scan.build_step3_structured_artifacts(analysis)
        completion = artifacts["step3f_completion.json"]

        self.assertFalse(completion["step3_complete"])
        self.assertIn("successful_call_chain_path", completion["missing_sections"])

    def test_decodes_utf8_subprocess_output_for_linux_locale(self):
        raw = "中文路径/模块.c -> €\n".encode("utf-8")

        decoded = scan.decode_process_output(raw)

        self.assertIn("中文路径/模块.c", decoded)
        self.assertIn("€", decoded)

    def test_markdown_report_is_written_as_plain_utf8_for_linux(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "risk_report.md"

            scan.write_markdown_report(path, "# 中文报告\n")

            raw = path.read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertEqual("# 中文报告\n", raw.decode("utf-8"))

    def test_tool_lookup_uses_codegraph_only(self):
        with mock.patch.object(scan.shutil, "which", return_value=None) as which:
            scan.find_codegraph()

        looked_up = [call.args[0] for call in which.call_args_list]
        self.assertEqual(["codegraph"], looked_up)

    def test_required_codegraph_mode_does_not_use_reference_fallback(self):
        codegraph = scan.codegraph_status("required")
        codegraph["executable"] = "/usr/bin/codegraph"
        symbols = [scan.changed_symbol("api_open", "src/api.c", "function", "int api_open(void);")]

        with mock.patch.object(scan, "run_codegraph_impact", return_value=[]):
            refs = scan.gather_references(Path("."), symbols, 50, codegraph, scan.default_scan_config())

        self.assertEqual("none", refs[0]["backend"])

    def test_call_chain_analysis_groups_deep_and_local_branch_points(self):
        config = scan.default_scan_config("fosip/nbm")
        symbols = [
            scan.changed_symbol(
                "common_flow",
                "fosip/nbm/common.c",
                "local-function-context",
                "if (state == READY) { return enqueue(ctx); }",
            )
        ]
        refs = [
            scan.reference_result(
                "common_flow",
                "codegraph",
                [
                    "fosip/nbm/northbound/open_handler.c",
                    "fosip/nem/legacy/old_handler.c",
                    "fosip/nio/dispatch/msg_dispatch.c",
                ],
                config,
            )
        ]
        raw_graph = {
            "common_flow": {
                "paths": [
                    ["nbm_open_api", "nbm_prepare", "common_flow"],
                    ["legacy_nbm_open", "nbm_prepare", "common_flow"],
                    ["msg_dispatch", "nbm_msg_handler", "common_flow"],
                ],
                "callers": ["nbm_prepare", "nbm_msg_handler"],
                "callees": ["enqueue", "set_state"],
            }
        }

        analysis = scan.build_call_chain_analysis(symbols, refs, config, raw_graph, max_depth=15)

        item = analysis["symbols"][0]
        self.assertEqual("common_flow", item["symbol"])
        self.assertEqual(15, item["max_depth"])
        statuses = [group["termination_status"] for group in item["business_entry_groups"]]
        self.assertTrue(all(status in scan.CALL_CHAIN_TERMINATION_STATUSES for status in statuses))
        self.assertIn("complete_to_entry", statuses)
        self.assertIn("local-control-flow", [point["kind"] for point in item["branch_points"]])
        self.assertIn("upstream-fan-in", [point["kind"] for point in item["branch_points"]])
        self.assertIn("downstream-fan-out", [point["kind"] for point in item["branch_points"]])
        entries = [group["entry"] for group in item["business_entry_groups"]]
        self.assertIn("nbm_open_api", entries)
        self.assertIn("legacy_nbm_open", entries)
        self.assertIn("msg_dispatch", entries)
        self.assertTrue(any(group["legacy_hit"] for group in item["business_entry_groups"]))

    def test_required_codegraph_mode_fails_when_index_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._make_git_repo(tmp)
            old_cwd = Path.cwd()
            try:
                import os
                os.chdir(str(repo))
                with mock.patch.object(scan, "find_codegraph", return_value="/usr/bin/codegraph"):
                    ret = scan.main(["--step", "discover", "--codegraph-mode", "required"])

                self.assertEqual(3, ret)
            finally:
                os.chdir(str(old_cwd))

    def test_default_cli_requires_codegraph(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._make_git_repo(tmp)
            old_cwd = Path.cwd()
            try:
                import os
                os.chdir(str(repo))
                with mock.patch.object(scan, "find_codegraph", return_value=None):
                    ret = scan.main([])

                self.assertEqual(3, ret)
            finally:
                os.chdir(str(old_cwd))

    def test_cli_rejects_prefer_codegraph_mode(self):
        with self.assertRaises(SystemExit):
            scan.main(["--codegraph-mode", "prefer"])


    def test_focus_config_loaded_from_yaml_file(self):
        config = scan.default_scan_config("subsys/net")
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / ".impact-scan-focus.yml").write_text(
                "\n".join([
                    "subsystem: subsys/net",
                    "focus_symbols:",
                    "  - api_open",
                    "  - session_alloc",
                    "ignore_paths:",
                    "  - tests/",
                    "  - docs/",
                    "legacy_paths:",
                    "  - oldflow/",
                    "public_interfaces:",
                    "  - exported/",
                    "notes:",
                    "  - old client must not change",
                ]),
                encoding="utf-8",
            )
            focus = scan.load_focus_config(repo)

        self.assertIn("api_open", focus["focus_symbols"])
        self.assertIn("session_alloc", focus["focus_symbols"])
        self.assertIn("tests/", focus["ignore_paths"])
        self.assertIn("oldflow/", focus["legacy_paths"])
        self.assertIn("exported/", focus["public_interfaces"])
        self.assertIn("subsys/net", focus["scope_override"])
        self.assertTrue(any("old client" in n for n in focus["notes"]))

    def test_focus_config_loaded_from_explicit_file_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            config_dir = repo / "configs"
            config_dir.mkdir()
            focus_file = config_dir / "net-focus.yml"
            focus_file.write_text(
                "\n".join([
                    "subsystem: subsys/net",
                    "focus_symbols:",
                    "  - api_open",
                    "legacy_paths:",
                    "  - oldflow/",
                    "public_interfaces:",
                    "  - exported/",
                ]),
                encoding="utf-8",
            )

            focus = scan.load_focus_config(focus_file)

        self.assertEqual("subsys/net", focus["scope_override"])
        self.assertEqual(["api_open"], focus["focus_symbols"])
        self.assertEqual(["oldflow/"], focus["legacy_paths"])
        self.assertEqual(["exported/"], focus["public_interfaces"])

    def test_focus_cli_flags_override_file_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            focus = scan.load_focus_config(
                repo,
                cli_focus_symbols="my_func,other_func",
                cli_ignore_paths="vendor/,third_party/",
            )

        self.assertEqual(["my_func", "other_func"], focus["focus_symbols"])
        self.assertEqual(["vendor/", "third_party/"], focus["ignore_paths"])

    def test_select_symbols_for_expansion_picks_focus_high_risk_and_memory(self):
        symbols = [
            scan.changed_symbol("api_open", "include/api.h", "function", "int api_open(void);"),
            scan.changed_symbol("helper", "src/helper.c", "function", "void helper(void);"),
            scan.changed_symbol("session_alloc", "core/session.c", "memory-lifetime", "ctx = malloc(sizeof(*ctx));"),
        ]
        risks = [
            scan.risk_item("api_open", "function", 12, ["public/shared interface path changed"], ["include/api.h"]),
            scan.risk_item("helper", "function", 2, ["small change"], ["src/helper.c"]),
            scan.risk_item("session_alloc", "memory-lifetime", 10, ["memory allocation/lifetime related change"], ["core/session.c"]),
        ]
        focus = {"focus_symbols": ["api_open"], "ignore_paths": [], "notes": []}

        selected, reasons = scan.select_symbols_for_expansion(symbols, risks, focus)

        self.assertIn("api_open", selected)
        self.assertIn("session_alloc", selected)
        self.assertNotIn("helper", selected)
        self.assertIn("user-specified focus symbol", reasons["api_open"])
        self.assertIn("memory-lifetime", reasons["session_alloc"])

    def test_ignore_paths_filter_removes_matching_items(self):
        focus = {"focus_symbols": [], "ignore_paths": ["tests/", "docs/"], "notes": []}
        items = [
            {"path": "tests/test_foo.c"},
            {"path": "docs/readme.md"},
            {"path": "src/main.c"},
        ]

        filtered = scan.filter_ignored_paths(items, focus)

        self.assertEqual(1, len(filtered))
        self.assertEqual("src/main.c", filtered[0]["path"])

    def test_focus_ignore_filters_symbols_risks_and_reference_files(self):
        focus = {"focus_symbols": [], "ignore_paths": ["tests/", "docs/"], "notes": []}
        config = scan.default_scan_config()
        symbols = [
            scan.changed_symbol("test_helper", "tests/test_helper.c", "function", "int test_helper(void);"),
            scan.changed_symbol("api_open", "src/api.c", "function", "int api_open(void);"),
        ]
        risks = [
            scan.risk_item("tests/test_helper.c", "file", 4, ["test only"], ["tests/test_helper.c"]),
            scan.risk_item("api_open", "function", 8, ["public/shared interface path changed"], ["tests/api_test.c", "src/api.c"]),
            scan.risk_item("doc_note", "function", 6, ["doc only"], ["docs/readme.md"]),
        ]
        refs = [
            scan.reference_result("api_open", "codegraph", ["tests/api_test.c", "src/client.c"], config),
        ]

        filtered_symbols = scan.filter_symbols_by_focus(symbols, focus)
        filtered_risks = scan.filter_risks_by_focus(risks, focus)
        filtered_refs = scan.filter_references_by_focus(refs, focus, config)

        self.assertEqual(["api_open"], [s["name"] for s in filtered_symbols])
        self.assertEqual(["api_open"], [r["subject"] for r in filtered_risks])
        self.assertEqual(["src/api.c"], filtered_risks[0]["evidence_files"])
        self.assertEqual(["src/client.c"], filtered_refs[0]["files"])
        self.assertEqual(1, filtered_refs[0]["file_count"])

    def _make_git_repo(self, tmp):
        """Create a minimal git repo in tmp with two commits (so HEAD~1..HEAD works)."""
        repo = Path(tmp)
        scan.run(["git", "init"], repo)
        scan.run(["git", "config", "user.email", "test@test"], repo)
        scan.run(["git", "config", "user.name", "test"], repo)
        (repo / "src").mkdir(exist_ok=True)
        (repo / "src/main.c").write_text("int main(void) { return 0; }\n", encoding="utf-8")
        scan.run(["git", "add", "."], repo)
        scan.run(["git", "commit", "-m", "initial"], repo)
        (repo / "src/main.c").write_text("int main(void) { return 1; }\n", encoding="utf-8")
        scan.run(["git", "add", "."], repo)
        scan.run(["git", "commit", "-m", "second"], repo)
        return repo

    def _make_git_repo_with_leaf_subsystem_change(self, tmp):
        repo = Path(tmp)
        scan.run(["git", "init"], repo)
        scan.run(["git", "config", "user.email", "test@test"], repo)
        scan.run(["git", "config", "user.name", "test"], repo)
        source_dir = repo / "fosip" / "nbm"
        source_dir.mkdir(parents=True)
        (source_dir / "api.c").write_text("int nbm_api(void) { return 0; }\n", encoding="utf-8")
        scan.run(["git", "add", "."], repo)
        scan.run(["git", "commit", "-m", "initial"], repo)
        (source_dir / "api.c").write_text("int nbm_api(void) { return 1; }\n", encoding="utf-8")
        scan.run(["git", "add", "."], repo)
        scan.run(["git", "commit", "-m", "update nbm"], repo)
        return repo

    def _make_git_repo_with_ambiguous_leaf_subsystem_change(self, tmp):
        repo = Path(tmp)
        scan.run(["git", "init"], repo)
        scan.run(["git", "config", "user.email", "test@test"], repo)
        scan.run(["git", "config", "user.name", "test"], repo)
        for root in ("fosip", "product"):
            source_dir = repo / root / "nbm"
            source_dir.mkdir(parents=True)
            (source_dir / "api.c").write_text("int api(void) { return 0; }\n", encoding="utf-8")
        scan.run(["git", "add", "."], repo)
        scan.run(["git", "commit", "-m", "initial"], repo)
        for root in ("fosip", "product"):
            (repo / root / "nbm" / "api.c").write_text("int api(void) { return 1; }\n", encoding="utf-8")
        scan.run(["git", "add", "."], repo)
        scan.run(["git", "commit", "-m", "ambiguous nbm"], repo)
        return repo

    def _make_git_repo_with_local_variable_change(self, tmp):
        repo = Path(tmp)
        scan.run(["git", "init"], repo)
        scan.run(["git", "config", "user.email", "test@test"], repo)
        scan.run(["git", "config", "user.name", "test"], repo)
        source_dir = repo / "fosip" / "nbm"
        source_dir.mkdir(parents=True)
        (source_dir / "api.c").write_text(
            "\n".join(
                [
                    "int nbm_api(int flag)",
                    "{",
                    "    int ret = flag;",
                    "    return ret;",
                    "}",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        scan.run(["git", "add", "."], repo)
        scan.run(["git", "commit", "-m", "initial"], repo)
        (source_dir / "api.c").write_text(
            "\n".join(
                [
                    "int nbm_api(int flag)",
                    "{",
                    "    int ret = flag + 1;",
                    "    return ret;",
                    "}",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        scan.run(["git", "add", "."], repo)
        scan.run(["git", "commit", "-m", "local change"], repo)
        return repo

    def _make_git_repo_with_multiline_function_local_change(self, tmp):
        repo = Path(tmp)
        scan.run(["git", "init"], repo)
        scan.run(["git", "config", "user.email", "test@test"], repo)
        scan.run(["git", "config", "user.name", "test"], repo)
        source_dir = repo / "fosip" / "nbm"
        source_dir.mkdir(parents=True)
        (source_dir / "api.c").write_text(
            "\n".join(
                [
                    "int wrong_helper(void)",
                    "{",
                    "    return 0;",
                    "}",
                    "",
                    "static int",
                    "nbm_api(",
                    "    int flag,",
                    "    int mode)",
                    "{",
                    "    int ret = flag;",
                    "    return ret + mode;",
                    "}",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        scan.run(["git", "add", "."], repo)
        scan.run(["git", "commit", "-m", "initial"], repo)
        (source_dir / "api.c").write_text(
            "\n".join(
                [
                    "int wrong_helper(void)",
                    "{",
                    "    return 0;",
                    "}",
                    "",
                    "static int",
                    "nbm_api(",
                    "    int flag,",
                    "    int mode)",
                    "{",
                    "    int ret = flag + 1;",
                    "    return ret + mode;",
                    "}",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        scan.run(["git", "add", "."], repo)
        scan.run(["git", "commit", "-m", "multiline local change"], repo)
        return repo

    def _make_git_repo_with_heap_lifetime_change(self, tmp):
        repo = Path(tmp)
        scan.run(["git", "init"], repo)
        scan.run(["git", "config", "user.email", "test@test"], repo)
        scan.run(["git", "config", "user.name", "test"], repo)
        source_dir = repo / "fosip" / "nbm"
        source_dir.mkdir(parents=True)
        (source_dir / "session.c").write_text(
            "\n".join(
                [
                    "struct nbm_session { int id; };",
                    "int nbm_session_open(void)",
                    "{",
                    "    struct nbm_session *ctx = 0;",
                    "    return ctx != 0;",
                    "}",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        scan.run(["git", "add", "."], repo)
        scan.run(["git", "commit", "-m", "initial"], repo)
        (source_dir / "session.c").write_text(
            "\n".join(
                [
                    "struct nbm_session { int id; };",
                    "int nbm_session_open(void)",
                    "{",
                    "    struct nbm_session *ctx = malloc(sizeof(*ctx));",
                    "    list_add(&ctx->node, &g_sessions);",
                    "    return ctx != 0;",
                    "}",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        scan.run(["git", "add", "."], repo)
        scan.run(["git", "commit", "-m", "heap lifetime"], repo)
        return repo

    def test_step_discover_outputs_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._make_git_repo(tmp)
            out = repo / ".impact-scan"
            out.mkdir(parents=True)
            old_cwd = Path.cwd()
            try:
                import os
                os.chdir(str(repo))
                ret = scan.main(["--range", "HEAD~1..HEAD", "--out", ".impact-scan",
                                 "--step", "discover", "--codegraph-mode", "off"])

                self.assertEqual(0, ret)
                self.assertTrue((out / "scope_discovery.json").exists())
                discovery = json.loads((out / "scope_discovery.json").read_text(encoding="utf-8"))
                self.assertIn("changed_files", discovery)
            finally:
                os.chdir(str(old_cwd))

    def test_discover_resolves_leaf_subsystem_from_latest_changed_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._make_git_repo_with_leaf_subsystem_change(tmp)
            out = repo / ".impact-scan"
            old_cwd = Path.cwd()
            try:
                import os
                os.chdir(str(repo))
                ret = scan.main(["--range", "HEAD~1..HEAD", "--out", ".impact-scan",
                                 "--step", "discover", "--subsystem", "nbm",
                                 "--codegraph-mode", "off"])

                self.assertEqual(0, ret)
                discovery = json.loads((out / "scope_discovery.json").read_text(encoding="utf-8"))
                config = json.loads((out / "scan_config.json").read_text(encoding="utf-8"))
                self.assertEqual(["fosip/nbm/api.c"], discovery["changed_files"])
                self.assertEqual("nbm", discovery["requested_subsystem"])
                self.assertEqual("fosip/nbm", discovery["resolved_subsystem"])
                self.assertTrue(discovery["subsystem_auto_resolved"])
                self.assertEqual("fosip/nbm", config["scope_path"])
            finally:
                os.chdir(str(old_cwd))

    def test_discover_infers_full_subsystem_from_latest_changed_files_without_subsystem_arg(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._make_git_repo_with_leaf_subsystem_change(tmp)
            out = repo / ".impact-scan"
            old_cwd = Path.cwd()
            try:
                import os
                os.chdir(str(repo))
                ret = scan.main(["--range", "HEAD~1..HEAD", "--out", ".impact-scan",
                                 "--step", "discover", "--codegraph-mode", "off"])

                self.assertEqual(0, ret)
                discovery = json.loads((out / "scope_discovery.json").read_text(encoding="utf-8"))
                config = json.loads((out / "scan_config.json").read_text(encoding="utf-8"))
                self.assertEqual(["fosip/nbm/api.c"], discovery["changed_files"])
                self.assertEqual("", discovery["requested_subsystem"])
                self.assertEqual("fosip/nbm", discovery["resolved_subsystem"])
                self.assertTrue(discovery["subsystem_auto_resolved"])
                self.assertEqual("fosip/nbm", config["scope_path"])
            finally:
                os.chdir(str(old_cwd))

    def test_discover_reports_ambiguous_leaf_subsystem_without_guessing(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._make_git_repo_with_ambiguous_leaf_subsystem_change(tmp)
            out = repo / ".impact-scan"
            old_cwd = Path.cwd()
            try:
                import os
                os.chdir(str(repo))
                ret = scan.main(["--range", "HEAD~1..HEAD", "--out", ".impact-scan",
                                 "--step", "discover", "--subsystem", "nbm",
                                 "--codegraph-mode", "off"])

                self.assertEqual(0, ret)
                discovery = json.loads((out / "scope_discovery.json").read_text(encoding="utf-8"))
                self.assertEqual([], discovery["changed_files"])
                self.assertEqual("nbm", discovery["resolved_subsystem"])
                self.assertFalse(discovery["subsystem_auto_resolved"])
                self.assertEqual(["fosip/nbm", "product/nbm"], discovery["subsystem_resolution_candidates"])
            finally:
                os.chdir(str(old_cwd))

    def test_local_variable_change_expands_enclosing_function(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._make_git_repo_with_local_variable_change(tmp)
            config = scan.default_scan_config("fosip/nbm")

            symbols = scan.extract_symbols(repo, "HEAD~1..HEAD", 20, config)
            selected, reasons = scan.select_symbols_for_expansion(
                symbols,
                [scan.risk_item("nbm_api", "local-function-context", 8, ["local function context changed"], ["fosip/nbm/api.c"])],
                {"focus_symbols": []},
            )

        self.assertEqual(["nbm_api"], [symbol["name"] for symbol in symbols])
        self.assertEqual("local-function-context", symbols[0]["kind"])
        self.assertIn("ret = flag + 1", symbols[0]["evidence"])
        self.assertIn("nbm_api", selected)
        self.assertEqual("local change in enclosing function", reasons["nbm_api"])

    def test_local_change_in_multiline_function_uses_real_enclosing_function(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._make_git_repo_with_multiline_function_local_change(tmp)
            config = scan.default_scan_config("fosip/nbm")

            symbols = scan.extract_symbols(repo, "HEAD~1..HEAD", 20, config)

        self.assertEqual(["nbm_api"], [symbol["name"] for symbol in symbols])
        self.assertNotIn("wrong_helper", [symbol["name"] for symbol in symbols])
        self.assertEqual("local-function-context", symbols[0]["kind"])
        self.assertIn("ret = flag + 1", symbols[0]["evidence"])

    def test_function_boundary_allows_struct_parameters(self):
        lines = [
            "struct nbm_msg { int id; };",
            "static int nbm_api(struct nbm_msg *msg)",
            "{",
            "    int ret = msg->id;",
            "    return ret;",
            "}",
        ]

        self.assertEqual([(2, 6, "nbm_api")], scan.function_ranges(lines))

    def test_heap_lifetime_change_expands_enclosing_function_with_lifecycle_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._make_git_repo_with_heap_lifetime_change(tmp)
            config = scan.default_scan_config("fosip/nbm")

            symbols = scan.extract_symbols(repo, "HEAD~1..HEAD", 20, config)
            risks = scan.build_risk_items([], symbols, [], config)
            selected, reasons = scan.select_symbols_for_expansion(symbols, risks, {"focus_symbols": []})

        self.assertEqual(["nbm_session_open"], sorted(set(symbol["name"] for symbol in symbols)))
        self.assertTrue(any(symbol["kind"] == "memory-lifetime" for symbol in symbols))
        self.assertTrue(any("heap/object lifetime evidence" in symbol.get("evidence_role", "") for symbol in symbols))
        self.assertTrue(any("malloc" in symbol["evidence"] for symbol in symbols))
        self.assertTrue(any("list_add" in symbol["evidence"] for symbol in symbols))
        self.assertIn("nbm_session_open", selected)
        self.assertIn(reasons["nbm_session_open"], ["memory-lifetime symbol", "high-risk symbol (score >= 8)"])

    def test_report_uses_lifecycle_evidence_without_removed_review_section(self):
        config = scan.default_scan_config("fosip/nbm")
        risk = scan.risk_item(
            "nbm_session_open",
            "memory-lifetime",
            10,
            ["memory allocation/lifetime related change"],
            ["fosip/nbm/session.c"],
            ["memory_leak"],
        )

        text = scan.markdown_report(
            "HEAD~1..HEAD",
            scan.codegraph_status("off"),
            [],
            [],
            [],
            [risk],
            {"subsystems": []},
            config,
            [],
            scan.build_architecture_risk_summary([risk]),
            [],
        )

        self.assertNotIn("必须" + "人工 " + "Review", text)
        self.assertNotIn("Manual " + "Review 层", text)
        self.assertIn("生命周期风险证据", text)

    def test_discover_clears_previous_scan_artifacts_before_starting(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._make_git_repo(tmp)
            out = repo / ".impact-scan"
            out.mkdir(parents=True)
            stale = out / "risk_report.md"
            stale.write_text("stale report\n", encoding="utf-8")
            old_cwd = Path.cwd()
            try:
                import os
                os.chdir(str(repo))
                ret = scan.main(["--range", "HEAD~1..HEAD", "--out", ".impact-scan",
                                 "--step", "discover", "--codegraph-mode", "off"])

                self.assertEqual(0, ret)
                self.assertFalse(stale.exists())
                self.assertTrue((out / "scope_discovery.json").exists())
            finally:
                os.chdir(str(old_cwd))

    def test_later_guided_steps_do_not_clear_previous_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._make_git_repo(tmp)
            out = repo / ".impact-scan"
            out.mkdir(parents=True)
            marker = out / "scope_discovery.json"
            marker.write_text('{"marker": true}', encoding="utf-8")
            old_cwd = Path.cwd()
            try:
                import os
                os.chdir(str(repo))
                ret = scan.main(["--range", "HEAD~1..HEAD", "--out", ".impact-scan",
                                 "--step", "triage", "--codegraph-mode", "off"])

                self.assertEqual(0, ret)
                self.assertTrue(marker.exists())
            finally:
                os.chdir(str(old_cwd))

    def test_rejects_non_latest_commit_range(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._make_git_repo(tmp)
            old_cwd = Path.cwd()
            try:
                import os
                os.chdir(str(repo))
                ret = scan.main(["--range", "HEAD~2..HEAD", "--codegraph-mode", "off"])

                self.assertEqual(4, ret)
            finally:
                os.chdir(str(old_cwd))

    def test_step_triage_outputs_triage_summary_and_focus_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._make_git_repo(tmp)
            out = repo / ".impact-scan"
            out.mkdir(parents=True)
            old_cwd = Path.cwd()
            try:
                import os
                os.chdir(str(repo))
                ret = scan.main(["--range", "HEAD~1..HEAD", "--out", ".impact-scan",
                                 "--step", "triage", "--codegraph-mode", "off",
                                 "--focus-symbols", "main"])

                self.assertEqual(0, ret)
                self.assertTrue((out / "triage_summary.json").exists())
                triage = json.loads((out / "triage_summary.json").read_text(encoding="utf-8"))
                self.assertIn("focus_coverage", triage)
            finally:
                os.chdir(str(old_cwd))

    def test_step_expand_writes_deep_call_chain_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._make_git_repo_with_local_variable_change(tmp)
            out = repo / ".impact-scan"
            old_cwd = Path.cwd()
            try:
                import os
                os.chdir(str(repo))
                scan.main(["--range", "HEAD~1..HEAD", "--out", ".impact-scan",
                           "--step", "discover", "--codegraph-mode", "off"])
                scan.main(["--range", "HEAD~1..HEAD", "--out", ".impact-scan",
                           "--step", "triage", "--codegraph-mode", "off"])
                ret = scan.main(["--range", "HEAD~1..HEAD", "--out", ".impact-scan",
                                 "--step", "expand", "--codegraph-mode", "off"])

                self.assertEqual(0, ret)
                self.assertTrue((out / "call_chain_analysis.json").exists())
                self.assertTrue((out / "step3a_call_paths.json").exists())
                self.assertTrue((out / "step3b_business_entries.json").exists())
                self.assertTrue((out / "step3c_branch_points.json").exists())
                self.assertTrue((out / "step3d_state_flow.json").exists())
                self.assertTrue((out / "step3e_evidence_gaps.json").exists())
                self.assertTrue((out / "step3f_completion.json").exists())
                self.assertFalse((out / ("step3_callchain" + "_review.md")).exists())
                self.assertTrue((out / "workflow_state.json").exists())
                analysis = json.loads((out / "call_chain_analysis.json").read_text(encoding="utf-8"))
                summary = json.loads((out / "expansion_summary.json").read_text(encoding="utf-8"))
                completion = json.loads((out / "step3f_completion.json").read_text(encoding="utf-8"))
                state = json.loads((out / "workflow_state.json").read_text(encoding="utf-8"))
                self.assertEqual("deep-call-chain", analysis["mode"])
                self.assertIn("business_entry_group_count", summary)
                self.assertIn("branch_point_count", summary)
                self.assertFalse(completion["step3_complete"])
                self.assertIn("successful_call_chain_path", completion["missing_sections"])
                self.assertEqual("expand", state["next_required_step"])
            finally:
                os.chdir(str(old_cwd))

    def test_step_report_requires_step3_completion_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._make_git_repo_with_local_variable_change(tmp)
            out = repo / ".impact-scan"
            old_cwd = Path.cwd()
            try:
                import os
                os.chdir(str(repo))
                scan.main(["--range", "HEAD~1..HEAD", "--out", ".impact-scan",
                           "--step", "discover", "--codegraph-mode", "off"])
                scan.main(["--range", "HEAD~1..HEAD", "--out", ".impact-scan",
                           "--step", "triage", "--codegraph-mode", "off"])
                ret = scan.main(["--range", "HEAD~1..HEAD", "--out", ".impact-scan",
                                 "--step", "report", "--codegraph-mode", "off"])

                self.assertEqual(5, ret)
                self.assertFalse((out / "risk_report.md").exists())
            finally:
                os.chdir(str(old_cwd))

    def test_step_report_rejects_incomplete_step3_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._make_git_repo_with_local_variable_change(tmp)
            out = repo / ".impact-scan"
            old_cwd = Path.cwd()
            try:
                import os
                os.chdir(str(repo))
                scan.main(["--range", "HEAD~1..HEAD", "--out", ".impact-scan",
                           "--step", "discover", "--codegraph-mode", "off"])
                scan.main(["--range", "HEAD~1..HEAD", "--out", ".impact-scan",
                           "--step", "triage", "--codegraph-mode", "off"])
                scan.main(["--range", "HEAD~1..HEAD", "--out", ".impact-scan",
                           "--step", "expand", "--codegraph-mode", "off"])
                completion = out / "step3f_completion.json"
                data = json.loads(completion.read_text(encoding="utf-8"))
                data["step3_complete"] = False
                data["missing_sections"] = ["business_entry_analysis"]
                completion.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                ret = scan.main(["--range", "HEAD~1..HEAD", "--out", ".impact-scan",
                                 "--step", "report", "--codegraph-mode", "off"])

                self.assertEqual(5, ret)
                self.assertFalse((out / "risk_report.md").exists())
            finally:
                os.chdir(str(old_cwd))

    def test_step_report_includes_focus_coverage_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._make_git_repo(tmp)
            out = repo / ".impact-scan"
            out.mkdir(parents=True)
            old_cwd = Path.cwd()
            try:
                import os
                os.chdir(str(repo))
                # Run discover + triage first, then report
                scan.main(["--range", "HEAD~1..HEAD", "--out", ".impact-scan",
                           "--step", "discover", "--codegraph-mode", "off"])
                scan.main(["--range", "HEAD~1..HEAD", "--out", ".impact-scan",
                           "--step", "triage", "--codegraph-mode", "off"])
                scan.main(["--range", "HEAD~1..HEAD", "--out", ".impact-scan",
                           "--step", "expand", "--codegraph-mode", "off"])
                completion = out / "step3f_completion.json"
                data = json.loads(completion.read_text(encoding="utf-8"))
                data["step3_complete"] = True
                data["missing_sections"] = []
                completion.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                ret = scan.main(["--range", "HEAD~1..HEAD", "--out", ".impact-scan",
                                 "--step", "report", "--codegraph-mode", "off",
                                 "--focus-symbols", "main"])

                self.assertEqual(0, ret)
                self.assertTrue((out / "risk_report.md").exists())
                raw = (out / "risk_report.md").read_bytes()
                self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
                text = raw.decode("utf-8")
                self.assertIn("用户重点关注覆盖", text)
            finally:
                os.chdir(str(old_cwd))

    def test_one_shot_mode_still_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._make_git_repo(tmp)
            out = repo / ".impact-scan"
            old_cwd = Path.cwd()
            try:
                import os
                os.chdir(str(repo))
                ret = scan.main(["--codegraph-mode", "off"])
                self.assertEqual(0, ret)
                self.assertTrue(out.exists())
                md = out / "risk_report.md"
                self.assertTrue(md.exists(), "risk_report.md should exist after one-shot scan")
                text = md.read_bytes().decode("utf-8-sig")
                self.assertIn("C 回归影响扫描报告", text)
            finally:
                os.chdir(str(old_cwd))

    def test_skill_identity_and_guidance_match_ripple(self):
        skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        agent_text = (SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")

        self.assertIn("name: ripple", skill_text)
        self.assertIn("Interactive Guided", skill_text)
        self.assertIn("Default mode is interactive guided mode", skill_text)
        self.assertIn("stop and wait", skill_text)
        self.assertIn("Do not run Step 1 through Step 4 in one uninterrupted sequence", skill_text)
        self.assertNotIn("Evidence " + "review", skill_text)
        self.assertNotIn("Step " + "5", skill_text)
        self.assertIn("Deep call-chain analysis", skill_text)
        self.assertIn("business entry groups", skill_text)
        self.assertIn("branch points", skill_text)
        self.assertIn("top-level business entry or root caller", skill_text)
        self.assertIn("depth is only a CodeGraph search budget", skill_text)
        self.assertIn("step3f_completion.json", skill_text)
        self.assertNotIn("step3_callchain" + "_review.md", skill_text)
        self.assertIn("workflow_state.json", skill_text)
        self.assertIn("Success terminal conditions are only", skill_text)
        self.assertIn("Chinese", skill_text)
        self.assertIn("references/risk-rules.md", skill_text)
        self.assertIn("references/report-format.md", skill_text)
        self.assertLess(len(skill_text.splitlines()), 260)
        self.assertIn("display_name: Ripple", agent_text)
        self.assertIn("interactive guided", agent_text)
        self.assertIn("wait for confirmation", agent_text)
        self.assertNotIn("Ask for " + "focus first", agent_text)
        self.assertIn("infer scope from git changed files", agent_text)

    def test_skill_reference_files_exist(self):
        self.assertTrue((SKILL_ROOT / "references" / "risk-rules.md").exists())
        self.assertTrue((SKILL_ROOT / "references" / "report-format.md").exists())

    def test_removed_risk_categories_do_not_remain_in_skill_or_script(self):
        skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        script_text = SCRIPT.read_text(encoding="utf-8")
        combined = skill_text + "\n" + script_text
        removed_terms = [
            "ownership" + "_lifetime",
            "macro or " + "conditional",
            "conditional " + "compilation",
            "build/" + "feature",
        ]

        for term in removed_terms:
            self.assertNotIn(term, combined)

    def test_pointer_alias_lifetime_scores_high_and_reports_lifecycle_evidence(self):
        symbol = scan.changed_symbol(
            "register_cb",
            "core/session/session.c",
            "pointer-alias-lifetime",
            "register_cb(on_done, session); /* later delivered as void *opaque */",
        )

        score, reasons = scan.score_symbol(symbol, None, scan.default_scan_config())

        self.assertIn("pointer_alias_lifetime", symbol["risk_categories"])
        self.assertGreaterEqual(score, 8)
        self.assertTrue(any("opaque" in reason.lower() or "pointer alias" in reason.lower() for reason in reasons))

    def test_pointer_alias_report_section_is_present(self):
        config = scan.default_scan_config()
        symbol = scan.changed_symbol(
            "ctx",
            "core/session/session.c",
            "pointer-alias-lifetime",
            "owner->session = ctx;",
        )
        risk = scan.risk_item(
            symbol["name"],
            symbol["kind"],
            10,
            ["pointer alias/field ownership lifetime change"],
            [symbol["file"]],
            symbol["risk_categories"],
        )

        text = scan.markdown_report(
            "HEAD~1..HEAD",
            scan.codegraph_status("off"),
            [],
            [symbol],
            [],
            [risk],
            {"subsystems": []},
            config,
            [],
            scan.build_architecture_risk_summary([risk]),
            [],
        )

        self.assertIn("指针别名与生命周期关注点", text)
        self.assertIn("不要只按变量名", text)


if __name__ == "__main__":
    unittest.main()
