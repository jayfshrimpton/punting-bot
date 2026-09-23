import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError, URLError

from punting.core import Invalid
from punting.store import Store
from punting.research import access
from punting.research.access import cache_text, fetch, readable, robots_allows, robots_for, robots_rules
from punting.research.digest import page, render
from punting.research.evidence import Notes, build, check_pack, horse_key, import_pack, resolve, verify
from punting.research.weather import forecast_docs, parse

CONFIG = json.loads(Path("config.json").read_text())
MID = "rosehill-2026-09-26"
MEETING = next(m for m in CONFIG["meetings"] if m["id"] == MID)
OBS = "2026-09-23T00:00:00+00:00"
READ = "2026-09-23T01:00:00+00:00"
ARTICLE = ("Golden Rose preview\nTrainer Chris Waller said St Gotthard's trial was sharp and he looks ready for the step up to 1400 metres. "
           "Meanwhile Surfin' Bird drew wide and faces a tough run from barrier 14 in the Golden Pendant. "
           + "Filler text about the rest of the card and the weather. " * 30
           + "Campione D'Italia is the stable's forgotten runner and could be a value play if the track stays soft.")
BOM = b"""<?xml version="1.0"?><product><amoc><identifier>IDN11060</identifier><issue-time-utc>2026-09-23T06:00:00Z</issue-time-utc>
<status>O</status><product-type>F</product-type></amoc><forecast>
<area aac="NSW_PT111" description="Parramatta" type="location">
<forecast-period index="0" start-time-local="2026-09-23T16:00:00+10:00"><text type="precis">Partly cloudy.</text><text type="probability_of_precipitation">30%</text></forecast-period>
<forecast-period index="1" start-time-local="2026-09-24T00:00:00+10:00"><element type="air_temperature_maximum" units="Celsius">25</element><text type="precis">Partly cloudy.</text><text type="probability_of_precipitation">20%</text></forecast-period>
<forecast-period index="3" start-time-local="2026-09-26T00:00:00+10:00"><element type="air_temperature_maximum" units="Celsius">34</element><text type="precis">Mostly sunny.</text><text type="probability_of_precipitation">20%</text></forecast-period>
</area><area aac="NSW_PT132" description="Sydney Olympic Park" type="location">
<forecast-period index="1" start-time-local="2026-09-24T00:00:00+10:00"><element type="air_temperature_maximum" units="Celsius">25</element><text type="precis">Sunny.</text></forecast-period>
</area></forecast></product>"""


def field(observed=OBS, race=1, runners=None, start="2026-09-26T12:00:00+10:00"):
    runners = runners or [{"id": "ra:1", "name": "ST GOTTHARD", "number": "1", "status": "active"},
                          {"id": "ra:2", "name": "SURFIN’ BIRD", "number": "2", "status": "active"},
                          {"id": "ra:3", "name": "CAMPIONE D’ITALIA", "number": "3", "status": "active"},
                          {"id": "ra:4", "name": "MR BRIGHTSIDE (NZ)", "number": "4", "status": "active"}]
    return {"kind": "field", "meeting_id": MID, "race_no": race, "source_url": "https://example.com/field", "publisher": "Synthetic official field",
            "observed_at": observed, "published_at": None,
            "payload": {"race_name": "Synthetic (1400 METRES)", "start_at": start, "runners": runners, "going": "Soft 5", "rail": "True", "official": True, "card_races": 2}}


class Response:
    def __init__(self, body, status=200, final=None, kind="text/html; charset=utf-8"):
        self.body, self.status, self.final, self.headers = body.encode() if isinstance(body, str) else body, status, final, {"Content-Type": kind}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, n=-1):
        return self.body

    def geturl(self):
        return self.final


def opener(routes):
    """Fake urlopen: routes maps URL -> body, exception or Response."""
    def fake(request, timeout=None):
        u = request.full_url
        value = routes.get(u)
        if value is None:
            raise AssertionError("Unexpected network request " + u)
        if isinstance(value, Exception):
            raise value
        return value if isinstance(value, Response) else Response(value, final=u)
    return fake


class RobotsTests(unittest.TestCase):
    def test_same_agent_groups_merge_like_bom(self):
        body = "User-agent: R6_FeedFetcher\nDisallow: /\n\nUser-agent: *\nDisallow: /fwo/\n\nUser-agent: *\nDisallow: /core/\nAllow: /core/*.css$\n"
        rules = robots_rules(body)
        self.assertFalse(robots_allows(rules, "/fwo/IDN11060.xml"))
        self.assertFalse(robots_allows(rules, "/core/x.js"))
        self.assertTrue(robots_allows(rules, "/core/site.css"))
        self.assertFalse(robots_allows(rules, "/core/site.css?v=1"))
        self.assertTrue(robots_allows(rules, "/places/nsw/"))

    def test_disallow_all_with_specific_allows_like_punters(self):
        rules = robots_rules("User-agent: AhrefsBot\nCrawl-Delay: 10\nDisallow: /search\n\nUser-agent: *\nAllow: /ads.txt\nDisallow: /\n")
        self.assertFalse(robots_allows(rules, "/form-guide/horse-racing/rosehill/"))
        self.assertTrue(robots_allows(rules, "/ads.txt"))
        self.assertTrue(robots_allows(rules, "/robots.txt"))
        self.assertIsNone(rules["delay"])

    def test_longest_match_tie_wildcards_and_own_group(self):
        rules = robots_rules("User-agent: *\nDisallow: /a\nAllow: /a/b\nDisallow: /*.pdf$\nAllow: /x\nDisallow: /x\n")
        self.assertTrue(robots_allows(rules, "/a/b/c"))
        self.assertFalse(robots_allows(rules, "/a/c"))
        self.assertFalse(robots_allows(rules, "/files/form.pdf"))
        self.assertTrue(robots_allows(rules, "/files/form.pdf?download=1"))
        self.assertTrue(robots_allows(rules, "/x"))
        own = robots_rules("User-agent: *\nDisallow: /\n\nUser-agent: puntingpowerai\nDisallow: /private\n")
        self.assertTrue(robots_allows(own, "/news"))
        self.assertFalse(robots_allows(own, "/private/x"))

    def test_status_handling(self):
        access._robots.clear()
        missing = robots_for("https://a.example", opener({"https://a.example/robots.txt": HTTPError("u", 404, "nf", {}, None)}))
        self.assertTrue(robots_allows(missing, "/anything"))
        down = robots_for("https://b.example", opener({"https://b.example/robots.txt": HTTPError("u", 503, "down", {}, None)}))
        self.assertFalse(robots_allows(down, "/anything"))
        gone = robots_for("https://c.example", opener({"https://c.example/robots.txt": URLError("dns")}))
        self.assertFalse(robots_allows(gone, "/anything"))
        access._robots.clear()


class FetchTests(unittest.TestCase):
    def setUp(self):
        access._robots.clear(); access._last.clear()
        self.temp = tempfile.TemporaryDirectory(); self.cache = Path(self.temp.name) / "pages"

    def tearDown(self):
        access._robots.clear(); self.temp.cleanup()

    def test_browser_and_manual_sources_never_fetched(self):
        for u in ["https://www.punters.com.au/news/x", "https://www.justhorseracing.com.au/news/x", "https://wolfden.bet/tips", "https://unknown.example/x"]:
            with self.assertRaises(Invalid):
                fetch(u, self.cache, opener({}), pause=lambda s: None)

    def test_robots_disallowed_path_refused(self):
        routes = {"https://thedailypunt.com.au/robots.txt": "User-agent: *\nAllow: /\nDisallow: /api/\n"}
        with self.assertRaises(Invalid):
            fetch("https://thedailypunt.com.au/api/tips", self.cache, opener(routes), pause=lambda s: None)

    def test_capture_strips_scripts_keeps_article_and_next_data(self):
        body = ('<html><head><title>Rosehill tips</title><script>var secret="tracking"</script></head><body><p>St Gotthard looks ready.</p>'
                '<script id="__NEXT_DATA__" type="application/json">{"props":{"body":"<p>Warwoven has the inside draw and should lead</p>"}}</script></body></html>')
        routes = {"https://thedailypunt.com.au/robots.txt": "User-agent: *\nDisallow: /api/\n", "https://thedailypunt.com.au/news/rosehill": body}
        rec = fetch("https://thedailypunt.com.au/news/rosehill", self.cache, opener(routes), pause=lambda s: None)
        text = (self.cache / f"{rec['text_sha256']}.txt").read_text(encoding="utf-8")
        self.assertEqual(rec["title"], "Rosehill tips"); self.assertEqual(rec["source"], "The Daily Punt")
        self.assertIn("St Gotthard looks ready.", text); self.assertIn("Warwoven has the inside draw", text); self.assertNotIn("tracking", text)

    def test_cross_host_redirect_and_http_errors(self):
        routes = {"https://thedailypunt.com.au/robots.txt": "User-agent: *\nAllow: /\n",
                  "https://thedailypunt.com.au/go": Response("x", final="https://bookmaker.example/offer"),
                  "https://thedailypunt.com.au/missing": HTTPError("u", 404, "nf", {}, None)}
        with self.assertRaises(Invalid):
            fetch("https://thedailypunt.com.au/go", self.cache, opener(routes), pause=lambda s: None)
        with self.assertRaisesRegex(Invalid, "not evidence that nothing was published"):
            fetch("https://thedailypunt.com.au/missing", self.cache, opener(routes), pause=lambda s: None)

    def test_cache_detects_tampering(self):
        sha = cache_text("Original page text " * 5, self.cache)
        (self.cache / f"{sha}.txt").write_text("edited", encoding="utf-8")
        with self.assertRaises(Invalid):
            cache_text("Original page text " * 5, self.cache)


class NameAndVerificationTests(unittest.TestCase):
    RUNNERS = field()["payload"]["runners"]

    def test_apostrophes_suffixes_and_numbers(self):
        self.assertEqual(resolve("Campione D'Italia", self.RUNNERS)["id"], "ra:3")
        self.assertEqual(resolve("surfin bird", self.RUNNERS)["id"], "ra:2")
        self.assertEqual(resolve("Mr Brightside", self.RUNNERS)["id"], "ra:4")
        self.assertEqual(resolve("Mr Brightside (NZ)", self.RUNNERS)["id"], "ra:4")
        self.assertEqual(resolve({"name": "St Gotthard", "number": "1"}, self.RUNNERS)["id"], "ra:1")
        for bad in ["Mr Brightside (GB)", "Gotthard", {"name": "St Gotthard", "number": "2"}, "Warwoven"]:
            with self.assertRaises(Invalid):
                resolve(bad, self.RUNNERS)

    def test_ambiguous_base_name_needs_suffix(self):
        runners = [{"id": "x", "name": "STAR (NZ)", "number": "1", "status": "active"}, {"id": "y", "name": "STAR (GB)", "number": "2", "status": "active"}]
        with self.assertRaisesRegex(Invalid, "Ambiguous"):
            resolve("Star", runners)
        self.assertEqual(resolve("Star (GB)", runners)["id"], "y")
        self.assertEqual(horse_key("SMOKIN’ ROMANS (NZ)"), horse_key("Smokin' Romans"))

    def test_verbatim_excerpt_and_wrong_horse(self):
        verify(ARTICLE, "trial was sharp and he looks ready", ["ST GOTTHARD"])  # possessive St Gotthard's
        verify(ARTICLE, "faces a tough   run from barrier 14", ["SURFIN’ BIRD"])  # whitespace and curly apostrophe
        with self.assertRaisesRegex(Invalid, "not found verbatim"):
            verify(ARTICLE, "trial was brilliant and he will win", ["ST GOTTHARD"])
        with self.assertRaisesRegex(Invalid, "wrong-horse"):
            verify(ARTICLE, "could be a value play if the track stays soft", ["ST GOTTHARD"])
        verify(ARTICLE, "could be a value play if the track stays soft", ["CAMPIONE D’ITALIA"])
        with self.assertRaises(Invalid):
            verify(ARTICLE, "", ["ST GOTTHARD"])


class PackBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); root = Path(self.temp.name)
        self.store, self.notes, self.cache = Store(root / "data"), Notes(root / "data"), root / "data" / "private" / "pages"
        self.store.add(field(), CONFIG)
        self.sha = cache_text(ARTICLE, self.cache)
        self.root = root

    def tearDown(self):
        self.store.close(); self.notes.close(); self.temp.cleanup()

    def pack(self):
        page = {"id": "p1", "source": "Racing.com", "url": "https://www.racing.com/news/golden-rose-preview", "publisher": "Racing.com", "author": "A Writer",
                "title": "Golden Rose preview", "published_at": "2026-09-22T23:00:00+00:00", "observed_at": READ, "route": "http", "text_sha256": self.sha}
        claims = [{"page": "p1", "race_no": 1, "runners": ["St Gotthard"], "type": "attributed statement", "stance": "positive", "topic": "fitness",
                   "summary": "Waller reports a sharp trial and readiness for 1400m.", "excerpt": "trial was sharp and he looks ready", "conditions": [], "author": "Chris Waller"},
                  {"page": "p1", "race_no": 1, "runners": ["Campione D'Italia"], "type": "opinion", "stance": "positive", "topic": "selection", "tip": "value",
                   "summary": "Writer names it a value play.", "excerpt": "could be a value play if the track stays soft", "conditions": ["track stays soft"]},
                  {"page": "p1", "race_no": 1, "runners": ["Surfin Bird"], "type": "opinion", "stance": "negative", "topic": "barrier",
                   "summary": "Wide draw is a concern.", "excerpt": "faces a tough run from barrier 14", "conditions": []}]
        coverage = [{"source": "Racing.com", "race_no": 1, "status": "checked with relevant evidence", "detail": "Preview read", "checked_urls": [page["url"]], "observed_at": READ},
                    {"source": "Punters", "status": "access unavailable", "detail": "robots.txt disallows automated access", "checked_urls": ["https://www.punters.com.au/robots.txt"], "observed_at": READ}]
        notes = [{"race_no": 1, "text": "Soft-track conditions attached to one tip; recheck going on race morning.", "basis": ["p1"], "observed_at": READ}]
        return {"pack": "research-pack-v1", "meeting_id": MID, "researcher": "test researcher", "pages": [page], "claims": claims, "coverage": coverage, "notes": notes}

    def write(self, pack, name="pack.json"):
        path = self.root / name
        path.write_text(json.dumps(pack), encoding="utf-8")
        return path


class PackTests(PackBase):
    def test_import_is_verified_classified_and_idempotent(self):
        path = self.write(self.pack())
        result = import_pack(path, self.store, self.notes, CONFIG, self.cache)
        self.assertEqual(result, {"evidence": 3, "coverage": 2, "notes": 1, "labels": 0, "verified": 3})
        again = import_pack(path, self.store, self.notes, CONFIG, self.cache)
        self.assertEqual(again["evidence"], 3)
        evidence = [d for d in self.store.all(MID) if d["kind"] == "evidence"]
        self.assertEqual(len(evidence), 3)
        self.assertTrue(all(d["payload"]["reviewed"] for d in evidence))
        self.assertEqual({d["payload"]["author"] for d in evidence}, {"Chris Waller", "A Writer"})
        labels = [n for n in self.notes.all(MID) if n["kind"] == "classification"]
        self.assertEqual(len(labels), 3)
        self.assertEqual({n["evidence_id"] for n in labels}, {d["id"] for d in evidence})

    def test_invalid_claims_block_the_whole_pack(self):
        def case(edit, reason):
            p = self.pack(); edit(p); return p, reason
        cases = [case(lambda p: p["claims"][0].update(runners=["Warwoven"]), "Unknown runner 'Warwoven'"),
                 case(lambda p: p["claims"][0].update(excerpt="an invented quotation"), "not found verbatim"),
                 case(lambda p: p["claims"][1].update(runners=["St Gotthard"]), "wrong-horse"),
                 case(lambda p: p["claims"][0].update(excerpt=" ".join(["word"] * 21)), "limited to 20 words"),
                 case(lambda p: p["claims"][0].update(type="inference"), "inference belongs in notes"),
                 case(lambda p: p["pages"][0].update(url="https://www.punters.com.au/news/x", source="Punters"), "not approved for automated fetching"),
                 case(lambda p: p["pages"][0].update(source="Punters"), "does not carry material from Punters"),
                 case(lambda p: p["pages"][0].update(published_at="2026-09-23T02:00:00+00:00"), "Publication cannot be after observation"),
                 case(lambda p: p["claims"][1].update(tip="banker"), "known selection label"),
                 case(lambda p: p["notes"][0].update(basis=[]), "must cite the pages"),
                 case(lambda p: p["notes"][0].update(observed_at="2026-09-23T00:30:00+00:00"), "observed after the note was written"),
                 case(lambda p: p["notes"][0].update(basis=["e" * 64]), "neither a pack page nor a stored snapshot"),
                 case(lambda p: p["claims"].append(dict(p["claims"][0], runners=["St Gotthard", "ST GOTTHARD"])), "same runner twice")]
        for i, (pack, reason) in enumerate(cases):
            with self.subTest(reason=reason), self.assertRaisesRegex(Invalid, reason):
                import_pack(self.write(pack, f"bad{i}.json"), self.store, self.notes, CONFIG, self.cache)
        self.assertFalse([d for d in self.store.all(MID) if d["kind"] in {"evidence", "coverage"}])

    def test_missing_cached_text_and_post_start_observation(self):
        p = self.pack(); p["pages"][0]["text_sha256"] = "0" * 64
        with self.assertRaisesRegex(Invalid, "missing from the local cache"):
            build(p, self.store, CONFIG, self.cache)
        p = self.pack()
        p["notes"] = []  # a note written before its basis was observed is refused first, by a separate guard
        p["pages"][0]["observed_at"] = "2026-09-26T02:30:00+00:00"  # 12:30 AEST, after the 12:00 start
        with self.assertRaisesRegex(Invalid, "cannot be in the future"):
            import_pack(self.write(p), self.store, self.notes, CONFIG, self.cache)
        later = lambda: "2026-09-26T03:00:00+00:00"  # a clock after the race, so only the start gate can refuse it
        with mock.patch("punting.core.now", later), mock.patch("punting.research.evidence.now", later):
            with self.assertRaisesRegex(Invalid, "after the race start"):
                import_pack(self.write(p), self.store, self.notes, CONFIG, self.cache)
        self.assertFalse([d for d in self.store.all(MID) if d["kind"] == "evidence"])

    def test_manual_import_is_marked_unverified(self):
        p = self.pack()
        p["pages"][0].update(route="manual", text_sha256=None, url="https://wolfden.bet/tips/golden-rose", source="Wolfden", publisher="Wolfden")
        p["claims"] = [dict(p["claims"][1], excerpt="")]
        p["coverage"], p["notes"] = [], []
        import_pack(self.write(p), self.store, self.notes, CONFIG, self.cache)
        [e] = [d for d in self.store.all(MID) if d["kind"] == "evidence"]
        self.assertFalse(e["payload"]["reviewed"])
        _, _, text = render(self.store, self.notes, CONFIG, MID, "2030-01-01T00:00:00+00:00")
        self.assertIn("UNVERIFIED manual import", text)

    def test_syndicated_copy_counts_once(self):
        p = self.pack()
        copy_page = dict(p["pages"][0], id="p2", url="https://www.justracing.com.au/copy", source="Just Racing", publisher="Just Racing",
                         original_url=p["pages"][0]["url"], original_publisher="Racing.com")
        p["pages"].append(copy_page)
        p["claims"].append(dict(p["claims"][1], page="p2", claim_id="value-call"))
        p["claims"][1]["claim_id"] = "value-call"
        import_pack(self.write(p), self.store, self.notes, CONFIG, self.cache)
        _, evidence, text = render(self.store, self.notes, CONFIG, MID, "2030-01-01T00:00:00+00:00")
        self.assertEqual(sum("value" == e["label"].get("tip") for e in evidence), 1)
        self.assertIn("| R1 | 3 | CAMPIONE D’ITALIA | 1 | 0 |", text)

    def test_digest_groups_escapes_and_respects_recording_cutoff(self):
        p = self.pack()
        p["claims"].append({"page": "p1", "race_no": 1, "runners": ["St Gotthard"], "type": "opinion", "stance": "negative", "topic": "distance",
                            "summary": "<script>alert(1)</script> doubts 1400m", "excerpt": "ready for the step up to 1400 metres", "conditions": []})
        import_pack(self.write(p), self.store, self.notes, CONFIG, self.cache)
        _, _, text = render(self.store, self.notes, CONFIG, MID, "2030-01-01T00:00:00+00:00")
        self.assertIn("Sources disagree: ST GOTTHARD (1 for, 1 against)", text)
        self.assertIn("| Punters | access unavailable |", text)
        self.assertIn("| Wolfden | not checked | No check recorded; access route: manual |", text)
        self.assertIn("track stays soft", text)
        html = page(text + "\n[x](javascript:alert(1))\n", "t")
        self.assertNotIn("<script>", html); self.assertNotIn('href="javascript:', html)
        _, early, _ = render(self.store, self.notes, CONFIG, MID, READ)  # evidence observed by READ; labels recorded later
        self.assertTrue(early)
        self.assertEqual({e["label"]["stance"] for e in early}, {"unclassified"})


class BrowserAndLabelTests(PackBase):
    RECEIPT_SHA = "a" * 64

    def browser_pack(self, found=True, near=True):
        p = self.pack()
        excerpt = p["claims"][1]["excerpt"]
        p["pages"][0].update(route="browser", url="https://www.justhorseracing.com.au/tips/rosehill/1", source="Just Horse Racing",
                             publisher="Just Horse Racing", text_sha256=self.RECEIPT_SHA,
                             browser_receipt={"url": "https://www.justhorseracing.com.au/tips/rosehill/1/", "checked_at": "2026-09-23T01:02:00.000Z",
                                              "text_sha256": self.RECEIPT_SHA, "words": 900, "names_in_page": {},
                                              "excerpts": {excerpt: {"found": found, "near": {"Campione D'Italia": near}}}})
        p["claims"], p["coverage"], p["notes"] = [p["claims"][1]], [], []
        return p

    def test_browser_receipt_verifies_without_retaining_text(self):
        import_pack(self.write(self.browser_pack()), self.store, self.notes, CONFIG, self.cache)
        [e] = [d for d in self.store.all(MID) if d["kind"] == "evidence"]
        self.assertTrue(e["payload"]["reviewed"])
        [label] = [n for n in self.notes.all(MID) if n["kind"] == "classification"]
        self.assertEqual(label["verification"]["method"], "browser receipt")
        _, _, text = render(self.store, self.notes, CONFIG, MID, "2030-01-01T00:00:00+00:00")
        self.assertIn("excerpt verified in browser", text)

    def test_browser_receipt_failures(self):
        for pack, reason in [(self.browser_pack(found=False), "not found verbatim in the browser check"),
                             (self.browser_pack(near=False), "wrong-horse"),
                             (dict(self.browser_pack(), claims=[dict(self.browser_pack()["claims"][0], excerpt="value play")]), "No browser check recorded")]:
            with self.subTest(reason=reason), self.assertRaisesRegex(Invalid, reason):
                import_pack(self.write(pack), self.store, self.notes, CONFIG, self.cache)
        p = self.browser_pack(); p["pages"][0]["browser_receipt"]["text_sha256"] = "b" * 64
        with self.assertRaisesRegex(Invalid, "hash does not match"):
            check_pack(p, CONFIG)
        p = self.browser_pack(); p["pages"][0]["browser_receipt"]["url"] = "https://www.justhorseracing.com.au/tips/other"
        with self.assertRaisesRegex(Invalid, "Browser receipt is for"):
            check_pack(p, CONFIG)

    def legacy(self, runner="ra:3"):
        """An existing store record without an excerpt, like the first-session imports."""
        d = {"kind": "evidence", "meeting_id": MID, "race_no": 1, "source_url": "https://www.racing.com/news/golden-rose-preview", "publisher": "Racing.com",
             "observed_at": "2026-09-23T00:30:00+00:00", "published_at": None,
             "payload": {"runner_ids": [runner], "author": None, "original_url": "https://www.racing.com/news/golden-rose-preview", "claim_id": "legacy",
                         "excerpt": "", "summary": "Named as a value play.", "type": "opinion", "conditions": [], "reviewed": True}}
        return self.store.add(d, CONFIG)

    def test_same_speaker_is_one_voice_across_outlets(self):
        from punting.research.digest import tally
        e = lambda author, pub: {"publisher": pub, "label": {"stance": "positive"}, "payload": {"type": "attributed statement", "author": author, "runner_ids": ["ra:1"], "conditions": []}}
        t = tally([e("Michael Kent Jnr, reported by Trent Masenhelder", "Racing.com"), e("Michael Kent Jnr", "Just Racing")], "ra:1")
        self.assertEqual(len(t["for"]), 1)

    def test_labels_classify_existing_evidence_and_confirm_the_horse(self):
        sid = self.legacy()
        p = self.pack(); p["claims"], p["coverage"], p["notes"] = [], [], []
        _, _, before = render(self.store, self.notes, CONFIG, MID, "2030-01-01T00:00:00+00:00")
        self.assertIn("**Unclassified** — Named as a value play.", before)
        p["labels"] = [{"evidence_id": sid, "stance": "positive", "topic": "selection", "tip": "value", "page": "p1"}]
        self.assertEqual(import_pack(self.write(p), self.store, self.notes, CONFIG, self.cache)["labels"], 1)
        _, _, after = render(self.store, self.notes, CONFIG, MID, "2030-01-01T00:00:00+00:00")
        self.assertIn("**For (value)** — Named as a value play.", after)
        self.assertIn("marked reviewed but no excerpt to verify; horse confirmed on source page", after)
        absent = self.legacy("ra:4")  # Mr Brightside is not in the article
        p["labels"] = [{"evidence_id": absent, "stance": "positive", "topic": "selection", "page": "p1"}]
        with self.assertRaisesRegex(Invalid, "absent from its source page"):
            import_pack(self.write(p), self.store, self.notes, CONFIG, self.cache)
        p["labels"] = [{"evidence_id": "f" * 64, "stance": "positive", "topic": "selection"}]
        with self.assertRaisesRegex(Invalid, "not in this meeting's store"):
            import_pack(self.write(p), self.store, self.notes, CONFIG, self.cache)


class WeatherTests(unittest.TestCase):
    def test_forecast_uses_issue_time_and_flags_missing_window(self):
        parsed = parse(BOM)
        self.assertEqual(parsed["issued_at"], "2026-09-23T06:00:00+00:00")
        docs, coverage = forecast_docs(MEETING, parsed, "2026-09-23T08:00:00+00:00")
        self.assertEqual(len(docs), 1)
        d = docs[0]
        self.assertEqual(d["published_at"], parsed["issued_at"]); self.assertEqual(d["payload"]["type"], "forecast")
        self.assertIn("max 34°C", d["payload"]["summary"]); self.assertIn("Thu 24 Sep", d["payload"]["summary"])
        self.assertIn("Sydney Olympic Park", coverage["payload"]["detail"])
        self.assertEqual(coverage["payload"]["status"], "checked with relevant evidence")
        early = copy.deepcopy(parsed)
        early["areas"]["Parramatta"] = early["areas"]["Parramatta"][:2]
        docs, coverage = forecast_docs(MEETING, early, "2026-09-23T08:00:00+00:00")
        self.assertEqual((docs, coverage["payload"]["status"]), ([], "not yet published"))

    def test_rejects_entities_and_non_forecasts(self):
        with self.assertRaises(Invalid):
            parse(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><product/>')
        with self.assertRaises(Invalid):
            parse(BOM.replace(b"<product-type>F</product-type>", b"<product-type>O</product-type>"))


if __name__ == "__main__":
    unittest.main()
