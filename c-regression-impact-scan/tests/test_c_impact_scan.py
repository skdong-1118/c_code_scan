import importlib.util
import codecs
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "c_impact_scan.py"
SPEC = importlib.util.spec_from_file_location("c_impact_scan", str(SCRIPT))
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
        self.assertIn("ownership_lifetime", categories)
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
        codegraph = scan.codegraph_status("prefer")
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
        self.assertIn("Manual Review 层", report)
        self.assertIn("人工排查", report)

    def test_detects_architecture_risk_categories_from_c_evidence(self):
        cases = {
            "memory_safety": "memcpy(dst, src, len + 1);",
            "memory_leak": "ctx = malloc(sizeof(*ctx)); return -1;",
            "abi_layout": "struct api_msg { int version; long size; };",
            "concurrency": "pthread_mutex_unlock(&ctx->lock);",
            "error_handling": "if (!ctx) return ERR_INVALID;",
            "ownership_lifetime": "refcount_dec(&obj->refcnt); release(obj);",
            "macro_config": "#ifdef CONFIG_FEATURE_X",
            "protocol_compatibility": "msg->version = PROTOCOL_V2; opcode = CMD_OPEN;",
            "state_machine_timing": "state = STATE_RETRY; timer_start(t, timeout);",
            "callback_dispatch": "ops->open = handler; register_callback(cb);",
            "performance_resource": "while (retry--) { socket_fd = open(path); }",
            "security_boundary": "if (!auth_check(token)) return PERMISSION_DENIED;",
            "build_deploy": "target_link_libraries(foo bar)",
        }

        for expected, evidence in cases.items():
            categories = scan.detect_risk_categories(evidence, "subsys/net/api.c", "function")
            self.assertIn(expected, categories, evidence)

    def test_architecture_categories_increase_score_and_review(self):
        config = scan.default_scan_config("subsys/net")
        symbol = scan.changed_symbol(
            "parse_packet",
            "subsys/net/protocol/parser.c",
            "function",
            "memcpy(buf, pkt->payload, pkt->len); if (!auth_check(token)) return ERR_DENIED;",
        )

        score, reasons = scan.score_symbol(symbol, None, config)
        review = scan.manual_review_items([scan.risk_item("parse_packet", "function", score, reasons, ["subsys/net/protocol/parser.c"])])

        self.assertGreaterEqual(score, 8)
        self.assertTrue(any("memory_safety" in reason for reason in reasons))
        self.assertTrue(any("security_boundary" in reason for reason in reasons))
        self.assertEqual("parse_packet", review[0]["subject"])

    def test_decodes_utf8_subprocess_output_without_gbk_locale(self):
        raw = "中文路径/模块.c -> €\n".encode("utf-8")

        decoded = scan.decode_process_output(raw)

        self.assertIn("中文路径/模块.c", decoded)
        self.assertIn("€", decoded)

    def test_markdown_report_is_written_with_utf8_bom_for_windows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "risk_report.md"

            scan.write_markdown_report(path, "# 中文报告\n")

            raw = path.read_bytes()
        self.assertTrue(raw.startswith(codecs.BOM_UTF8))
        self.assertEqual("# 中文报告\n", raw.decode("utf-8-sig"))


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
                    "focus_risks:",
                    "  - memory_leak",
                    "  - abi_layout",
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
        self.assertIn("memory_leak", focus["focus_risks"])
        self.assertIn("abi_layout", focus["focus_risks"])
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
                cli_focus_risks="concurrency",
                cli_ignore_paths="vendor/,third_party/",
            )

        self.assertEqual(["my_func", "other_func"], focus["focus_symbols"])
        self.assertEqual(["concurrency"], focus["focus_risks"])
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
        focus = {"focus_symbols": ["api_open"], "focus_risks": [], "ignore_paths": [], "notes": []}

        selected, reasons = scan.select_symbols_for_expansion(symbols, risks, focus)

        self.assertIn("api_open", selected)
        self.assertIn("session_alloc", selected)
        self.assertNotIn("helper", selected)
        self.assertIn("user-specified focus symbol", reasons["api_open"])
        self.assertIn("memory-lifetime", reasons["session_alloc"])

    def test_ignore_paths_filter_removes_matching_items(self):
        focus = {"focus_symbols": [], "focus_risks": [], "ignore_paths": ["tests/", "docs/"], "notes": []}
        items = [
            {"path": "tests/test_foo.c"},
            {"path": "docs/readme.md"},
            {"path": "src/main.c"},
        ]

        filtered = scan.filter_ignored_paths(items, focus)

        self.assertEqual(1, len(filtered))
        self.assertEqual("src/main.c", filtered[0]["path"])

    def test_focus_ignore_filters_symbols_risks_and_reference_files(self):
        focus = {"focus_symbols": [], "focus_risks": [], "ignore_paths": ["tests/", "docs/"], "notes": []}
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
            scan.reference_result("api_open", "rg", ["tests/api_test.c", "src/client.c"], config),
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
                                 "--focus-symbols", "main",
                                 "--focus-risks", "memory_leak"])

                self.assertEqual(0, ret)
                self.assertTrue((out / "triage_summary.json").exists())
                triage = json.loads((out / "triage_summary.json").read_text(encoding="utf-8"))
                self.assertIn("focus_coverage", triage)
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
                ret = scan.main(["--range", "HEAD~1..HEAD", "--out", ".impact-scan",
                                 "--step", "report", "--codegraph-mode", "off",
                                 "--focus-symbols", "main",
                                 "--focus-risks", "abi_layout"])

                self.assertEqual(0, ret)
                self.assertTrue((out / "risk_report.md").exists())
                raw = (out / "risk_report.md").read_bytes()
                self.assertTrue(raw.startswith(codecs.BOM_UTF8))
                text = raw.decode("utf-8-sig")
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


if __name__ == "__main__":
    unittest.main()
