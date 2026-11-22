import json
import tempfile
import threading
import tomllib
import unittest
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import uvicorn
from fastapi.testclient import TestClient

from config import BridgeConfig, ConfigError, read_raw, render_raw
from fixtures import bar, bar_coverage, coverage, event, write_lines
from hounddog_client import HoundDogClient, HoundDogRefused, HoundDogUnavailable, TopicResult
from server import ServerStop, create_app

LOCAL = "http://127.0.0.1:8090"


class FakeHoundDog:
    """Stands in for HoundDogClient: remembers topics, can be down, can refuse."""

    def __init__(self, topics=(), down=False, refuse=()):
        self.topics = {name: ["kept"] for name in topics}
        self.down = down
        self.refuse = set(refuse)

    def __call__(self, base_url):
        self.base_url = base_url
        return self

    def topic_names(self):
        if self.down:
            raise HoundDogUnavailable("HoundDog is not reachable")
        return list(self.topics)

    def add_topic(self, name, keywords):
        if self.down:
            raise HoundDogUnavailable("HoundDog is not reachable")
        if name in self.refuse:
            raise HoundDogRefused("Include keywords cannot be empty", 400)
        if name in self.topics:
            return TopicResult(name, created=False)
        self.topics[name] = keywords
        return TopicResult(name, created=True)


class ServerTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.config = root / "bridge" / "bridge.toml"
        self.config.parent.mkdir()
        self.config.write_text(
            '[inputs]\nhounddog_exports = "../HoundDog/exports"\nthetadesk_exports = "../market"\n\n'
            '[hounddog]\nurl = "http://127.0.0.1:8080"\n\n'
            '[[symbols]]\nsymbol = "AAPL"\ntopics = ["AAPL"]\n',
            encoding="utf-8",
        )
        write_lines(root / "HoundDog" / "exports" / "hounddog-2026-11-16.jsonl", [
            coverage(1, "2026-11-16 15:00", ["AAPL"]), event(1, "2026-11-16 15:00", "https://x/mon", ["AAPL"]),
        ])
        write_lines(root / "market" / "theta-bars-2026-11-22.jsonl", [
            bar("AAPL", date(2026, 11, 13), 100.0), bar("AAPL", date(2026, 11, 16), 105.0),
            bar("NVDA", date(2026, 11, 13), 50.0), bar("NVDA", date(2026, 11, 16), 50.0),
        ])
        write_lines(root / "market" / "theta-coverage-2026-11-22.jsonl", [
            bar_coverage("AAPL", date(2026, 11, 13), date(2026, 11, 16)),
            bar_coverage("NVDA", date(2026, 11, 13), date(2026, 11, 16)),
        ])
        self.hounddog = FakeHoundDog(topics=["AAPL", "Breaking"])

    def client(self):
        return TestClient(create_app(self.config, self.hounddog), base_url=LOCAL)

    def watch(self, body, **headers):
        return self.client().post("/api/watch", json=body, headers=headers)

    def test_overview_has_both_sources_the_study_and_hounddog_topics(self):
        response = self.client().get("/api/overview")

        data = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual([s["symbol"] for s in data["status"]["thetadesk"]["symbols"]], ["AAPL", "NVDA"])
        self.assertEqual(data["report"]["symbols"][0]["news"]["sessions"], 1)
        self.assertEqual(data["report"]["symbols"][0]["sessions"][0]["kind"], "news")
        self.assertEqual(data["hounddog"], {
            "url": "http://127.0.0.1:8080", "enabled": True, "reachable": True,
            "topics": ["AAPL", "Breaking"], "error": "",
        })
        self.assertEqual(data["display"], {"banner": ""})

    def test_overview_still_works_while_hounddog_is_down(self):
        self.hounddog.down = True

        data = self.client().get("/api/overview").json()

        self.assertFalse(data["hounddog"]["reachable"])
        self.assertIsNone(data["hounddog"]["topics"])
        self.assertEqual(data["report"]["symbols"][0]["symbol"], "AAPL")

    def test_watching_a_group_creates_one_topic_per_ticker_and_records_the_group(self):
        response = self.watch({
            "tickers": [{"symbol": "nvda", "keywords": ["Nvidia", " "]}, {"symbol": "AAPL", "keywords": ["Apple"]}],
            "group": " Tech Bros ",
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual([(r["symbol"], r["status"]) for r in response.json()["results"]],
                         [("NVDA", "created"), ("AAPL", "existing")])
        self.assertEqual(self.hounddog.topics["NVDA"], ["Nvidia"])
        self.assertEqual(self.hounddog.topics["AAPL"], ["kept"], "an existing topic is left alone")
        config = BridgeConfig.load(self.config)
        self.assertEqual([(s.symbol, s.topics) for s in config.symbols], [("AAPL", ("AAPL",)), ("NVDA", ("NVDA",))])
        self.assertEqual([(g.name, g.symbols) for g in config.groups], [("Tech Bros", ("NVDA", "AAPL"))])

    def test_adding_to_an_existing_group_keeps_its_members(self):
        self.watch({"tickers": [{"symbol": "NVDA", "keywords": ["Nvidia"]}], "group": "Tech Bros"})
        self.watch({"tickers": [{"symbol": "MSFT", "keywords": ["Microsoft"]}, {"symbol": "NVDA", "keywords": ["x"]}],
                    "group": "Tech Bros"})

        [group] = BridgeConfig.load(self.config).groups
        self.assertEqual(group.symbols, ("NVDA", "MSFT"))

    def test_nothing_is_written_while_hounddog_is_down(self):
        before = self.config.read_text(encoding="utf-8")
        self.hounddog.down = True

        response = self.watch({"tickers": [{"symbol": "NVDA", "keywords": ["Nvidia"]}]})

        self.assertEqual(response.status_code, 502)
        self.assertIn("not reachable", response.json()["detail"])
        self.assertEqual(self.config.read_text(encoding="utf-8"), before)

    def test_a_refused_ticker_is_reported_and_the_rest_are_added(self):
        self.hounddog.refuse = {"MSFT"}

        response = self.watch({"tickers": [{"symbol": "MSFT", "keywords": ["Microsoft"]},
                                           {"symbol": "NVDA", "keywords": ["Nvidia"]}]})

        self.assertEqual([(r["symbol"], r["status"]) for r in response.json()["results"]],
                         [("MSFT", "failed"), ("NVDA", "created")])
        self.assertEqual([s.symbol for s in BridgeConfig.load(self.config).symbols], ["AAPL", "NVDA"])

    def test_invalid_requests_are_refused_without_calling_hounddog(self):
        cases = [
            {"tickers": [{"symbol": "NOT A TICKER", "keywords": ["x"]}]},
            {"tickers": [{"symbol": "NVDA", "keywords": [" ", "*"]}]},
            {"tickers": [{"symbol": "NVDA", "keywords": []}]},
            {"tickers": []},
        ]
        for body in cases:
            with self.subTest(body=body):
                self.assertEqual(self.watch(body).status_code, 422)
        self.assertNotIn("NVDA", self.hounddog.topics)

    def test_requests_from_other_sites_are_refused(self):
        cross_site = self.watch({"tickers": [{"symbol": "NVDA", "keywords": ["Nvidia"]}]},
                                origin="https://attacker.example")
        rebound = TestClient(create_app(self.config, self.hounddog), base_url="http://attacker.example:8090")

        self.assertEqual(cross_site.status_code, 403)
        self.assertEqual(rebound.get("/api/overview").status_code, 400)
        self.assertNotIn("NVDA", self.hounddog.topics)

    def test_shut_down_stops_the_server_it_was_started_with(self):
        stop = ServerStop()
        server = uvicorn.Server(uvicorn.Config(create_app(self.config, self.hounddog, server_stop=stop)))
        stop.attach(server)
        client = TestClient(create_app(self.config, self.hounddog, server_stop=stop), base_url=LOCAL)

        refused = client.post("/api/shutdown", headers={"origin": "https://attacker.example"})
        self.assertEqual(refused.status_code, 403)
        self.assertFalse(server.should_exit)

        accepted = client.post("/api/shutdown", headers={"origin": LOCAL})
        self.assertEqual(accepted.status_code, 202)
        self.assertEqual(accepted.json(), {"stopping": True})
        self.assertTrue(server.should_exit)

    def test_shut_down_says_how_to_stop_a_server_started_another_way(self):
        response = self.client().post("/api/shutdown")

        self.assertEqual(response.status_code, 409)
        self.assertIn("Ctrl+C", response.json()["detail"])

    def test_the_page_and_its_assets_are_served(self):
        client = self.client()

        page = client.get("/").text
        self.assertIn("theta_hound bridge", page)
        self.assertRegex(page, r'src="/app\.js\?v=[0-9a-f]{16}"')
        self.assertRegex(page, r'href="/styles\.css\?v=[0-9a-f]{16}"')
        self.assertEqual(client.get("/app.js").status_code, 200)
        self.assertEqual(client.get("/styles.css").status_code, 200)


class ConfigWritingTests(unittest.TestCase):
    def test_written_config_reads_back_the_same(self):
        raw = {
            "inputs": {"hounddog_exports": "C:\\Data\\HoundDog\\exports", "thetadesk_exports": ""},
            "hounddog": {"url": "http://127.0.0.1:8080"},
            "symbols": [{"symbol": "AAPL", "topics": ["AAPL", 'Apple "Inc"']}],
            "groups": [{"name": "Tech Bros", "symbols": ["AAPL"]}],
        }

        text = render_raw(raw)

        self.assertEqual(tomllib.loads(text), raw)
        self.assertTrue(text.startswith("# theta_hound bridge settings"))

    def test_rewriting_keeps_tables_and_values_it_does_not_manage(self):
        raw = {
            "inputs": {"hounddog_exports": "../HoundDog/exports"},
            "notes": {"owner": "me", "reviewed": True, "version": 2},
            "symbols": [{"symbol": "AAPL", "topics": ["AAPL"]}],
        }

        self.assertEqual(tomllib.loads(render_raw(raw)), raw)

    def test_a_ticker_listed_twice_is_an_error_and_group_repeats_count_once(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bridge.toml"
            path.write_text('[[symbols]]\nsymbol = "AAPL"\n\n[[symbols]]\nsymbol = "aapl"\n', encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "AAPL is listed twice"):
                BridgeConfig.load(path)
            path.write_text('[[groups]]\nname = "G"\nsymbols = ["AAPL", "aapl", "MSFT"]\n', encoding="utf-8")
            self.assertEqual(BridgeConfig.load(path).groups[0].symbols, ("AAPL", "MSFT"))

    def test_the_shipped_config_loads(self):
        # bridge.toml is the user's own: the dashboard adds tickers to it, so only
        # check that it loads, not what it lists.
        config = BridgeConfig.load(Path(__file__).resolve().parents[1] / "bridge.toml")

        self.assertTrue(config.symbols)
        self.assertTrue(read_raw(Path(__file__).resolve().parents[1] / "bridge.toml")["inputs"])


class StubHoundDogHandler(BaseHTTPRequestHandler):
    """Answers like HoundDog's server: a dashboard with topics, 409 for a duplicate name."""

    topics = ["Breaking"]

    def do_GET(self):
        self.reply(200, {"topics": [{"name": name} for name in self.topics]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if body["name"] in self.topics:
            # Reworded on purpose: the client must go by the status, not the text.
            self.reply(409, {"error": "That topic already exists"})
        elif not body["keywords"]:
            self.reply(400, {"error": "Add at least one include keyword"})
        else:
            self.reply(201, body)

    def reply(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class HoundDogClientTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), StubHoundDogHandler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.client = HoundDogClient(f"http://127.0.0.1:{self.server.server_address[1]}/")

    def test_topics_are_listed_created_and_duplicates_are_left_alone(self):
        self.assertEqual(self.client.topic_names(), ["Breaking"])
        self.assertEqual(self.client.add_topic("NVDA", ["Nvidia"]), TopicResult("NVDA", created=True))
        self.assertEqual(self.client.add_topic("Breaking", ["x"]), TopicResult("Breaking", created=False))

    def test_a_refusal_carries_hounddogs_reason(self):
        with self.assertRaisesRegex(HoundDogRefused, "Add at least one include keyword"):
            self.client.add_topic("NVDA", [])

    def test_a_stopped_hounddog_is_unavailable(self):
        port = self.server.server_address[1]
        self.server.shutdown()
        self.server.server_close()

        with self.assertRaisesRegex(HoundDogUnavailable, "Start HoundDog"):
            HoundDogClient(f"http://127.0.0.1:{port}").topic_names()


if __name__ == "__main__":
    unittest.main()
