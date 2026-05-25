import importlib.util
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


if __name__ == "__main__":
    unittest.main()
