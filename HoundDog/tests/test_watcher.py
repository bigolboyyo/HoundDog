from contextlib import closing, redirect_stderr, redirect_stdout
import gzip
import io
import json
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
import xml.etree.ElementTree as ET

import watcher
import watcher_server


class FeedMetadataTests(unittest.TestCase):
    def test_rss_parser_extracts_author_description_and_image(self):
        root = ET.fromstring(
            """\
            <rss xmlns:dc="http://purl.org/dc/elements/1.1/"
                 xmlns:media="http://search.yahoo.com/mrss/">
              <channel><item>
                <title>Example story</title>
                <link>https://example.com/story</link>
                <description><![CDATA[<p>Short description.</p>]]></description>
                <pubDate>Fri, 21 Nov 2026 10:00:00 GMT</pubDate>
                <dc:creator>Example author</dc:creator>
                <media:thumbnail url="https://example.com/story.jpg" />
              </item></channel>
            </rss>
            """
        )

        [item] = watcher.parse_rss(root, "Example feed")

        self.assertEqual(item.source, "Example feed")
        self.assertEqual(item.author, "Example author")
        self.assertEqual(item.summary, "Short description.")
        self.assertEqual(item.image_url, "https://example.com/story.jpg")

    def test_rss_parser_finds_image_embedded_in_description(self):
        root = ET.fromstring(
            """\
            <rss><channel><item>
              <description><![CDATA[<p>Story</p><img src="https://example.com/inline.jpg">]]></description>
            </item></channel></rss>
            """
        )

        [item] = watcher.parse_rss(root, "Example feed")

        self.assertEqual(item.image_url, "https://example.com/inline.jpg")

    def test_existing_seen_database_migrates_without_losing_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "watcher.db"
            with closing(sqlite3.connect(path)) as db:
                with db:
                    db.execute(
                        "CREATE TABLE seen ("
                        "topic TEXT NOT NULL, link TEXT NOT NULL, first_seen TEXT NOT NULL, "
                        "PRIMARY KEY (topic, link))"
                    )
                    db.execute(
                        "INSERT INTO seen VALUES (?, ?, ?)",
                        ("Policy", "https://example.com/old", "2026-04-01T10:00:00+00:00"),
                    )

            with patch.object(watcher_server, "DB_PATH", path):
                [item] = watcher_server.seen_items()

            self.assertEqual(item["topic"], "Policy")
            self.assertEqual(item["link"], "https://example.com/old")
            self.assertEqual(item["title"], None)
            self.assertEqual(item["image_url"], None)

    def test_seen_store_persists_item_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "watcher.db"
            item = watcher.Item(
                source="Example feed",
                title="Example story",
                link="https://example.com/story",
                summary="Short description.",
                published="2026-04-02T09:00:00+00:00",
                author="Example author",
                image_url="https://example.com/story.jpg",
            )
            store = watcher.SeenStore(path)
            try:
                store.mark_seen([watcher.Match("AI tooling", item, ("AI",))])
            finally:
                store.close()

            with patch.object(watcher_server, "DB_PATH", path):
                [seen] = watcher_server.seen_items()

            self.assertEqual(seen["source"], "Example feed")
            self.assertEqual(seen["title"], "Example story")
            self.assertEqual(seen["summary"], "Short description.")
            self.assertEqual(seen["published"], "2026-04-02T09:00:00+00:00")
            self.assertEqual(seen["author"], "Example author")
            self.assertEqual(seen["image_url"], "https://example.com/story.jpg")

    def test_normal_feed_check_enriches_existing_seen_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "watcher.db"
            link = "https://example.com/old-story"
            store = watcher.SeenStore(path)
            store.mark_seen(
                [
                    watcher.Match(
                        "AI tooling",
                        watcher.Item("Example feed", "", link, "", ""),
                        (),
                    )
                ]
            )
            with patch.object(watcher_server, "DB_PATH", path):
                old_first_seen = watcher_server.seen_items()[0]["first_seen"]

            class StaticSource:
                name = "Example feed"
                url = "https://example.com/feed.xml"
                check_every_minutes = None

                def fetch(self, settings, validators):
                    return feed_response([
                        watcher.Item(
                            "Example feed",
                            "Agent tools update",
                            link,
                            "A refreshed description.",
                            "2026-04-02T09:00:00+00:00",
                            "Example author",
                            "https://example.com/old-story.jpg",
                        )
                    ])

            check = watcher.Watcher(
                [StaticSource()],
                [watcher.Topic("AI tooling", ["agent"], [])],
                store,
                watcher.Settings(),
            )
            result = check.collect()
            self.assertEqual(result.matches, ())
            self.assertEqual(len(result.seen_updates), 1)
            store.mark_seen(result.seen_updates)
            store.close()

            with patch.object(watcher_server, "DB_PATH", path):
                [seen] = watcher_server.seen_items()

            self.assertEqual(seen["first_seen"], old_first_seen)
            self.assertEqual(seen["title"], "Agent tools update")
            self.assertEqual(seen["summary"], "A refreshed description.")
            self.assertEqual(seen["image_url"], "https://example.com/old-story.jpg")


class FeedHardeningTests(unittest.TestCase):
    def test_clean_text_strips_terminal_control_characters(self):
        self.assertEqual(watcher.clean_text("Title\x1b]0;pwned\x07 \x9b31m end"), "Title ]0;pwned 31m end")

    def test_atom_link_and_image_urls_are_cleaned(self):
        root = ET.fromstring(
            """\
            <feed xmlns="http://www.w3.org/2005/Atom"><entry>
              <title>Story</title>
              <link href="https://example.com/a&#x9b;b" />
              <link rel="enclosure" type="image/png" href="https://example.com/i&#x85;.png" />
            </entry></feed>
            """
        )

        [item] = watcher.parse_atom(root, "Example feed")

        self.assertEqual(item.link, "https://example.com/a b")
        self.assertEqual(item.image_url, "https://example.com/i .png")

    def test_redirects_to_non_http_schemes_are_refused(self):
        handler = watcher.HttpOnlyRedirectHandler()
        request = urllib.request.Request("https://example.com/feed")
        with self.assertRaises(urllib.error.HTTPError):
            handler.redirect_request(request, None, 302, "Found", {}, "ftp://example.com/feed")
        self.assertIsNotNone(
            handler.redirect_request(request, None, 302, "Found", {}, "https://example.org/feed")
        )

    def test_read_limited_caps_size_and_total_time(self):
        class EndlessResponse:
            def read1(self, size):
                return b"x" * size

        class FixedResponse:
            def __init__(self, size):
                self._body = io.BytesIO(b"x" * size)

            def read1(self, size):
                return self._body.read1(size)

        self.assertEqual(len(watcher.read_limited(FixedResponse(100_000), 100_000, 60)), 100_000)
        with self.assertRaisesRegex(ValueError, "larger than"):
            watcher.read_limited(EndlessResponse(), 100_000, 60)
        with self.assertRaises(TimeoutError):
            watcher.read_limited(EndlessResponse(), 100_000, -1)

    def test_reload_config_keeps_previous_config_when_file_breaks(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "watch.toml"
            path.write_text(
                '[[sources]]\nname = "A"\nurl = "https://example.com/a"\n'
                '[[topics]]\nname = "T"\nkeywords = ["x"]\n',
                encoding="utf-8",
            )
            current = watcher.Config.load(path)
            path.write_text("not = [valid", encoding="utf-8")
            with redirect_stderr(io.StringIO()) as stderr:
                self.assertIs(watcher.reload_config(path, current), current)
            self.assertIn("keeping previous configuration", stderr.getvalue())

    def test_config_rejects_urls_without_host(self):
        with self.assertRaises(watcher.ConfigError):
            watcher.Config._parse_source({"name": "Bad", "url": "http:///feed"}, 1)


BILLION_LAUGHS = b"""<?xml version="1.0"?>
<!DOCTYPE rss [
  <!ENTITY lol "lol">
  <!ENTITY lol1 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
  <!ENTITY lol2 "&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;">
  <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
]>
<rss><channel><item><title>&lol3;</title></item></channel></rss>
"""


class FeedXmlSafetyTests(unittest.TestCase):
    def test_entity_expansion_attacks_are_refused(self):
        quadratic_blowup = (
            b'<!DOCTYPE rss [<!ENTITY a "' + b"x" * 10_000 + b'">]>'
            b"<rss><channel><item><title>" + b"&a;" * 1_000 + b"</title></item></channel></rss>"
        )
        external_entity = (
            b'<!DOCTYPE rss [<!ENTITY ext SYSTEM "file:///etc/passwd">]>'
            b"<rss><channel><item><title>&ext;</title></item></channel></rss>"
        )
        for label, payload in (
            ("billion laughs", BILLION_LAUGHS),
            ("quadratic blowup", quadratic_blowup),
            ("external entity", external_entity),
        ):
            with self.subTest(label):
                with self.assertRaisesRegex(ET.ParseError, "declares XML entities"):
                    watcher.parse_feed_xml(payload)

    def test_doctype_without_entities_is_accepted(self):
        root = watcher.parse_feed_xml(
            b'<!DOCTYPE rss PUBLIC "-//Netscape Communications//DTD RSS 0.91//EN" '
            b'"http://my.netscape.com/publish/formats/rss-0.91.dtd">'
            b"<rss><channel><item><title>Story</title></item></channel></rss>"
        )
        self.assertEqual(root.tag, "rss")

    def test_malformed_xml_raises_parse_error(self):
        with self.assertRaises(ET.ParseError):
            watcher.parse_feed_xml(b"<rss><channel>")

    def test_refused_feed_is_reported_as_failed_source(self):
        class Response:
            headers = {}

            def __init__(self):
                self._body = io.BytesIO(BILLION_LAUGHS)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read1(self, size):
                return self._body.read1(size)

        with tempfile.TemporaryDirectory() as directory:
            store = watcher.SeenStore(Path(directory) / "watcher.db")
            try:
                check = watcher.Watcher(
                    [watcher.Source("Hostile", "https://example.com/feed")],
                    [watcher.Topic("Any", ["lol*"], [])],
                    store,
                    watcher.Settings(),
                )
                with patch.object(watcher.OPENER, "open", return_value=Response()):
                    with redirect_stderr(io.StringIO()) as stderr:
                        result = check.collect()
            finally:
                store.close()

        self.assertEqual(result.matches, ())
        self.assertEqual(result.failed_sources, ["Hostile"])
        self.assertIn("declares XML entities", stderr.getvalue())


class SettingsTests(unittest.TestCase):
    def write_config(self, directory, settings=""):
        path = Path(directory) / "watch.toml"
        path.write_text(
            settings
            + '[[sources]]\nname = "A"\nurl = "https://example.com/a"\n'
            + '[[topics]]\nname = "T"\nkeywords = ["x"]\n',
            encoding="utf-8",
        )
        return path

    def test_missing_settings_table_uses_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            config = watcher.Config.load(self.write_config(directory))
        self.assertEqual(config.settings, watcher.Settings())
        self.assertEqual(config.settings.max_feed_bytes, 5_000_000)
        self.assertEqual(config.settings.fetch_deadline_seconds, 60)
        self.assertEqual(config.settings.history_retention_days, 90)

    def test_settings_table_is_loaded(self):
        with tempfile.TemporaryDirectory() as directory:
            config = watcher.Config.load(self.write_config(directory, (
                "[settings]\nfetch_timeout_seconds = 30\nmax_feed_megabytes = 10\n"
                'user_agent = "HoundDog/1.0"\nhistory_retention_days = 90\n'
            )))
        self.assertEqual(config.settings, watcher.Settings(30, 10, "HoundDog/1.0", 90))

    def test_invalid_settings_are_rejected(self):
        for table in (
            {"fetch_timeout_seconds": 0},
            {"fetch_timeout_seconds": True},
            {"max_feed_megabytes": 500},
            {"history_retention_days": -1},
            {"user_agent": ""},
            {"user_agent": "bad\x1bagent"},
            {"typo_setting": 1},
            [],
        ):
            with self.subTest(table=table):
                with self.assertRaises(watcher.ConfigError):
                    watcher.Settings.from_table(table)

    def test_fetch_uses_settings(self):
        captured = {}

        class Response(io.BytesIO):
            headers = {}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_open(request, timeout):
            captured["agent"] = request.get_header("User-agent")
            captured["timeout"] = timeout
            return Response(b"<rss><channel></channel></rss>")

        with patch.object(watcher.OPENER, "open", side_effect=fake_open):
            response = watcher.Source("A", "https://example.com/a").fetch(watcher.Settings(7, 1, "HoundDog/1.0", 0))
        self.assertEqual(response.items, [])
        self.assertEqual(captured, {"agent": "HoundDog/1.0", "timeout": 7})


class RetentionTests(unittest.TestCase):
    def test_prune_forgets_only_items_older_than_retention(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "watcher.db"
            store = watcher.SeenStore(path)
            try:
                with closing(sqlite3.connect(path)) as db:
                    with db:
                        db.executemany(
                            "INSERT INTO seen (topic, link, first_seen) VALUES (?, ?, ?)",
                            [
                                ("T", "https://example.com/old", "2020-01-01T00:00:00+00:00"),
                                ("T", "https://example.com/new", "2999-01-01T00:00:00+00:00"),
                            ],
                        )
                self.assertEqual(store.prune(0), 0, "0 keeps everything")
                self.assertEqual(store.prune(30), 1)
                self.assertTrue(store.contains("T", "https://example.com/new"))
                self.assertFalse(store.contains("T", "https://example.com/old"))
            finally:
                store.close()


class FakeSource:
    check_every_minutes = None

    def __init__(self, name, items=None, error=None):
        self.name = name
        self.url = f"https://example.com/{name}.xml"
        self._items = items or []
        self._error = error

    def fetch(self, settings, validators):
        if self._error:
            raise self._error
        return feed_response(self._items)


def feed_response(items, etag="", last_modified="", not_modified=False):
    return watcher.FeedResponse(list(items), etag, last_modified, not_modified)


def story(link, title):
    return watcher.Item("Feed", title, link, "", "")


class TopicEvaluationTests(unittest.TestCase):
    def test_evaluate_reports_hits_and_vetoes(self):
        topic = watcher.Topic("T", ["agent*", "LLM"], ["crypto"])
        clean = topic.evaluate("New agents for LLM work")
        self.assertEqual(clean.keywords, ("agent*", "LLM"))
        self.assertTrue(clean.matched)
        vetoed = topic.evaluate("Agent crypto scheme")
        self.assertEqual((vetoed.keywords, vetoed.excluded_by), (("agent*",), ("crypto",)))
        self.assertFalse(vetoed.matched)
        self.assertEqual(topic.matched_keywords("Agent crypto scheme"), [])


class CheckLogTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "watcher.db"

    def collect(self, sources):
        store = watcher.SeenStore(self.path)
        self.addCleanup(store.close)
        check = watcher.Watcher(sources, [watcher.Topic("T", ["hound*"], [])], store, watcher.Settings())
        with redirect_stderr(io.StringIO()):
            return check.collect()

    def test_collect_reports_each_source(self):
        result = self.collect([
            FakeSource("good", [story("https://example.com/1", "Hound news"), story("https://example.com/2", "Other")]),
            FakeSource("broken", error=OSError("connection refused")),
        ])
        self.assertEqual(len(result.matches), 1)
        good, broken = result.source_results
        self.assertEqual((good.ok, good.item_count, good.new_matches, good.error), (True, 2, 1, ""))
        self.assertEqual((broken.ok, broken.item_count, broken.error), (False, 0, "connection refused"))
        self.assertEqual(list(result.fetched_items), ["https://example.com/good.xml"])
        self.assertEqual(result.failed_sources, ["broken"])

    def test_network_errors_keep_their_reason(self):
        refused = urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))
        result = self.collect([
            FakeSource("refused", error=refused),
            FakeSource("missing", error=urllib.error.HTTPError("https://x", 404, "Not Found", {}, None)),
            FakeSource("odd", error=ValueError("unsupported feed format <html>")),
        ])
        self.assertEqual([r.error for r in result.source_results], [
            "[Errno 111] Connection refused", "HTTP Error 404: Not Found", "unsupported feed format <html>",
        ])

    def test_sources_are_fetched_in_parallel_and_reported_in_order(self):
        # Each fake fetch waits for the other; run one after another, both would time out.
        both_started = threading.Barrier(2, timeout=5)

        class WaitingSource(FakeSource):
            def fetch(self, settings, validators):
                both_started.wait()
                return super().fetch(settings, validators)

        result = self.collect([
            WaitingSource("first", [story("https://example.com/1", "Hound one")]),
            WaitingSource("second", [story("https://example.com/2", "Hound two")]),
        ])
        self.assertEqual([r.name for r in result.source_results], ["first", "second"])
        self.assertEqual([r.ok for r in result.source_results], [True, True])
        self.assertEqual([m.item.link for m in result.matches], ["https://example.com/1", "https://example.com/2"])

    def test_recent_and_health_summarize_logged_checks(self):
        log = watcher.CheckLog(self.path)
        self.addCleanup(log.close)
        ok = watcher.SourceResult("A", "https://a.example/feed", True, "", 10, 2, 120)
        failing = watcher.SourceResult("B", "https://b.example/feed", False, "HTTP Error 404", 0, 0, 40)
        log.record("2026-11-20T10:00:00+00:00", 500, "cli", True, 2, 0, [ok, failing])
        log.record("2026-11-21T10:00:00+00:00", 300, "auto", False, 0, 1,
                   [watcher.SourceResult("A", "https://a.example/feed", True, "", 0, 0, 90), failing])

        latest, first = log.recent(10)
        self.assertEqual((latest["trigger"], latest["saved"], latest["pruned"], latest["source_count"]), ("auto", False, 1, 2))
        self.assertEqual(first["failed"], [{"name": "B", "error": "HTTP Error 404"}])

        a, b, c = log.source_health([("A", "https://a.example/feed"), ("B", "https://b.example/feed"), ("C", "https://c.example/feed")])
        self.assertEqual((a["status"], a["last_new_match"], a["item_count"]), ("empty", "2026-11-20T10:00:00+00:00", 0))
        self.assertEqual((b["status"], b["failure_streak"], b["last_success"], b["error"]), ("failing", 2, None, "HTTP Error 404"))
        self.assertEqual(c["status"], "unchecked")

    def test_failure_streak_counts_every_failure_since_the_last_success(self):
        log = watcher.CheckLog(self.path)
        self.addCleanup(log.close)
        url = "https://a.example/feed"
        log.record("2026-11-01T00:00:00+00:00", 1, "cli", True, 0, 0, [watcher.SourceResult("A", url, True, "", 5, 0, 1)])
        failure = watcher.SourceResult("A", url, False, "timed out", 0, 0, 1)
        for minute in range(75):
            log.record(f"2026-11-02T00:{minute // 60:02d}:{minute % 60:02d}+00:00", 1, "auto", False, 0, 0, [failure])
        [health] = log.source_health([("A", url)])
        self.assertEqual((health["status"], health["failure_streak"]), ("failing", 75))
        self.assertEqual(health["last_success"], "2026-11-01T00:00:00+00:00")

    def test_log_keeps_only_the_newest_checks(self):
        log = watcher.CheckLog(self.path)
        self.addCleanup(log.close)
        result = watcher.SourceResult("A", "https://a.example/feed", True, "", 1, 0, 1)
        with patch.object(watcher, "MAX_LOGGED_CHECKS", 3):
            for day in range(1, 6):
                log.record(f"2026-11-0{day}T00:00:00+00:00", 1, "cli", True, 0, 0, [result])
        self.assertEqual([check["started_at"][:10] for check in log.recent(10)], ["2026-11-05", "2026-11-04", "2026-11-03"])
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM check_sources").fetchone()[0], 3)

    def test_unknown_trigger_is_rejected(self):
        log = watcher.CheckLog(self.path)
        self.addCleanup(log.close)
        with self.assertRaises(ValueError):
            log.record("2026-11-21T10:00:00+00:00", 1, "cron", True, 0, 0, [])

    def test_cli_run_is_logged(self):
        config_path = Path(self.path).with_name("watch.toml")
        config_path.write_text(
            '[[sources]]\nname = "A"\nurl = "https://example.com/a"\n[[topics]]\nname = "T"\nkeywords = ["x"]\n',
            encoding="utf-8",
        )
        with patch.object(watcher.Source, "fetch", return_value=feed_response([])):
            with redirect_stdout(io.StringIO()):
                watcher.main(["--config", str(config_path), "--db", str(self.path), "--dry-run"])
        log = watcher.CheckLog(self.path)
        self.addCleanup(log.close)
        [check] = log.recent(5)
        self.assertEqual((check["trigger"], check["saved"], check["source_count"]), ("cli", False, 1))

        with patch.object(watcher.Source, "fetch", return_value=feed_response([])):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(watcher.main(["--config", str(config_path), "--db", str(self.path), "--scheduled"]), 0)
        latest = log.recent(1)[0]
        self.assertEqual((latest["trigger"], latest["saved"]), ("scheduled", True))
        with redirect_stderr(io.StringIO()):
            self.assertEqual(watcher.main(["--config", str(config_path), "--scheduled", "--dry-run"]), 2)

    def test_scheduled_runs_log_problems_instead_of_printing_them(self):
        job_log = Path(self.path).with_name(watcher.JOB_LOG_NAME)
        config_path = Path(self.path).with_name("watch.toml")
        config_path.write_text("not = [valid", encoding="utf-8")
        args = ["--config", str(config_path), "--db", str(self.path), "--scheduled"]
        with redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(watcher.main(args), watcher.EXIT_USAGE_OR_CONFIG)
        self.assertEqual(stderr.getvalue(), "", "nothing is printed; there is no console")
        heading, message = job_log.read_text(encoding="utf-8").splitlines()[:2]
        self.assertRegex(heading, r"^\d{4}-\d\d-\d\dT.* exit 2$")
        self.assertIn("invalid TOML", message)

        config_path.write_text('[[sources]]\nname = "A"\nurl = "https://example.com/a"\n[[topics]]\nname = "T"\nkeywords = ["x"]\n',
                               encoding="utf-8")
        with patch.object(watcher.Watcher, "collect", side_effect=RuntimeError("boom")):
            self.assertEqual(watcher.main(args), watcher.EXIT_CRASHED)
        log = job_log.read_text(encoding="utf-8")
        self.assertIn("exit 3", log)
        self.assertIn("RuntimeError: boom", log)

        size_before = job_log.stat().st_size
        with patch.object(watcher.Source, "fetch", return_value=feed_response([])):
            self.assertEqual(watcher.main(args), watcher.EXIT_OK)
        self.assertEqual(job_log.stat().st_size, size_before, "a clean run adds nothing")

    def test_interval_watching_survives_a_failed_check(self):
        config_path = Path(self.path).with_name("watch.toml")
        config_path.write_text(
            '[[sources]]\nname = "A"\nurl = "https://example.com/a"\n[[topics]]\nname = "T"\nkeywords = ["x"]\n',
            encoding="utf-8",
        )
        calls = []

        def flaky_check(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise sqlite3.OperationalError("database is locked")
            raise KeyboardInterrupt

        with patch.object(watcher, "run_cli_check", side_effect=flaky_check), \
                patch.object(watcher.time, "sleep"), redirect_stdout(io.StringIO()), \
                redirect_stderr(io.StringIO()) as stderr:
            code = watcher.main(["--config", str(config_path), "--db", str(self.path), "--interval", "1"])
        self.assertEqual((code, len(calls)), (watcher.EXIT_OK, 2), "the second check still ran")
        self.assertIn("database is locked", stderr.getvalue())

    def test_the_job_log_stays_bounded(self):
        job_log = Path(self.path).with_name(watcher.JOB_LOG_NAME)
        with patch.object(watcher, "MAX_JOB_LOG_BYTES", 1000):
            for number in range(100):
                watcher.append_job_log(job_log, f"entry {number}", "x" * 40)
        text = job_log.read_text(encoding="utf-8")
        self.assertLessEqual(len(text), 1000)
        self.assertTrue(text.startswith("entry ") or text.startswith("x"), "trimmed at a line boundary")
        self.assertIn("entry 99", text)


class NormalizationTests(unittest.TestCase):
    def test_canonical_link_drops_tracking_and_fragments_only(self):
        cases = {
            "https://www.bbc.co.uk/news/articles/c6ly5w40eg07o?at_medium=RSS&at_campaign=rss":
                "https://www.bbc.co.uk/news/articles/c6ly5w40eg07o",
            "HTTPS://Example.COM:443/Path/Case?id=3&utm_source=x&UTM_Medium=y#section":
                "https://example.com/Path/Case?id=3",
            "https://news.ycombinator.com/item?id=42": "https://news.ycombinator.com/item?id=42",
            "https://example.com/p?q=a%20b&fbclid=1&flag": "https://example.com/p?q=a%20b&flag",
            "http://example.com:8080/x": "http://example.com:8080/x",
            "urn:uuid:1234": "urn:uuid:1234",
        }
        for link, expected in cases.items():
            with self.subTest(link=link):
                self.assertEqual(watcher.canonical_link(link), expected)

    def test_published_dates_become_utc_timestamps(self):
        cases = {
            "Sat, 21 Nov 2026 22:19:43 GMT": "2026-11-21T22:19:43+00:00",
            "Wed, 18 Nov 2026 09:15:58 -0500": "2026-11-18T14:15:58+00:00",
            "2026-11-19T18:59:53Z": "2026-11-19T18:59:53+00:00",
            "2026-11-19T13:59:53-05:00": "2026-11-19T18:59:53+00:00",
            # No usable zone: unknown rather than guessed as UTC.
            "2026-11-19": "",
            "2026-11-19T18:59:53": "",
            "Sat, 21 Nov 2026 22:19:43 CET": "",
            "Sat, 21 Nov 2026 22:19:43 -0000": "",
            "next Tuesday": "",
            "": "",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(watcher.normalize_published(raw), expected)

    def test_feed_items_carry_canonical_links_and_dates(self):
        root = watcher.parse_feed_xml(
            b"<rss><channel><item><title>T</title>"
            b"<link>https://example.com/a?utm_source=rss#top</link>"
            b"<pubDate>Sat, 21 Nov 2026 22:19:43 GMT</pubDate></item></channel></rss>"
        )
        [item] = watcher.parse_rss(root, "Feed")
        self.assertEqual((item.link, item.published_at), ("https://example.com/a", "2026-11-21T22:19:43+00:00"))

    def test_existing_history_is_migrated_once(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "watcher.db"
            with closing(sqlite3.connect(path)) as db:
                db.execute(
                    "CREATE TABLE seen (topic TEXT NOT NULL, link TEXT NOT NULL, first_seen TEXT NOT NULL, "
                    "source TEXT, title TEXT, summary TEXT, published TEXT, author TEXT, image_url TEXT, "
                    "PRIMARY KEY (topic, link))"
                )
                db.executemany("INSERT INTO seen (topic, link, first_seen, title, published) VALUES (?, ?, ?, ?, ?)", [
                    ("T", "https://example.com/a?utm_source=x", "2026-11-02T00:00:00+00:00", "A", "2026-11-01T08:00:00Z"),
                    ("T", "https://example.com/a", "2026-11-03T00:00:00+00:00", "A", ""),
                    ("U", "https://example.com/a#comments", "2026-11-04T00:00:00+00:00", "A", "bad date"),
                ])
                db.commit()

            watcher.SeenStore(path).close()
            with closing(sqlite3.connect(path)) as db:
                rows = db.execute("SELECT topic, link, first_seen, published_at FROM seen ORDER BY topic").fetchall()
                version = db.execute("PRAGMA user_version").fetchone()[0]
            self.assertEqual(rows, [
                ("T", "https://example.com/a", "2026-11-02T00:00:00+00:00", None),
                ("U", "https://example.com/a", "2026-11-04T00:00:00+00:00", None),
            ])
            self.assertEqual(version, watcher.SEEN_SCHEMA_VERSION)

    def test_max_item_age_skips_old_dated_items_but_keeps_undated_ones(self):
        now = datetime.now(timezone.utc)
        old = watcher.Item("F", "Hound old", "https://example.com/old", "", "", published_at=watcher.utc_timestamp(now - timedelta(days=10)))
        new = watcher.Item("F", "Hound new", "https://example.com/new", "", "", published_at=watcher.utc_timestamp(now - timedelta(days=1)))
        undated = watcher.Item("F", "Hound undated", "https://example.com/undated", "", "")
        with (
            tempfile.TemporaryDirectory() as directory,
            closing(watcher.SeenStore(Path(directory) / "watcher.db")) as store,
        ):
            check = watcher.Watcher([FakeSource("f", [old, new, undated])], [watcher.Topic("T", ["hound"], [])],
                                    store, watcher.Settings(max_item_age_days=7))
            result = check.collect()
        self.assertEqual([m.item.link for m in result.matches], ["https://example.com/new", "https://example.com/undated"])


class ItemStateTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "watcher.db"
        self.store = watcher.SeenStore(self.path)
        self.addCleanup(self.store.close)
        item = story("https://example.com/a", "A")
        self.store.mark_seen([watcher.Match("T", item, ()), watcher.Match("U", item, ())])

    def state(self):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute("SELECT link, read_at IS NOT NULL, starred_at IS NOT NULL FROM item_state").fetchall()

    def test_state_is_per_article_and_unknown_links_are_ignored(self):
        self.store.set_item_state(["https://example.com/a", "https://example.com/unknown"], read=True, starred=None)
        self.assertEqual(self.state(), [("https://example.com/a", 1, 0)])
        self.store.set_item_state(["https://example.com/a"], read=None, starred=True)
        self.assertEqual(self.state(), [("https://example.com/a", 1, 1)])
        self.store.set_item_state(["https://example.com/a"], read=False, starred=False)
        self.assertEqual(self.state(), [], "a row with neither flag is removed")

    def test_retention_keeps_starred_articles(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE seen SET first_seen = '2020-01-01T00:00:00+00:00'")
            db.commit()
        self.store.mark_seen([watcher.Match("T", story("https://example.com/b", "B"), ())])
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE seen SET first_seen = '2020-01-01T00:00:00+00:00'")
            db.commit()
        self.store.set_item_state(["https://example.com/a"], read=True, starred=True)
        self.store.set_item_state(["https://example.com/b"], read=True, starred=None)

        self.assertEqual(self.store.prune(30), 1)
        self.assertTrue(self.store.contains("T", "https://example.com/a"))
        self.assertFalse(self.store.contains("T", "https://example.com/b"))
        self.assertEqual(self.state(), [("https://example.com/a", 1, 1)], "state of pruned articles goes too")


class RecordingSource(FakeSource):
    """Answers like a server with validators: 304 when sent the current ETag."""

    def __init__(self, name, items, etag="v1", check_every_minutes=None):
        super().__init__(name, items)
        self.etag = etag
        self.check_every_minutes = check_every_minutes
        self.sent = []

    def fetch(self, settings, validators):
        self.sent.append(validators.etag)
        if validators.etag == self.etag:
            return feed_response([], validators.etag, validators.last_modified, not_modified=True)
        return feed_response(self._items, self.etag)


class PoliteFetchingTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = watcher.SeenStore(Path(directory.name) / "watcher.db")
        self.addCleanup(self.store.close)
        self.topics = [watcher.Topic("T", ["hound*"], [])]

    def check(self, sources, topics=None, save=True):
        with redirect_stderr(io.StringIO()):
            result = watcher.Watcher(sources, topics or self.topics, self.store, watcher.Settings()).collect(
                self.store.feed_states()
            )
        (self.store.save_check if save else self.store.save_backoff)(result)
        return result

    def test_validators_are_sent_after_a_saved_check_and_304_finds_nothing(self):
        source = RecordingSource("a", [story("https://example.com/1", "Hound one")])
        self.assertEqual(len(self.check([source]).matches), 1)
        second = self.check([source])
        self.assertEqual(source.sent, ["", "v1"])
        self.assertEqual((second.matches, second.source_results[0].not_modified), ((), True))
        self.assertEqual(dict(second.fetched_items), {}, "a 304 does not replace the tester's cached items")

    def test_a_preview_never_moves_the_validators(self):
        source = RecordingSource("a", [story("https://example.com/1", "Hound one")])
        self.check([source], save=False)
        saved = self.check([source])
        self.assertEqual(source.sent, ["", ""])
        self.assertEqual(len(saved.matches), 1, "the saved check still sees what the preview saw")

    def test_changed_topics_ignore_old_validators(self):
        source = RecordingSource("a", [story("https://example.com/1", "Hound one"), story("https://example.com/2", "Fox two")])
        self.check([source])
        result = self.check([source], topics=[watcher.Topic("Fox", ["fox"], [])])
        self.assertEqual(source.sent, ["", ""])
        self.assertEqual([m.item.link for m in result.matches], ["https://example.com/2"])

    def test_feeds_with_an_interval_are_skipped_until_due(self):
        source = RecordingSource("a", [], check_every_minutes=60)
        self.check([source])
        result = self.check([source])
        self.assertEqual(source.sent, [""])
        self.assertEqual([skip.name for skip in result.skipped], ["a"])
        self.assertIn("checked every 60 min", result.skipped[0].reason)

    def test_rate_limited_feeds_back_off_even_after_a_preview(self):
        retry_at = datetime.now(timezone.utc) + timedelta(minutes=10)
        limited = FakeSource("a", error=watcher.RateLimited(429, retry_at))
        first = self.check([limited], save=False)
        self.assertIn("HTTP Error 429", first.source_results[0].error)
        second = self.check([limited], save=False)
        self.assertEqual((second.source_results, [skip.name for skip in second.skipped]), ((), ["a"]))

    def test_previews_store_nothing_but_backoff(self):
        self.check([RecordingSource("a", [])], save=False)
        self.assertEqual(self.store.feed_states(), {}, "no row for a feed without backoff")

        self.check([RecordingSource("a", [])])
        self.check([RecordingSource("a", [])], save=False)
        self.assertEqual(self.store.feed_states()["https://example.com/a.xml"].etag, "v1")

    def test_overlapping_checks_cannot_rewind_validators_or_backoff(self):
        source = RecordingSource("a", [])
        url = source.url
        result = watcher.Watcher([source], self.topics, self.store, watcher.Settings()).collect()
        older = "2024-01-02T10:00:00.000001+00:00"
        newer = "2024-01-02T10:00:00.000002+00:00"
        old_success = replace(result, checked_at=older, feed_updates={
            url: replace(result.feed_updates[url], saved_at=older, etag="old")
        })
        new_success = replace(result, checked_at=newer, feed_updates={
            url: replace(result.feed_updates[url], saved_at=newer, etag="new")
        })
        old_backoff = replace(old_success, feed_updates={}, retry_updates={url: "2024-01-02T10:10:00+00:00"})
        self.store.save_check(new_success)
        self.store.save_check(old_success)
        self.store.save_backoff(old_backoff)
        self.assertEqual(self.store.feed_states()[url], new_success.feed_updates[url])

        new_backoff = replace(old_backoff, checked_at="2024-01-02T10:00:00.000003+00:00")
        self.store.save_backoff(new_backoff)
        self.store.save_check(new_success)
        self.assertEqual(self.store.feed_states()[url],
                         replace(new_success.feed_updates[url], retry_at=new_backoff.retry_updates[url]))

    def test_old_database_preserves_validators_and_backoff_when_upgraded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "watcher.db"
            state = ("etag", "last-modified", "fingerprint", "2024-01-02T10:00:00+00:00", "2024-01-02T10:10:00+00:00")
            url = "https://example.com/feed"
            with closing(sqlite3.connect(path)) as db, db:
                db.execute(
                    "CREATE TABLE feed_state (url TEXT PRIMARY KEY, etag TEXT NOT NULL, last_modified TEXT NOT NULL, "
                    "fingerprint TEXT NOT NULL, saved_at TEXT NOT NULL, retry_at TEXT NOT NULL)"
                )
                db.execute("INSERT INTO feed_state VALUES (?, ?, ?, ?, ?, ?)", (url, *state))
                db.execute("PRAGMA user_version = 1")
            with closing(watcher.SeenStore(path)) as store:
                self.assertEqual(store.feed_states()[url], watcher.FeedState(*state))
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], watcher.SEEN_SCHEMA_VERSION)

    def test_unreadable_saved_state_means_due(self):
        source = RecordingSource("a", [], check_every_minutes=60)
        state = {"https://example.com/a.xml": watcher.FeedState(saved_at="yesterday-ish")}
        self.assertEqual(watcher.skip_reason(source, state[source.url], datetime.now(timezone.utc)), "")

    def test_retry_after_accepts_seconds_or_a_date_and_is_capped(self):
        now = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(watcher.retry_time("120", now), now + timedelta(seconds=120))
        self.assertEqual(watcher.retry_time("Sun, 22 Nov 2026 12:30:00 GMT", now), now + timedelta(minutes=30))
        self.assertEqual(watcher.retry_time("999999", now), now + watcher.MAX_BACKOFF)
        self.assertEqual(watcher.retry_time(None, now), now + watcher.DEFAULT_BACKOFF)


class HttpFetchTests(unittest.TestCase):
    class Response(io.BytesIO):
        def __init__(self, body, headers=None):
            super().__init__(body)
            self.headers = headers or {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    RSS = b"<rss><channel><item><title>T</title><link>https://example.com/a</link></item></channel></rss>"

    def test_validators_are_sent_and_returned(self):
        captured = {}

        def fake_open(request, timeout):
            captured.update(request.header_items())
            return self.Response(self.RSS, {"ETag": '"abc"', "Last-Modified": "Sun, 22 Nov 2026 12:00:00 GMT"})

        with patch.object(watcher.OPENER, "open", side_effect=fake_open):
            response = watcher.Source("A", "https://example.com/feed").fetch(
                watcher.Settings(), watcher.FeedState(etag='"old"', last_modified="Sat, 21 Nov 2026 12:00:00 GMT")
            )
        self.assertEqual((captured["If-none-match"], captured["If-modified-since"], captured["Accept-encoding"]),
                         ('"old"', "Sat, 21 Nov 2026 12:00:00 GMT", "gzip"))
        self.assertEqual((response.etag, response.last_modified, len(response.items)),
                         ('"abc"', "Sun, 22 Nov 2026 12:00:00 GMT", 1))

    def test_304_is_not_modified(self):
        not_modified = urllib.error.HTTPError("https://example.com/feed", 304, "Not Modified", {}, None)
        with patch.object(watcher.OPENER, "open", side_effect=not_modified):
            response = watcher.Source("A", "https://example.com/feed").fetch(watcher.Settings(), watcher.FeedState(etag='"v"'))
        self.assertEqual((response.not_modified, response.items, response.etag), (True, [], '"v"'))

    def test_429_raises_rate_limited_with_retry_after(self):
        limited = urllib.error.HTTPError("https://example.com/feed", 429, "Too Many Requests", {"Retry-After": "60"}, None)
        with patch.object(watcher.OPENER, "open", side_effect=limited):
            with self.assertRaises(watcher.RateLimited) as caught:
                watcher.Source("A", "https://example.com/feed").fetch(watcher.Settings())
        delay = caught.exception.retry_at - datetime.now(timezone.utc)
        self.assertTrue(timedelta(seconds=50) < delay <= timedelta(seconds=60))

    def test_gzip_bodies_are_inflated_within_the_size_limit(self):
        body = gzip.compress(self.RSS)
        with patch.object(watcher.OPENER, "open", return_value=self.Response(body, {"Content-Encoding": "gzip"})):
            response = watcher.Source("A", "https://example.com/feed").fetch(watcher.Settings())
        self.assertEqual(len(response.items), 1)

        bomb = gzip.compress(b"<rss>" + b" " * 2_000_000 + b"</rss>")
        with patch.object(watcher.OPENER, "open", return_value=self.Response(bomb, {"Content-Encoding": "gzip"})):
            with self.assertRaisesRegex(ValueError, "when decompressed"):
                watcher.Source("A", "https://example.com/feed").fetch(watcher.Settings(max_feed_megabytes=1))

    def test_health_reports_an_unchanged_feed_as_ok(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            closing(watcher.CheckLog(Path(directory) / "watcher.db")) as log,
        ):
            result = watcher.SourceResult("A", "https://a.example/feed", True, "", 0, 0, 5, not_modified=True)
            log.record("2026-11-22T10:00:00+00:00", 5, "cli", True, 0, 0, [result])
            [health] = log.source_health([("A", "https://a.example/feed")])
        self.assertEqual((health["status"], health["not_modified"]), ("ok", True))


class EventExportTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "watcher.db"
        self.exports = watcher.export_directory(self.path)
        self.store = watcher.SeenStore(self.path)
        self.log = watcher.CheckLog(self.path)
        self.export = watcher.EventExport(self.path, self.exports)
        for resource in (self.store, self.log, self.export):
            self.addCleanup(resource.close)
        self.topics = (watcher.Topic("T", ["hound*"], []), watcher.Topic("U", ["one"], []))

    def check(self, sources, save=True, settings=watcher.Settings(), trigger="cli"):
        config = watcher.Config(tuple(sources), self.topics, settings)
        with redirect_stderr(io.StringIO()):
            return watcher.perform_check(config, self.store, self.log, self.export, save, trigger)

    def records(self):
        lines = [
            line
            for path in sorted(self.exports.glob("hounddog-*.jsonl"))
            for line in path.read_text(encoding="utf-8").splitlines()
        ]
        return [json.loads(line) for line in lines]

    def test_a_saved_check_exports_its_coverage_and_one_event_per_article(self):
        feed = FakeSource("a", [story("https://example.com/1", "Hound one"), story("https://example.com/2", "Cat")])
        broken = FakeSource("b", error=OSError("offline"))
        self.check([feed, broken])

        coverage, event = self.records()
        [check] = self.log.recent(1)
        self.assertEqual((coverage["schema"], coverage["check_id"]), (watcher.COVERAGE_SCHEMA, check["id"]))
        self.assertEqual(
            [(feed["name"], feed["status"], feed["items"], feed["new_matches"]) for feed in coverage["feeds"]],
            [("a", "ok", 2, 2), ("b", "failed", 0, 0)],
        )
        self.assertEqual(coverage["feeds"][1]["detail"], "offline")
        self.assertEqual(event["schema"], watcher.EVENT_SCHEMA)
        self.assertEqual(event["event_id"], watcher.event_id("https://example.com/1"))
        self.assertEqual(event["run_id"], coverage["run_id"])
        self.assertEqual(
            [(topic["name"], topic["keywords"], topic["feed_url"], topic["backfill"]) for topic in event["topics"]],
            [("T", ["hound*"], feed.url, True), ("U", ["one"], feed.url, True)],
        )
        self.assertEqual([topic["name"] for topic in coverage["topics"]], ["T", "U"])
        self.assertTrue(all(topic["fingerprint"] for topic in coverage["topics"]))
        self.assertEqual((event["feed_url"], event["released_at"], event["backfill"]), (feed.url, None, True))
        with closing(sqlite3.connect(self.path)) as db:
            first_seen = db.execute("SELECT DISTINCT first_seen FROM seen").fetchall()
        self.assertEqual(first_seen, [(event["detected_at"],)], "detected_at is History's first_seen")
        self.assertTrue(self.exports.joinpath(f"hounddog-{coverage['started_at'][:10]}.jsonl").exists())

        feed._items.append(story("https://example.com/3", "Hound three"))
        self.check([feed], save=False)
        self.assertEqual(len(self.records()), 2, "previews export nothing")
        self.check([feed])
        *_, later_coverage, later_event = self.records()
        self.assertEqual(later_event["link"], "https://example.com/3")
        self.assertFalse(later_event["backfill"], "the feed was already read under these topics")
        self.assertEqual(later_coverage["check_id"], later_event["check_id"])

    def test_scheduled_notification_summarizes_distinct_articles_after_the_save(self):
        feed = FakeSource("a", [story("https://example.com/1", "Hound one")])
        settings = watcher.Settings(notification_enabled=True, notification_min_articles=2, notification_sound=False)

        def delivered(path, trigger, title, lines, **options):
            self.assertTrue(self.store.contains("T", "https://example.com/3"))
            self.assertEqual((path, trigger, title), (self.path, "scheduled", "HoundDog"))
            self.assertEqual(lines, ("2 articles · 3 matches", "T 2 · U 1"))
            self.assertEqual(options, {"sound": False, "banner": True})
            return {"state": "submitted"}

        with (
            patch.object(watcher.windows_notifications, "supported", return_value=True),
            patch.object(watcher.windows_notifications, "send", side_effect=delivered) as send,
        ):
            backfill = self.check([feed], settings=settings, trigger="scheduled")
            self.assertEqual(backfill.notification["message"], "Only backfill matches were found.")
            feed._items.append(story("https://example.com/2", "Hound two"))
            below = self.check([feed], settings=settings, trigger="scheduled")
            self.assertEqual(below.notification["state"], "skipped")
            feed._items.extend([
                story("https://example.com/3", "Hound one returns"),
                story("https://example.com/4", "Hound four"),
            ])
            self.assertIsNone(self.check([feed], save=False, settings=settings, trigger="auto").notification)
            send.assert_not_called()
            result = self.check([feed], settings=settings, trigger="scheduled")
            self.assertEqual(result.notification["state"], "submitted")
            self.check([feed], settings=settings, trigger="scheduled")
            send.assert_called_once()

    def test_native_manual_notifications_are_opt_in_and_can_include_backfill(self):
        feed = FakeSource("a", [story("https://example.com/1", "Hound one")])
        settings = watcher.Settings(notification_enabled=True)
        with (
            patch.object(watcher.windows_notifications, "supported", return_value=True),
            patch.object(watcher.windows_notifications, "send", return_value={"state": "failed"}) as send,
        ):
            self.assertIsNone(self.check([feed], settings=settings).notification)
            send.assert_not_called()
            second = FakeSource("b", [story("https://example.com/2", "Hound two")])
            result = self.check([second], settings=watcher.Settings(
                notification_enabled=True, notification_include_backfill=True, notification_manual_checks=True,
            ), trigger="dashboard")
            send.assert_called_once()
            self.assertEqual(result.notification["state"], "failed")
            self.assertTrue(self.store.contains("T", "https://example.com/2"))

    def test_first_seen_headline_and_date_stay_and_changes_become_revisions(self):
        def version(title, published_at, summary=""):
            return watcher.Item("Feed", title, "https://example.com/1", summary, published_at, published_at=published_at)

        feed = FakeSource("a", [version("Hound one", "2026-11-22T10:00:00+00:00")])
        self.check([feed])
        feed._items = [version("Hound one, updated", "2026-11-22T11:00:00+00:00", "Now with a summary")]
        self.check([feed])
        self.check([feed])

        with closing(sqlite3.connect(self.path)) as db:
            rows = db.execute("SELECT DISTINCT title, published_at, summary FROM seen").fetchall()
        self.assertEqual(rows, [("Hound one", "2026-11-22T10:00:00+00:00", "Now with a summary")],
                         "first-seen values stay; blanks are filled")
        [revision] = [record for record in self.records() if record["schema"] == watcher.REVISION_SCHEMA]
        coverage = next(record for record in self.records()
                        if record["schema"] == watcher.COVERAGE_SCHEMA and record["check_id"] == revision["check_id"])
        self.assertEqual(revision["run_id"], coverage["run_id"])
        self.assertEqual(revision["changed"], ["title", "released_at"])
        self.assertEqual((revision["title"], revision["released_at"]), ("Hound one, updated", "2026-11-22T11:00:00+00:00"))
        self.assertEqual((revision["previous_title"], revision["previous_released_at"]),
                         ("Hound one", "2026-11-22T10:00:00+00:00"))

    def test_records_that_cannot_be_written_wait_for_the_next_check(self):
        self.exports.write_text("not a folder", encoding="utf-8")
        feed = FakeSource("a", [story("https://example.com/1", "Hound one")])
        outcome = self.check([feed])
        self.assertIn("queued for the next saved check", outcome.export_error)
        self.assertEqual(self.export.pending(), 2)

        self.exports.unlink()
        self.assertEqual(self.check([feed]).export_error, "")
        self.assertEqual([record["schema"] for record in self.records()],
                         [watcher.COVERAGE_SCHEMA, watcher.EVENT_SCHEMA, watcher.COVERAGE_SCHEMA])
        self.assertEqual(self.export.pending(), 0)

    def test_queue_failure_rolls_back_history_and_log_until_the_retry(self):
        link = "https://example.com/1"
        feed = FakeSource("a", [story(link, "Hound")])
        with patch.object(self.export, "queue", side_effect=sqlite3.OperationalError("queue failed")):
            with self.assertRaisesRegex(sqlite3.OperationalError, "queue failed"):
                self.check([feed])
        self.assertFalse(self.store.contains("T", link))
        self.assertEqual(self.store.feed_states(), {})
        self.assertEqual(self.log.recent(1), [])
        self.check([feed])
        self.assertEqual([record["schema"] for record in self.records()],
                         [watcher.COVERAGE_SCHEMA, watcher.EVENT_SCHEMA])

    def test_clear_history_discards_checks_that_started_before_the_reset(self):
        link = "https://example.com/1"
        feed = RecordingSource("a", [story(link, "Hound one")])
        self.check([feed])
        original_collect = watcher.Watcher.collect

        def finish_after_reset(watcher_instance, feed_states):
            result = original_collect(watcher_instance, feed_states)
            self.assertTrue(result.seen_updates)
            with closing(watcher.SeenStore(self.path)) as resetter:
                resetter.clear_history()
            return result

        for version, save in enumerate((True, False), start=2):
            feed.etag = f"v{version}"
            with patch.object(watcher.Watcher, "collect", finish_after_reset):
                self.assertTrue(self.check([feed], save=save).history_reset)
            self.assertFalse(self.store.contains("T", link))
            self.assertEqual(self.store.feed_states()[feed.url].etag, "")
            self.assertEqual(len(self.records()), 2 * (version - 1))
            self.assertTrue(self.check([feed]).result.matches)

    def test_retry_repairs_a_partial_line_without_changing_complete_records(self):
        self.exports.mkdir()
        export_path = self.exports / "hounddog-2024-01-02.jsonl"
        complete = b'{"check_id":1}\n'
        export_path.write_bytes(complete + b'{"check_id":')
        self.export.queue("2024-01-02", [{"check_id": 2}])
        self.assertEqual(self.export.flush(), 1)
        self.assertTrue(export_path.read_bytes().startswith(complete))
        self.assertEqual(self.records(), [{"check_id": 1}, {"check_id": 2}])

    def test_event_uses_the_feed_that_matched_and_its_backfill_status(self):
        link = "https://example.com/shared"
        first = FakeSource("first", [story(link, "Cat")])
        self.check([first])
        second = FakeSource("second", [watcher.Item("second", "Hound", link, "", "")])
        self.check([first, second])
        [event] = [record for record in self.records() if record["schema"] == watcher.EVENT_SCHEMA]
        self.assertEqual((event["source"], event["feed_url"], event["backfill"]), ("second", second.url, True))

    def test_export_run_ids_survive_resetting_the_check_log_database(self):
        feed = FakeSource("a", [story("https://example.com/1", "Hound one")])
        self.check([feed])
        fresh_path = self.path.with_name("fresh.db")
        config = watcher.Config((feed,), self.topics, watcher.Settings())
        with (
            closing(watcher.SeenStore(fresh_path)) as store,
            closing(watcher.CheckLog(fresh_path)) as log,
            closing(watcher.EventExport(fresh_path, self.exports)) as export,
        ):
            watcher.perform_check(config, store, log, export, True, "cli")
        events = [record for record in self.records() if record["schema"] == watcher.EVENT_SCHEMA]
        self.assertEqual([record["check_id"] for record in events], [1, 1])
        self.assertEqual(len({record["run_id"] for record in events}), 2)

    def test_a_busy_database_delays_the_export_without_failing_the_check(self):
        feed = FakeSource("a", [story("https://example.com/1", "Hound one")])
        with patch.object(watcher.EventExport, "flush", side_effect=sqlite3.OperationalError("database is locked")):
            outcome = self.check([feed])
        self.assertIn("database is locked", outcome.export_error)
        self.assertTrue(self.store.contains("T", "https://example.com/1"), "the check itself was saved")
        self.check([feed])
        self.assertEqual(
            [record["schema"] for record in self.records()],
            [watcher.COVERAGE_SCHEMA, watcher.EVENT_SCHEMA, watcher.COVERAGE_SCHEMA],
            "the delayed records are written by the next check",
        )

    def test_a_new_topic_on_a_retitled_article_records_the_revision(self):
        self.check([FakeSource("a", [story("https://example.com/1", "Hound")])])
        # The new headline no longer matches T, so only the new topic sees it.
        self.topics = (*self.topics, watcher.Topic("V", ["retitled"], []))
        self.check([FakeSource("a", [story("https://example.com/1", "Story retitled")])])
        [revision] = [record for record in self.records() if record["schema"] == watcher.REVISION_SCHEMA]
        self.assertEqual((revision["previous_title"], revision["title"]), ("Hound", "Story retitled"))

    def test_line_separators_inside_text_do_not_split_records(self):
        self.check([FakeSource("a", [story("https://example.com/1", "Hound\u2028one\u2029two")])])
        path = next(self.exports.glob("hounddog-*.jsonl"))
        text = path.read_text(encoding="utf-8")
        self.assertEqual(len(text.splitlines()), 2)
        self.assertEqual(json.loads(text.splitlines()[1])["title"], "Hound\u2028one\u2029two")

    def test_the_export_can_be_turned_off(self):
        self.check([FakeSource("a", [story("https://example.com/1", "Hound one")])],
                   settings=watcher.Settings(event_export=False))
        self.assertFalse(self.exports.exists())
        with self.assertRaisesRegex(watcher.ConfigError, "event_export"):
            watcher.Settings.from_table({"event_export": "yes"})


if __name__ == "__main__":
    unittest.main()
