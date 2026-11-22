import http.client
import io
import json
import os
import sqlite3
from contextlib import closing, redirect_stderr, redirect_stdout
import tempfile
import threading
import unittest
from http import HTTPStatus
from pathlib import Path
from unittest.mock import patch

import scheduled_task
import watcher
import watcher_server
from test_scheduled_task import FakePowerShell


CONFIG = """\
[[sources]]
name = "Example"
url = "https://example.com/feed.xml"

[[topics]]
name = "AI tooling"
keywords = ["agent*"]
"""


class ServerTestCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.config_path = Path(directory.name) / "watch.toml"
        self.config_path.write_text(CONFIG, encoding="utf-8")
        for patcher in (
            patch.object(watcher_server, "CONFIG_PATH", self.config_path),
            patch.object(watcher_server, "DB_PATH", Path(directory.name) / "watcher.db"),
            patch.object(watcher_server.DashboardHandler, "log_message", lambda *args: None),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

        self.server = watcher_server.DashboardServer(("127.0.0.1", 0))
        self.serve_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.serve_thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.port = self.server.server_address[1]

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        self.addCleanup(connection.close)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        return response, response.read()

    def json_request(self, method, path, payload):
        return self.request(method, path, body=json.dumps(payload), headers={"Content-Type": "application/json"})

    def post_feed(self, payload, headers=None):
        return self.request(
            "POST",
            "/api/feeds",
            body=json.dumps(payload),
            headers={"Content-Type": "application/json", **(headers or {})},
        )


class DashboardServerSecurityTests(ServerTestCase):
    def test_only_dashboard_assets_are_served(self):
        for path in ("/watcher.db", "/watch.toml", "/.git/config", "/watcher.py", "/../watch.toml"):
            with self.subTest(path=path):
                response, _ = self.request("GET", path)
                self.assertEqual(response.status, 404)

        response, _ = self.request("GET", "/app.js")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader("Content-Type"), "text/javascript; charset=utf-8")
        self.assertEqual(response.getheader("X-Content-Type-Options"), "nosniff")
        self.assertIn("frame-ancestors 'none'", response.getheader("Content-Security-Policy"))

    def test_unknown_host_header_is_refused(self):
        response, _ = self.request("GET", "/api/dashboard", headers={"Host": "rebind.example:8080"})
        self.assertEqual(response.status, 403)

    def test_cross_origin_writes_are_refused(self):
        response, _ = self.post_feed(
            {"name": "Evil", "url": "https://evil.example/feed"},
            headers={"Origin": "https://evil.example"},
        )
        self.assertEqual(response.status, 403)
        self.assertEqual(self.config_path.read_text(encoding="utf-8"), CONFIG)

    def test_writes_require_json_content_type(self):
        response, _ = self.request(
            "POST",
            "/api/feeds",
            body=json.dumps({"name": "Plain", "url": "https://example.org/feed"}),
            headers={"Content-Type": "text/plain"},
        )
        self.assertEqual(response.status, 415)
        self.assertEqual(self.config_path.read_text(encoding="utf-8"), CONFIG)

    def test_oversized_and_negative_bodies_are_refused(self):
        for length in (str(watcher_server.MAX_BODY_BYTES + 1), "-1"):
            with self.subTest(length=length):
                response, _ = self.request(
                    "POST",
                    "/api/check",
                    body=b"",
                    headers={"Content-Type": "application/json", "Content-Length": length},
                )
                self.assertEqual(response.status, 400)

    def test_control_characters_and_invalid_unicode_are_refused(self):
        for name in ("Bad\x1b[2J", "Bad\ud800"):
            with self.subTest(name=repr(name)):
                response, _ = self.post_feed({"name": name, "url": "https://example.org/feed"})
                self.assertEqual(response.status, 400)
        self.assertEqual(self.config_path.read_text(encoding="utf-8"), CONFIG)

    def test_dashboard_returns_full_history(self):
        store = watcher.SeenStore(watcher_server.DB_PATH)
        try:
            store.mark_seen(
                watcher.Match("T", watcher.Item("S", "", f"https://example.com/{index}", "", ""), ())
                for index in range(250)
            )
        finally:
            store.close()

        response, body = self.request("GET", "/api/dashboard")
        payload = json.loads(body)
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["seen_count"], 250)
        self.assertEqual(len(payload["seen_items"]), 250)

    def test_same_origin_write_succeeds(self):
        response, _ = self.post_feed(
            {"name": "Second", "url": "https://example.org/feed"},
            headers={"Origin": f"http://127.0.0.1:{self.port}"},
        )
        self.assertEqual(response.status, 201)
        self.assertIn('url = "https://example.org/feed"', self.config_path.read_text(encoding="utf-8"))
        self.assertFalse(self.config_path.with_name("watch.toml.tmp").exists())


class ShutdownTests(ServerTestCase):
    def shutdown(self, headers=None):
        return self.request(
            "POST", "/api/shutdown", body="{}", headers={"Content-Type": "application/json", **(headers or {})}
        )

    def test_shutdown_stops_serving(self):
        response, body = self.shutdown({"Origin": f"http://127.0.0.1:{self.port}"})

        self.assertEqual(response.status, 202)
        self.assertEqual(json.loads(body), {"stopping": True})
        self.serve_thread.join(timeout=5)
        self.assertFalse(self.serve_thread.is_alive())

    def test_cross_origin_shutdown_is_refused(self):
        response, _ = self.shutdown({"Origin": "https://example.com"})

        self.assertEqual(response.status, 403)
        self.assertTrue(self.serve_thread.is_alive())
        response, _ = self.request("GET", "/api/dashboard")
        self.assertEqual(response.status, 200)

    def test_closing_waits_for_requests_in_progress(self):
        started, release = threading.Event(), threading.Event()

        def slow_get(handler):
            started.set()
            release.wait(5)
            handler.send_json(HTTPStatus.OK, {"finished": True})

        with patch.object(watcher_server.DashboardHandler, "do_GET", slow_get):
            slow = {}
            client = threading.Thread(target=lambda: slow.update(zip(("response", "body"), self.request("GET", "/"))))
            client.start()
            self.assertTrue(started.wait(5))
            self.shutdown()
            self.serve_thread.join(timeout=5)
            closer = threading.Thread(target=self.server.server_close)
            closer.start()
            closer.join(timeout=0.3)
            self.assertTrue(closer.is_alive(), "server_close returned while a request was still running")
            release.set()
            closer.join(timeout=5)
            client.join(timeout=5)

        self.assertFalse(closer.is_alive())
        self.assertEqual(slow["response"].status, 200)
        self.assertEqual(json.loads(slow["body"]), {"finished": True})


class ConfigSafetyTests(ServerTestCase):
    def test_malformed_sources_are_an_error_not_silently_dropped(self):
        # [sources] instead of [[sources]] is an easy hand-editing mistake.
        broken = CONFIG.replace("[[sources]]", "[sources]")
        self.config_path.write_text(broken, encoding="utf-8")
        response, body = self.request("GET", "/api/dashboard")
        self.assertEqual(response.status, 500)
        self.assertIn("'sources' must be an array of tables", json.loads(body)["error"])

        response, _ = self.request(
            "POST", "/api/topics",
            body=json.dumps({"name": "New", "keywords": ["x"]}),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status, 400)
        self.assertEqual(self.config_path.read_text(encoding="utf-8"), broken)

    def test_duplicate_keywords_are_saved_once(self):
        response, body = self.request(
            "POST", "/api/topics",
            body=json.dumps({"name": "New", "keywords": ["AI", "agents", "ai"], "exclude": ["Spam", "spam"]}),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status, 201, body)
        self.assertEqual(json.loads(body), {"name": "New", "keywords": ["AI", "agents"], "exclude": ["Spam"]})


class StartupTests(ServerTestCase):
    def test_second_server_on_the_same_port_fails_loudly(self):
        with patch("sys.argv", ["watcher_server.py", "--port", str(self.port)]):
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(watcher_server.main(), 1)
        self.assertIn("Another HoundDog server is probably still running", output.getvalue())

    def test_windows_binds_the_port_exclusively(self):
        self.assertEqual(watcher_server.DashboardServer.allow_reuse_address, os.name != "nt")


def feed_items(*titles):
    return [watcher.Item("Example", title, f"https://example.com/{index}", "", "") for index, title in enumerate(titles)]


class ToolEndpointTests(ServerTestCase):
    def setUp(self):
        super().setUp()
        patcher = patch.object(watcher_server, "LATEST_ITEMS", watcher_server.LatestItems())
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_check(self, payload, items=None, error=None):
        fetch = patch.object(
            watcher.Source, "fetch",
            side_effect=error, return_value=watcher.FeedResponse(items or [], "", "", False),
        )
        with fetch, redirect_stderr(io.StringIO()):
            response, body = self.json_request("POST", "/api/check", payload)
        self.assertEqual(response.status, 200, body)
        return json.loads(body)

    def test_checks_are_logged_with_their_trigger(self):
        self.run_check({"dry_run": True, "trigger": "auto"}, items=feed_items("Agents arrive"))
        self.run_check({"dry_run": False}, error=OSError("connection refused"))

        _, body = self.request("GET", "/api/activity")
        latest, first = json.loads(body)["checks"]
        self.assertEqual((first["trigger"], first["saved"], first["new_matches"]), ("auto", False, 1))
        self.assertEqual((latest["trigger"], latest["saved"]), ("dashboard", True))
        self.assertEqual(latest["failed"], [{"name": "Example", "error": "connection refused"}])

    def test_health_lists_every_configured_feed(self):
        self.post_feed({"name": "Never checked", "url": "https://example.org/feed"})
        self.run_check({"dry_run": True}, error=OSError("timed out"))
        _, body = self.request("GET", "/api/health")
        example, never = json.loads(body)["sources"]
        self.assertEqual((example["name"], example["status"], example["error"]), ("Example", "failing", "timed out"))
        self.assertEqual(never["status"], "failing", "the new feed was part of the check too")

        self.post_feed({"name": "Added later", "url": "https://example.net/feed"})
        _, body = self.request("GET", "/api/health")
        self.assertEqual(json.loads(body)["sources"][-1]["status"], "unchecked")

    def test_topic_tester_uses_items_from_the_last_check(self):
        self.run_check({"dry_run": True}, items=feed_items("Agents arrive", "Agent crypto pump", "Weather"))
        response, body = self.json_request(
            "POST", "/api/topic-test", {"keywords": ["agent*", "weather"], "exclude": ["crypto"], "corpus": "latest"}
        )
        self.assertEqual(response.status, 200, body)
        result = json.loads(body)
        self.assertEqual((result["total_items"], result["matched_count"], result["excluded_count"]), (3, 2, 1))
        self.assertEqual(result["keyword_hits"], [{"keyword": "agent*", "items": 2}, {"keyword": "weather", "items": 1}])
        self.assertEqual([match["title"] for match in result["matches"]], ["Agents arrive", "Weather"])
        self.assertIsNotNone(result["fetched_at"])

    def test_topic_tester_can_refresh_or_use_history(self):
        with patch.object(watcher.Source, "fetch", return_value=watcher.FeedResponse(feed_items("Fresh agent story"), "", "", False)):
            _, body = self.json_request(
                "POST", "/api/topic-test", {"keywords": ["agent*"], "corpus": "latest", "refresh": True}
            )
        self.assertEqual(json.loads(body)["matched_count"], 1)

        self.run_check({"dry_run": False}, items=feed_items("Saved agent story"))
        _, body = self.json_request("POST", "/api/topic-test", {"keywords": ["saved"], "corpus": "history"})
        result = json.loads(body)
        self.assertEqual((result["corpus"], result["matched_count"], result["fetched_at"]), ("history", 1, None))

    def test_topic_tester_validates_input(self):
        for payload in (
            {"keywords": [], "corpus": "latest"},
            {"keywords": ["*"], "corpus": "latest"},
            {"keywords": ["x"], "corpus": "everything"},
            {"keywords": ["x"], "exclude": "crypto", "corpus": "history"},
        ):
            with self.subTest(payload=payload):
                response, _ = self.json_request("POST", "/api/topic-test", payload)
                self.assertEqual(response.status, 400)


class SettingsExportImportTests(ServerTestCase):
    def seed_history(self, rows):
        watcher.SeenStore(watcher_server.DB_PATH).close()
        with closing(sqlite3.connect(watcher_server.DB_PATH)) as db:
            with db:
                db.executemany(
                    "INSERT INTO seen (topic, link, first_seen, title) VALUES (?, ?, ?, ?)", rows
                )

    def test_settings_update_is_validated_and_preserved_by_later_writes(self):
        response, body = self.json_request("PUT", "/api/settings", {"history_retention_days": 30})
        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(body)["history_retention_days"], 30)

        response, _ = self.json_request("PUT", "/api/settings", {"fetch_timeout_seconds": 0})
        self.assertEqual(response.status, 400)
        response, _ = self.json_request("PUT", "/api/settings", {"unknown": 1})
        self.assertEqual(response.status, 400)

        self.post_feed({"name": "Second", "url": "https://example.org/feed"})
        config = watcher.Config.load(self.config_path)
        self.assertEqual(config.settings.history_retention_days, 30)
        self.assertEqual(len(config.sources), 2)

        _, body = self.request("GET", "/api/dashboard")
        dashboard = json.loads(body)
        self.assertEqual(dashboard["settings"]["history_retention_days"], 30)
        self.assertEqual(dashboard["setting_defaults"], watcher.Settings().to_table())

    def test_json_export_round_trips_through_import(self):
        self.seed_history([("T", "https://example.com/a", "2026-01-01T00:00:00+00:00", "Story A")])
        response, body = self.request("GET", "/api/export?format=json")
        self.assertEqual(response.status, 200)
        self.assertIn("attachment", response.getheader("Content-Disposition"))
        document = json.loads(body)
        self.assertEqual(document["format"], "hounddog-export")
        self.assertEqual(len(document["history"]), 1)

        document["sources"].append({"name": "Imported", "url": "https://example.net/feed"})
        document["history"].append({"topic": "T", "link": "https://example.com/b", "first_seen": "2026-02-01T05:00:00-05:00"})
        response, body = self.json_request(
            "POST", "/api/import", {"data": document, "replace_config": True, "merge_history": True}
        )
        self.assertEqual(response.status, 200, body)
        self.assertEqual(json.loads(body), {"sources": 2, "topics": 1, "history_added": 1})
        self.assertEqual(len(watcher.Config.load(self.config_path).sources), 2)
        history = {item["link"]: item for item in watcher_server.seen_items()}
        self.assertEqual(history["https://example.com/b"]["first_seen"], "2026-02-01T10:00:00+00:00")

    def test_csv_export_neutralizes_spreadsheet_formulas(self):
        self.seed_history([("T", "https://example.com/a", "2026-01-01T00:00:00+00:00", '=HYPERLINK("http://evil")')])
        response, body = self.request("GET", "/api/export?format=csv")
        self.assertEqual(response.status, 200)
        text = body.decode("utf-8-sig")
        self.assertTrue(text.startswith("topic,link,first_seen"))
        self.assertIn("'=HYPERLINK", text)

    def test_invalid_import_changes_nothing(self):
        before = self.config_path.read_text(encoding="utf-8")
        bad_documents = [
            {"format": "something-else", "version": 1},
            {"format": "hounddog-export", "version": 99},
            {"format": "hounddog-export", "version": 1, "sources": [{"name": "Bad", "url": "file:///etc/passwd"}], "topics": [], "history": []},
            {"format": "hounddog-export", "version": 1, "sources": [], "topics": [],
             "history": [{"topic": "T", "link": "https://example.com/x", "first_seen": "not a date"}]},
        ]
        for document in bad_documents:
            with self.subTest(document=document):
                response, _ = self.json_request(
                    "POST", "/api/import", {"data": document, "replace_config": True, "merge_history": True}
                )
                self.assertEqual(response.status, 400)
        self.assertEqual(self.config_path.read_text(encoding="utf-8"), before)
        self.assertEqual(watcher_server.seen_items(), [])

    def test_import_needs_json_content_type_like_other_writes(self):
        response, _ = self.request("POST", "/api/import", body="{}", headers={"Content-Type": "text/plain"})
        self.assertEqual(response.status, 415)


class ConfigEntryEditTests(ServerTestCase):
    """Feeds and topics are edited by position, guarded by the entry the client expects there."""

    def setUp(self):
        super().setUp()
        self.post_feed({"name": "Second", "url": "https://example.org/feed"})
        self.json_request("POST", "/api/topics", {"name": "Policy", "keywords": ["privacy"]})

    def names(self, key):
        return [entry["name"] for entry in watcher_server.read_raw_config()[key]]

    def test_edit_and_delete_apply_when_the_expected_entry_is_there(self):
        response, body = self.json_request("PUT", "/api/topics/1", {
            "name": "Privacy", "keywords": ["privacy", "GDPR"], "expected": {"name": "Policy"},
        })
        self.assertEqual(response.status, 200, body)
        response, body = self.json_request("DELETE", "/api/feeds/0", {
            "expected": {"name": "Example", "url": "https://example.com/feed.xml"},
        })
        self.assertEqual(response.status, 200, body)
        self.assertEqual(json.loads(body)["deleted"]["name"], "Example")
        self.assertEqual((self.names("topics"), self.names("sources")), (["AI tooling", "Privacy"], ["Second"]))

    def test_a_shifted_list_is_refused_instead_of_changing_another_entry(self):
        # Another tab deleted topic 0, so "Policy" moved to position 0.
        self.json_request("DELETE", "/api/topics/0", {"expected": {"name": "AI tooling"}})
        response, _ = self.json_request("DELETE", "/api/topics/0", {"expected": {"name": "AI tooling"}})
        self.assertEqual(response.status, 409)
        response, _ = self.json_request("PUT", "/api/feeds/0", {
            "name": "Renamed", "url": "https://example.com/feed.xml",
            "expected": {"name": "Example", "url": "https://example.com/other.xml"},
        })
        self.assertEqual(response.status, 409)
        self.assertEqual((self.names("topics"), self.names("sources")), (["Policy"], ["Example", "Second"]))

    def test_expected_is_required_and_positions_are_validated(self):
        cases = [
            ("DELETE", "/api/topics/0", {}, 400),
            ("PUT", "/api/feeds/0", {"name": "X", "url": "https://example.com/x"}, 400),
            ("DELETE", "/api/topics/-1", {"expected": {"name": "AI tooling"}}, 400),
            ("DELETE", "/api/topics/9", {"expected": {"name": "AI tooling"}}, 404),
            ("PUT", "/api/topics/1", {"name": "AI tooling", "keywords": ["x"], "expected": {"name": "Policy"}}, 409),
            ("DELETE", "/api/widgets/0", {}, 404),
        ]
        for method, path, payload, status in cases:
            with self.subTest(method=method, path=path):
                response, _ = self.json_request(method, path, payload)
                self.assertEqual(response.status, status)
        self.assertEqual(self.names("topics"), ["AI tooling", "Policy"])


class LatestItemsTests(unittest.TestCase):
    def test_reports_when_the_oldest_used_source_was_fetched(self):
        latest = watcher_server.LatestItems()
        item = watcher.Item("A", "Story", "https://a.example/1", "", "")
        with patch.object(watcher, "utc_timestamp", return_value="2026-11-20T10:00:00+00:00"):
            latest.update({"https://a.example/feed": [item]})
        with patch.object(watcher, "utc_timestamp", return_value="2026-11-21T10:00:00+00:00"):
            latest.update({"https://b.example/feed": []})

        self.assertEqual(latest.for_sources(["https://a.example/feed", "https://b.example/feed"]),
                         ([item], "2026-11-20T10:00:00+00:00"))
        self.assertEqual(latest.for_sources(["https://b.example/feed"]), ([], "2026-11-21T10:00:00+00:00"))
        self.assertEqual(latest.for_sources(["https://c.example/feed"]), ([], None))


class InboxAndFetchStateTests(ServerTestCase):
    def setUp(self):
        super().setUp()
        store = watcher.SeenStore(watcher_server.DB_PATH)
        item = watcher.Item("Example", "Agents", "https://example.com/a", "", "Sat, 21 Nov 2026 22:19:43 GMT",
                            published_at="2026-11-21T22:19:43+00:00")
        store.mark_seen([watcher.Match("AI tooling", item, ()), watcher.Match("Other", item, ())])
        store.close()

    def history(self):
        _, body = self.request("GET", "/api/dashboard")
        return json.loads(body)["seen_items"]

    def test_item_state_is_shared_by_every_row_of_an_article(self):
        response, body = self.json_request("PUT", "/api/items/state", {"links": ["https://example.com/a"], "read": True, "starred": True})
        self.assertEqual(response.status, 200, body)
        rows = self.history()
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["read_at"] and row["starred_at"] for row in rows))
        self.assertEqual(rows[0]["published_at"], "2026-11-21T22:19:43+00:00")

        self.json_request("PUT", "/api/items/state", {"links": ["https://example.com/a"], "read": False})
        self.assertTrue(all(row["read_at"] is None and row["starred_at"] for row in self.history()))

    def test_item_state_requests_are_validated(self):
        for payload in (
            {"links": [], "read": True},
            {"links": "https://example.com/a", "read": True},
            {"links": ["https://example.com/a"]},
            {"links": ["https://example.com/a"], "read": "yes"},
            {"links": ["x"] * (watcher_server.MAX_STATE_LINKS + 1), "read": True},
        ):
            with self.subTest(payload=str(payload)[:60]):
                response, _ = self.json_request("PUT", "/api/items/state", payload)
                self.assertEqual(response.status, 400)

    def test_export_carries_state_and_import_merges_it_with_canonical_links(self):
        self.json_request("PUT", "/api/items/state", {"links": ["https://example.com/a"], "starred": True})
        _, body = self.request("GET", "/api/export?format=json")
        document = json.loads(body)
        self.assertTrue(all(row["starred_at"] for row in document["history"]))

        document["history"].append({
            "topic": "AI tooling", "link": "https://example.com/b?utm_source=rss#top",
            "first_seen": "2026-11-01T00:00:00+00:00", "read_at": "2026-11-02T00:00:00Z",
        })
        response, body = self.json_request("POST", "/api/import", {"data": document, "merge_history": True})
        self.assertEqual(response.status, 200, body)
        imported = [row for row in self.history() if row["link"] == "https://example.com/b"]
        self.assertEqual([(row["read_at"], row["starred_at"]) for row in imported], [("2026-11-02T00:00:00+00:00", None)])

    def test_import_keeps_local_state_for_articles_already_here(self):
        _, body = self.request("GET", "/api/export?format=json")
        document = json.loads(body)
        for row in document["history"]:
            row["read_at"] = "2026-11-02T00:00:00Z"  # the backup says read; here it is unread
        document["history"].append({"topic": "AI tooling", "link": "https://example.com/new",
                                    "first_seen": "2026-11-01T00:00:00Z", "starred_at": "2026-11-02T00:00:00Z"})
        response, body = self.json_request("POST", "/api/import", {"data": document, "merge_history": True})
        self.assertEqual(response.status, 200, body)
        state = {row["link"]: (row["read_at"], row["starred_at"]) for row in self.history()}
        self.assertEqual(state["https://example.com/a"], (None, None), "local unread wins")
        self.assertEqual(state["https://example.com/new"], (None, "2026-11-02T00:00:00+00:00"))

    def test_clear_history_forgets_feed_validators_but_keeps_backoff(self):
        with closing(sqlite3.connect(watcher_server.DB_PATH)) as db, db:
            watcher.ensure_seen_schema(db)
            db.execute(
                "INSERT INTO feed_state (url, etag, last_modified, fingerprint, saved_at, retry_at) "
                "VALUES ('https://example.com/feed.xml', '\"v\"', 'date', 'fp', 'now', 'later')"
            )
        self.request("DELETE", "/api/seen")
        store = watcher.SeenStore(watcher_server.DB_PATH)
        self.addCleanup(store.close)
        self.assertEqual(store.feed_states()["https://example.com/feed.xml"], watcher.FeedState(retry_at="later"))
        self.assertEqual(self.history(), [])

    def test_feed_interval_is_validated_saved_and_used(self):
        response, body = self.post_feed({"name": "Daily", "url": "https://example.org/daily", "check_every_minutes": 1440})
        self.assertEqual(response.status, 201, body)
        self.assertEqual(watcher.Config.load(self.config_path).sources[-1].check_every_minutes, 1440)
        for interval in (0, 99999, "60", True):
            with self.subTest(interval=interval):
                response, _ = self.post_feed({"name": "Bad", "url": "https://example.org/bad", "check_every_minutes": interval})
                self.assertEqual(response.status, 400)

        response, body = self.json_request("PUT", "/api/feeds/1", {
            "name": "Daily", "url": "https://example.org/daily",
            "expected": {"name": "Daily", "url": "https://example.org/daily"},
        })
        self.assertEqual(response.status, 200, body)
        self.assertIsNone(watcher.Config.load(self.config_path).sources[-1].check_every_minutes, "cleared by omitting it")

    def test_check_reports_feeds_that_are_not_due(self):
        self.post_feed({"name": "Daily", "url": "https://example.org/daily", "check_every_minutes": 1440})
        fetch = patch.object(watcher.Source, "fetch", return_value=watcher.FeedResponse([], "", "", False))
        with fetch, redirect_stderr(io.StringIO()):
            self.json_request("POST", "/api/check", {"dry_run": False})
            _, body = self.json_request("POST", "/api/check", {"dry_run": False})
        result = json.loads(body)
        self.assertEqual([skip["name"] for skip in result["skipped_sources"]], ["Daily"])

    def test_saved_checks_write_the_event_export_and_the_setting_survives_writes(self):
        item = watcher.Item("Feed", "Agent news", "https://example.com/agent", "", "")
        fetch = patch.object(watcher.Source, "fetch", return_value=watcher.FeedResponse([item], "", "", False))
        with fetch, redirect_stderr(io.StringIO()):
            _, body = self.json_request("POST", "/api/check", {"dry_run": False})
        self.assertEqual(json.loads(body)["export_error"], "")
        [path] = watcher.export_directory(watcher_server.DB_PATH).glob("hounddog-*.jsonl")
        schemas = [json.loads(line)["schema"] for line in path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(schemas[0], watcher.COVERAGE_SCHEMA)

        response, body = self.json_request("PUT", "/api/settings", {"event_export": False})
        self.assertEqual((response.status, json.loads(body)["event_export"]), (200, False))
        self.assertIn("event_export = false", self.config_path.read_text(encoding="utf-8"))
        self.assertFalse(watcher.Config.load(self.config_path).settings.event_export)


class BackgroundJobEndpointTests(ServerTestCase):
    def use_scheduler(self, runner, supported=True):
        fake = scheduled_task.TaskScheduler(watcher_server.ROOT, run=runner, supported=supported,
                                            executable="C:/Python312/python.exe")
        patcher = patch.object(watcher_server, "SCHEDULER", fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_status_install_run_and_remove(self):
        runner = FakePowerShell('{"installed":false}')
        self.use_scheduler(runner)
        response, body = self.request("GET", "/api/schedule")
        self.assertEqual((response.status, json.loads(body)["installed"]), (200, False))

        response, body = self.json_request("PUT", "/api/schedule", {"interval_minutes": 60, "run_on_battery": False})
        self.assertEqual(response.status, 200, body)
        xml = runner.calls[-2]["env"]["HOUNDDOG_TASK_XML"]
        self.assertIn("<Interval>PT60M</Interval>", xml)
        self.assertIn("<DisallowStartIfOnBatteries>true</DisallowStartIfOnBatteries>", xml)

        response, _ = self.json_request("POST", "/api/schedule/run", {})
        self.assertEqual(response.status, 200)
        response, _ = self.request("DELETE", "/api/schedule")
        self.assertEqual(response.status, 200)
        self.assertEqual(runner.scripts[-2], scheduled_task.REMOVE_SCRIPT)

    def test_bad_intervals_are_refused_before_task_scheduler_runs(self):
        runner = FakePowerShell()
        self.use_scheduler(runner)
        for payload in ({}, {"interval_minutes": "15"}, {"interval_minutes": True}, {"interval_minutes": 7},
                        {"interval_minutes": 15, "require_network": 1}):
            with self.subTest(payload=payload):
                response, _ = self.json_request("PUT", "/api/schedule", payload)
                self.assertEqual(response.status, 400)
        self.assertEqual(runner.calls, [])

    def test_task_scheduler_errors_and_other_systems(self):
        self.use_scheduler(FakePowerShell(returncode=1, stderr="Register-ScheduledTask : Access is denied."))
        response, body = self.json_request("PUT", "/api/schedule", {"interval_minutes": 15})
        self.assertEqual((response.status, json.loads(body)["error"]), (502, "Register-ScheduledTask : Access is denied."))

        self.use_scheduler(FakePowerShell(), supported=False)
        _, body = self.request("GET", "/api/schedule")
        self.assertFalse(json.loads(body)["supported"])
        response, _ = self.json_request("PUT", "/api/schedule", {"interval_minutes": 15})
        self.assertEqual(response.status, 501)

    def test_status_carries_the_job_log_and_it_can_be_cleared(self):
        self.use_scheduler(FakePowerShell('{"installed":false}'))
        log_path = watcher_server.DB_PATH.with_name(watcher.JOB_LOG_NAME)
        patcher = patch.object(watcher_server, "JOB_LOG_PATH", log_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        _, body = self.request("GET", "/api/schedule")
        self.assertEqual(json.loads(body)["log"], [])

        log_path.write_text("2026-11-22T15:00:00+00:00 exit 2\nerror: invalid TOML\x1b[31m\n", encoding="utf-8")
        _, body = self.request("GET", "/api/schedule")
        self.assertEqual(json.loads(body)["log"], ["2026-11-22T15:00:00+00:00 exit 2", "error: invalid TOML [31m"])

        response, _ = self.request("DELETE", "/api/schedule/log")
        self.assertEqual(response.status, 200)
        self.assertFalse(log_path.exists())

    def test_health_says_whether_a_feed_can_answer_unchanged(self):
        with closing(sqlite3.connect(watcher_server.DB_PATH)) as db, db:
            watcher.ensure_seen_schema(db)
            db.execute(
                "INSERT INTO feed_state (url, etag, last_modified, fingerprint, saved_at, retry_at) "
                "VALUES ('https://example.com/feed.xml', '\"v\"', '', 'fp', 'now', '')"
            )
        _, body = self.request("GET", "/api/health")
        self.assertIs(json.loads(body)["sources"][0]["conditional"], True)

    def test_schedule_writes_need_the_same_guards_as_other_writes(self):
        self.use_scheduler(FakePowerShell())
        response, _ = self.request("PUT", "/api/schedule", body="{}", headers={"Content-Type": "text/plain"})
        self.assertEqual(response.status, 415)
        response, _ = self.request("DELETE", "/api/schedule", headers={"Origin": "https://evil.example"})
        self.assertEqual(response.status, 403)


if __name__ == "__main__":
    unittest.main()
