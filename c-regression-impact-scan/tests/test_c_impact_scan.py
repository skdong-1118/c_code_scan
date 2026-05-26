import importlib.util
import codecs
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
                        "legacy_paths:",
                        "  - legacy/",
                        "high_risk_paths:",
                        "  - platform/",
                    ]
                ),
                encoding="utf-8",
            )

            config = scan.load_scan_config(repo, "subsys/net")

        self.assertEqual("subsys/net", config["scope_path"])
        self.assertIn("subsys/net/legacy/", config["legacy_paths"])
        self.assertIn("subsys/net/platform/", config["high_risk_paths"])

    def test_subsystem_scope_filters_changed_files(self):
        config = scan.default_scan_config("subsys/net")
        files = [
            scan.changed_file("subsys/net/include/api.h", "M"),
            scan.changed_file("subsys/storage/include/api.h", "M"),
        ]

        scoped = scan.filter_files_by_scope(files, config)

        self.assertEqual(["subsys/net/include/api.h"], [item["path"] for item in scoped])

    def test_config_marks_legacy_and_high_risk_files(self):
        config = scan.default_scan_config()
        config["legacy_paths"].append("legacy/http/")
        config["high_risk_paths"].append("platform/")

        legacy_file = scan.changed_file("legacy/http/client.c", "M")
        platform_file = scan.changed_file("platform/os/mem.c", "M")

        scan.apply_config_to_file(legacy_file, config)
        scan.apply_config_to_file(platform_file, config)

        self.assertTrue(legacy_file["is_legacy_path"])
        self.assertTrue(platform_file["is_high_risk_path"])

    def test_legacy_reference_increases_symbol_risk(self):
        config = scan.default_scan_config()
        config["legacy_paths"].append("legacy/http/")
        symbol = scan.changed_symbol(
            "api_open",
            "common/api/session.h",
            "changed-token",
            "api_open(ctx);",
        )
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
                "changed-token",
                12,
                ["referenced by 1 legacy feature files"],
                ["subsys/net/include/api.h", "subsys/net/legacy/client.c"],
                [],
            )
        ]
        impact_paths = scan.build_impact_paths(refs, config)

        analysis = scan.build_subsystem_analysis(files, refs, risks, impact_paths, config)

        self.assertEqual("subsys/net", analysis[0]["name"])
        self.assertIn("subsys/net/include/api.h", analysis[0]["changed_files"])
        self.assertIn("subsys/net/legacy/client.c", analysis[0]["referenced_files"])
        self.assertIn("api_open", analysis[0]["symbols"])
        self.assertTrue(analysis[0]["legacy_hit"])
        self.assertTrue(any("direct changed file" in reason for reason in analysis[0]["why_impacted"]))
        self.assertTrue(any("legacy tests" in check for check in analysis[0]["suggested_checks"]))

    def test_removed_c_risk_checks_do_not_score(self):
        config = scan.default_scan_config()
        public_header = scan.changed_file("include/api.h", "M")
        build_file = scan.changed_file("CMakeLists.txt", "M")
        scan.apply_config_to_file(public_header, config)
        scan.apply_config_to_file(build_file, config)

        self.assertEqual((0, []), scan.score_file(public_header))
        self.assertEqual((0, []), scan.score_file(build_file))

        function_symbol = scan.changed_symbol("api_open", "include/api.h", "function", "int api_open(void);")
        type_symbol = scan.changed_symbol("api_msg", "include/api.h", "type", "struct api_msg { int code; };")
        semantic_symbol = scan.changed_symbol("api_check", "src/api.c", "function", "ret = NULL; size = 0; lock = 1;")
        memory_symbol = scan.changed_symbol("malloc", "src/api.c", "memory-lifetime", "ctx = malloc(sizeof(*ctx));")
        macro_symbol = scan.changed_symbol("CONFIG_X", "src/api.c", "macro-or-conditional", "#ifdef CONFIG_X")
        callback_symbol = scan.changed_symbol("handler", "src/api.c", "callback-or-function-pointer", "ops->open = handler;")

        for symbol in (function_symbol, type_symbol, semantic_symbol, memory_symbol, macro_symbol, callback_symbol):
            score, reasons = scan.score_symbol(symbol, None, config)
            self.assertEqual(0, score)
            self.assertEqual([], reasons)

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

    def test_broad_cross_subsystem_reference_increases_flow_score_and_review(self):
        config = scan.default_scan_config("subsys/net")
        symbol = scan.changed_symbol("route_order", "subsys/net/protocol/router.c", "changed-token", "route_order(ctx);")
        refs = scan.reference_result(
            "route_order",
            "codegraph",
            [
                "subsys/net/legacy/client.c",
                "subsys/net/service/a.c",
                "subsys/storage/service/b.c",
                "subsys/order/service/c.c",
            ],
            config,
        )

        score, reasons = scan.score_symbol(symbol, refs, config)
        review = scan.manual_review_items([scan.risk_item("parse_packet", "function", score, reasons, ["subsys/net/protocol/parser.c"])])

        self.assertGreaterEqual(score, 8)
        self.assertTrue(any("legacy feature" in reason for reason in reasons))
        self.assertTrue(any("subsystems" in reason for reason in reasons))
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


if __name__ == "__main__":
    unittest.main()
