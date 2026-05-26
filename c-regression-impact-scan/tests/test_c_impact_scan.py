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


if __name__ == "__main__":
    unittest.main()
