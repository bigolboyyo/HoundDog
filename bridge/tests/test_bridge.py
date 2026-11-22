import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from pathlib import Path
from unittest.mock import patch

import bridge
from fixtures import bar, bar_coverage, coverage, event, write_lines


class BridgeCliTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.config = root / "bridge" / "bridge.toml"
        self.config.parent.mkdir()
        self.config.write_text(
            '[inputs]\nhounddog_exports = "../HoundDog/exports"\nthetadesk_exports = "../market"\n\n'
            '[[symbols]]\nsymbol = "aapl"\n',
            encoding="utf-8",
        )
        write_lines(root / "HoundDog" / "exports" / "hounddog-2026-11-16.jsonl", [
            coverage(1, "2026-11-16 15:00", ["AAPL"]), event(1, "2026-11-16 15:00", "https://x/mon", ["AAPL"]),
        ])
        write_lines(root / "market" / "theta-bars-2026-11-22.jsonl",
                    [bar("AAPL", date(2026, 11, 13), 100.0), bar("AAPL", date(2026, 11, 16), 105.0)])
        write_lines(root / "market" / "theta-coverage-2026-11-22.jsonl",
                    [bar_coverage("AAPL", date(2026, 11, 13), date(2026, 11, 16))])

    def run_cli(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = bridge.main([*args, "--config", str(self.config)])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_report_json_is_the_study_for_each_symbol(self):
        code, out, _ = self.run_cli("report", "--json")

        [study] = json.loads(out)["symbols"]
        self.assertEqual(code, 0)
        self.assertEqual((study["symbol"], study["topics"]), ("AAPL", ["AAPL"]), "topics default to the ticker")
        self.assertEqual(study["news"]["sessions"], 1)
        self.assertAlmostEqual(study["news"]["mean_abs_change"], 0.05)
        self.assertEqual(study["events"][0]["session"], "2026-11-16")

    def test_report_text(self):
        code, out, _ = self.run_cli("report")

        self.assertEqual(code, 0)
        self.assertIn("news sessions", out)
        self.assertIn("5.00%", out)
        self.assertIn("Only 1 news session(s)", out)

    def test_status_counts_what_each_folder_holds(self):
        code, out, _ = self.run_cli("status", "--json")

        result = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual((result["hounddog"]["events"], result["hounddog"]["topics_watched"]), (1, ["AAPL"]))
        self.assertEqual(result["thetadesk"]["symbols"], [
            {"symbol": "AAPL", "bars": 2, "first": "2026-11-13", "last": "2026-11-16"},
        ])

    def test_a_missing_config_is_a_clear_error(self):
        self.config.unlink()

        code, _, err = self.run_cli("report")

        self.assertEqual(code, bridge.EXIT_CONFIG)
        self.assertIn("config not found", err)

    def test_thetadesk_defaults_to_its_shared_store(self):
        self.config.write_text('[[symbols]]\nsymbol = "AAPL"\n', encoding="utf-8")
        with patch.dict("os.environ", {"LOCALAPPDATA": "C:/Users/me/AppData/Local"}):
            config = bridge.BridgeConfig.load(self.config)

        self.assertEqual(config.thetadesk_exports, Path("C:/Users/me/AppData/Local") / "ThetaDesk" / "exports")
        self.assertEqual(config.hounddog_exports, (self.config.parent / "../HoundDog/exports").resolve())


if __name__ == "__main__":
    unittest.main()
