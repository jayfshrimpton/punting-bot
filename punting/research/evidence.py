"""Evidence packs: researcher-authored claims, verified against captured source text, imported through Store.add.

A pack lists the pages read (capture route, observation time, text hash) and the claims taken from them.
Import refuses a claim unless its excerpt appears verbatim in the captured text and every named horse is
mentioned near that excerpt. Names resolve to official runner IDs by exact normalised name, never fuzzily.
Stance/topic labels are classifications with their own provenance, kept outside the evidence snapshot.
"""
import json
import re
import sqlite3
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit
from ..core import STATUSES, Invalid, canonical, digest, keys, now, stamp, text, url
from .access import POLICY, SUPPLEMENTARY, attributable, cached, normal

PACK = "research-pack-v1"
TYPES = {"official observation", "forecast", "opinion", "attributed statement"}
STANCES = {"positive", "negative", "neutral", "mixed"}
TOPICS = {"selection", "form", "fitness", "track", "distance", "barrier", "pace", "gear", "jockey", "stable", "market", "weather", "class", "other"}
TIPS = {"top selection", "second selection", "third selection", "fourth selection", "best bet", "next best", "value", "roughie", "each-way", "lay"}
ROUTES = {"http", "browser", "manual", "ftp"}
MAX_EXCERPT_WORDS = 20
MAX_SUMMARY_WORDS = 70
NEAR = 600  # characters either side of an excerpt within which a claimed horse must be named
SUFFIX = re.compile(r"\s*\(([A-Z]{2,4})\)\s*$")


def horse_key(name):
    """Matching form of a horse name: apostrophes dropped, punctuation spaced, country suffix removed."""
    s = re.sub(r"[‘’‛'`]", "", unicodedata.normalize("NFKC", name).upper())
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", SUFFIX.sub("", s)).split())


def suffix(name):
    m = SUFFIX.search(unicodedata.normalize("NFKC", name).upper())
    return m[1] if m else None


def resolve(ref, runners):
    """Exactly one official runner for 'St Gotthard', 'Mr Brightside (NZ)' or {'name':..., 'number':...}."""
    name, number = (ref, None) if isinstance(ref, str) else (ref.get("name"), ref.get("number")) if isinstance(ref, dict) else (None, None)
    text(name, "runner name")
    key, sfx = horse_key(name), suffix(name)
    found = [r for r in runners if horse_key(r["name"]) == key and (sfx is None or suffix(r["name"]) == sfx)]
    if number is not None:
        found = [r for r in found if r["number"] == str(number)]
    if len(found) != 1:
        raise Invalid(f"{'Ambiguous' if found else 'Unknown'} runner {name!r} for this race; use the official name (and number)")
    return found[0]


def windows(page, excerpt):
    """Every location of the excerpt in the page, as comparison-normalised text windows."""
    hay, needle = normal(page), normal(excerpt)
    out, start = [], hay.find(needle)
    while start >= 0 and needle:
        out.append(hay[max(0, start - NEAR):start + len(needle) + NEAR])
        start = hay.find(needle, start + 1)
    return out


def named_in(window, runner_name):
    """Whole-name match. Tries the text as written (RUBI'S CHOICE) and with possessives removed (St Gotthard's)."""
    key = f" {horse_key(runner_name)} "
    possessive = re.sub(r"'s\b", "", window, flags=re.I)
    return any(key in f" {horse_key(v)} " for v in (window, possessive))


def verify(page_text, excerpt, runner_names):
    """Raise unless the excerpt is verbatim in the page and each horse is named near it."""
    if not excerpt.strip():
        raise Invalid("A verified claim needs a short verbatim excerpt")
    found = windows(page_text, excerpt)
    if not found:
        raise Invalid(f"Excerpt not found verbatim in captured page text: {excerpt!r}")
    for name in runner_names:
        if not any(named_in(w, name) for w in found):
            raise Invalid(f"{name} is not named within {NEAR} characters of excerpt {excerpt!r}; possible wrong-horse attribution")


def words(value):
    return len(value.split())


def ref_name(ref):
    return ref if isinstance(ref, str) else ref.get("name", "")


def check_receipt(page):
    """A browser receipt must describe this page, match its text hash and be close to its observation time."""
    r = page["browser_receipt"]
    keys(r, ("url", "checked_at", "text_sha256", "words", "excerpts", "names_in_page"))
    a, b = urlsplit(r["url"]), urlsplit(page["url"])
    if (a.hostname, a.path.rstrip("/")) != (b.hostname, b.path.rstrip("/")):
        raise Invalid(f"Browser receipt is for {r['url']}, not {page['url']}")
    if r["text_sha256"] != page["text_sha256"]:
        raise Invalid("Browser receipt text hash does not match the page record")
    if abs((stamp(r["checked_at"]) - stamp(page["observed_at"])).total_seconds()) > 1800:
        raise Invalid("Browser receipt must be taken within 30 minutes of the recorded observation")
    if stamp(r["checked_at"]) > stamp(now()):
        raise Invalid("Browser receipt cannot be in the future")


def confirm(page, excerpt, refs, runners, cache):
    """How the excerpt was verified: 'captured text', 'browser receipt', or None for an unverifiable manual import.
    Raises when a check was possible and failed."""
    content = cached(page["text_sha256"], cache) if page["text_sha256"] else None
    if content is not None:
        verify(content, excerpt, [r["name"] for r in runners])
        return "captured text"
    receipt = page.get("browser_receipt")
    if receipt:
        result = receipt["excerpts"].get(excerpt)
        if result is None:
            raise Invalid(f"No browser check recorded for excerpt {excerpt!r}; rerun the checker for page {page['id']}")
        if not result["found"]:
            raise Invalid(f"Excerpt not found verbatim in the browser check: {excerpt!r}")
        missing = [ref_name(ref) for ref in refs if not result["near"].get(ref_name(ref))]
        if missing:
            raise Invalid(f"{', '.join(missing)} not named within {NEAR} characters of excerpt {excerpt!r}; possible wrong-horse attribution")
        return "browser receipt"
    if page["route"] in {"http", "browser"}:
        raise Invalid(f"Captured text for page {page['id']} is missing from the local cache; recapture it or attach a browser receipt")
    return None


def check_pack(pack, config):
    """Structural validation. Store-dependent checks happen in build()."""
    keys(pack, ("pack", "meeting_id", "researcher", "pages", "claims", "coverage"), ("notes", "labels"))
    if pack["pack"] != PACK:
        raise Invalid(f"Unsupported pack format {pack['pack']!r}")
    if pack["meeting_id"] not in {m["id"] for m in config["meetings"]}:
        raise Invalid("Unknown meeting_id")
    text(pack["researcher"], "researcher")
    pages = {}
    for p in pack["pages"]:
        keys(p, ("id", "source", "url", "publisher", "author", "title", "published_at", "observed_at", "route", "text_sha256"),
             ("original_url", "original_publisher", "published_note", "http_status", "raw_sha256", "notes", "browser_receipt"))
        text(p["id"], "page id")
        if p["id"] in pages:
            raise Invalid("Duplicate page id " + p["id"])
        url(p["url"])
        host = urlsplit(p["url"]).hostname
        if p["source"] not in POLICY and p["source"] not in SUPPLEMENTARY.values():
            raise Invalid(f"Unknown source {p['source']!r}; add it to the access policy first")
        if not attributable(p["source"], host):
            raise Invalid(f"{host} does not carry material from {p['source']}")
        if p["route"] not in ROUTES:
            raise Invalid("Unknown capture route")
        if p["route"] == "http" and p["source"] in POLICY and POLICY[p["source"]]["route"] != "http" and host in POLICY[p["source"]]["hosts"]:
            raise Invalid(f"{p['source']} is not approved for automated fetching")
        text(p["publisher"], "publisher")
        for k in ("author", "title", "original_publisher", "published_note", "notes"):
            if p.get(k) is not None:
                text(p[k], k)
        observed = stamp(p["observed_at"])
        if observed > stamp(now()):
            raise Invalid("Page observation cannot be in the future")
        if p["published_at"] is not None and stamp(p["published_at"]) > observed:
            raise Invalid("Publication cannot be after observation")
        if p.get("original_url") is not None:
            url(p["original_url"])
        if p["text_sha256"] is not None and not re.fullmatch(r"[0-9a-f]{64}", p["text_sha256"]):
            raise Invalid("text_sha256 must be a SHA-256 hex digest")
        if p["route"] in {"http", "browser"} and p["text_sha256"] is None:
            raise Invalid("Fetched or browser-read pages need their captured text hash")
        if p.get("browser_receipt") is not None:
            if p["route"] != "browser":
                raise Invalid("Browser receipts belong to browser-route pages")
            check_receipt(p)
        pages[p["id"]] = p
    for c in pack["claims"]:
        keys(c, ("page", "race_no", "runners", "type", "stance", "topic", "summary", "excerpt", "conditions"), ("claim_id", "author", "tip"))
        if c["page"] not in pages:
            raise Invalid("Claim refers to unknown page " + str(c["page"]))
        if c["race_no"] is not None and (type(c["race_no"]) is not int or c["race_no"] < 1):
            raise Invalid("race_no must be a positive integer or null")
        if not isinstance(c["runners"], list) or (c["runners"] and c["race_no"] is None):
            raise Invalid("runners must be a list, and runner claims need a race number")
        if c["type"] not in TYPES:
            raise Invalid(f"Claim type must be one of {sorted(TYPES)}; researcher inference belongs in notes")
        if c["stance"] not in STANCES or c["topic"] not in TOPICS:
            raise Invalid("Unknown stance/topic")
        if c.get("tip") is not None and (c["tip"] not in TIPS or c["topic"] != "selection"):
            raise Invalid("tip must be a known selection label on a selection claim")
        text(c["summary"], "summary")
        if words(c["summary"]) > MAX_SUMMARY_WORDS:
            raise Invalid("Summaries must be short, in your own words")
        if not isinstance(c["excerpt"], str) or words(c["excerpt"]) > MAX_EXCERPT_WORDS:
            raise Invalid(f"Excerpts are limited to {MAX_EXCERPT_WORDS} words")
        if not isinstance(c["conditions"], list) or not all(isinstance(x, str) and x.strip() for x in c["conditions"]):
            raise Invalid("conditions must be a list of nonempty strings")
        for k in ("claim_id", "author"):
            if c.get(k) is not None:
                text(c[k], k)
    for v in pack["coverage"]:
        keys(v, ("source", "status", "detail", "checked_urls", "observed_at"), ("race_no",))
        if v["source"] not in config["required_sources"] or v["status"] not in STATUSES:
            raise Invalid(f"Unknown coverage source/status: {v['source']!r}/{v['status']!r}")
        stamp(v["observed_at"])
    for n in pack.get("notes", []):
        keys(n, ("race_no", "text", "basis", "observed_at"))
        text(n["text"], "note")
        stamp(n["observed_at"])
        if not isinstance(n["basis"], list) or not n["basis"] or any(b not in pages and not re.fullmatch(r"[0-9a-f]{64}", str(b)) for b in n["basis"]):
            raise Invalid("A researcher note must cite the pages or stored snapshot IDs it is based on")
    for label in pack.get("labels", []):
        keys(label, ("evidence_id", "stance", "topic"), ("tip", "page"))
        if label["stance"] not in STANCES or label["topic"] not in TOPICS:
            raise Invalid("Unknown stance/topic in label")
        if label.get("tip") is not None and (label["tip"] not in TIPS or label["topic"] != "selection"):
            raise Invalid("tip must be a known selection label on a selection claim")
        if label.get("page") is not None and label["page"] not in pages:
            raise Invalid("Label refers to unknown page")
    return pages


def latest_field(store, meeting_id, race_no, observed_at):
    fields = [d for d in store.all(meeting_id, observed_at) if d["kind"] == "field" and d.get("race_no") == race_no]
    if not fields:
        raise Invalid(f"No official field for race {race_no} observed by {observed_at}")
    return fields[-1]


def build(pack, store, config, cache="data/private/pages"):
    """Evidence, coverage and classification documents for a pack. Nothing is written."""
    pages = check_pack(pack, config)
    meeting = pack["meeting_id"]
    evidence, labels, coverage, notes = [], [], [], []
    for c in pack["claims"]:
        page = pages[c["page"]]
        runners, field = [], None
        if c["race_no"] is not None:
            field = latest_field(store, meeting, c["race_no"], page["observed_at"])
            runners = [resolve(ref, field["payload"]["runners"]) for ref in c["runners"]]
            if len({r["id"] for r in runners}) != len(runners):
                raise Invalid("A claim names the same runner twice")
        method = confirm(page, c["excerpt"], c["runners"], runners, cache)
        verified = method is not None
        original = page.get("original_url") or page["url"]
        payload = {"runner_ids": [r["id"] for r in runners], "author": c.get("author") or page["author"], "original_url": original,
                   "claim_id": c.get("claim_id") or "claim:" + digest([original, c["race_no"], sorted(r["id"] for r in runners), c["summary"]])[:20],
                   "excerpt": c["excerpt"], "summary": c["summary"], "type": c["type"], "conditions": c["conditions"], "reviewed": verified}
        d = {"kind": "evidence", "meeting_id": meeting, "source_url": page["url"], "publisher": page["publisher"],
             "observed_at": page["observed_at"], "published_at": page["published_at"], "payload": payload}
        if c["race_no"] is not None:
            d["race_no"] = c["race_no"]
        evidence.append(d)
        labels.append({"kind": "classification", "meeting_id": meeting, "race_no": c["race_no"], "evidence_id": digest(d),
                       "classifier": pack["researcher"], "method": PACK + " manual reading", "stance": c["stance"], "topic": c["topic"],
                       "tip": c.get("tip"), "source": page["source"], "original_publisher": page.get("original_publisher") or page["publisher"],
                       "verification": {"route": page["route"], "text_sha256": page["text_sha256"], "excerpt_verbatim": verified,
                                        "runners_named_near_excerpt": verified and bool(runners), "method": method or "none"},
                       "published_note": page.get("published_note"), "observed_at": page["observed_at"]})
    existing = {d["id"]: d for d in store.all(meeting) if d["kind"] == "evidence"} if pack.get("labels") else {}
    for label in pack.get("labels", []):
        d = existing.get(label["evidence_id"])
        if d is None:
            raise Invalid(f"Label refers to evidence {label['evidence_id'][:12]} not in this meeting's store")
        check = {"route": None, "text_sha256": None, "excerpt_verbatim": False, "runners_named_in_page": None, "method": "label only"}
        if label.get("page") is not None:
            page = pages[label["page"]]
            if page["url"] not in {d["source_url"], d["payload"]["original_url"]}:
                raise Invalid("A label's confirming page must be the evidence's own source")
            names = []
            if d["payload"]["runner_ids"]:
                field = latest_field(store, meeting, d["race_no"], d["observed_at"])
                names = [r["name"] for r in field["payload"]["runners"] if r["id"] in d["payload"]["runner_ids"]]
            content = cached(page["text_sha256"], cache) if page["text_sha256"] else None
            if content is not None:
                present = {n: named_in(normal(content), n) for n in names}
            elif page.get("browser_receipt"):
                present = {n: page["browser_receipt"]["names_in_page"].get(n) for n in names}
                if any(v is None for v in present.values()):
                    raise Invalid("Browser receipt lacks a names_in_page check for a labelled runner; pass official names to the checker")
            else:
                raise Invalid("A confirming page needs captured text or a browser receipt")
            if not all(present.values()):
                raise Invalid(f"Labelled evidence names a horse absent from its source page: {[n for n, ok in present.items() if not ok]}")
            check.update(route=page["route"], text_sha256=page["text_sha256"], runners_named_in_page=True, method="source page re-read")
        labels.append({"kind": "classification", "meeting_id": meeting, "race_no": d.get("race_no"), "evidence_id": d["id"],
                       "classifier": pack["researcher"], "method": PACK + " label of existing evidence", "stance": label["stance"], "topic": label["topic"],
                       "tip": label.get("tip"), "source": d["publisher"], "original_publisher": d["publisher"], "verification": check,
                       "published_note": None, "observed_at": d["observed_at"]})
    for v in pack["coverage"]:
        d = {"kind": "coverage", "meeting_id": meeting, "source_url": v["checked_urls"][0] if v["checked_urls"] else "", "publisher": v["source"],
             "observed_at": v["observed_at"], "published_at": None,
             "payload": {"source": v["source"], "status": v["status"], "detail": v["detail"], "checked_urls": v["checked_urls"]}}
        if v.get("race_no") is not None:
            d["race_no"] = v["race_no"]
        coverage.append(d)
    stored = {d["id"]: d for d in store.all(meeting)} if any(b not in pages for n in pack.get("notes", []) for b in n["basis"]) else {}
    for n in pack.get("notes", []):
        basis = []
        for b in n["basis"]:
            source = pages.get(b) or stored.get(b)
            if source is None:
                raise Invalid(f"Note basis {b[:12]} is neither a pack page nor a stored snapshot for this meeting")
            if stamp(source["observed_at"]) > stamp(n["observed_at"]):
                raise Invalid("A note cannot rest on something observed after the note was written")
            basis.append({"url": source.get("url") or source["source_url"], "publisher": source["publisher"], "observed_at": source["observed_at"]})
        notes.append({"kind": "note", "meeting_id": meeting, "race_no": n["race_no"], "classifier": pack["researcher"], "text": n["text"],
                      "basis": basis, "observed_at": n["observed_at"]})
    from ..core import validate
    for d in evidence + coverage:
        validate(d, config)
    for d in evidence:
        if d.get("race_no") is not None:
            field = latest_field(store, d["meeting_id"], d["race_no"], d["observed_at"])
            if stamp(d["observed_at"]) >= stamp(field["payload"]["start_at"]):
                raise Invalid("Evidence observed after the race start cannot be imported")
    for d in labels + notes:
        validate_note(d)
    return evidence, labels, coverage, notes


def validate_note(d):
    """Shared preflight for generated notes and the append-only notes boundary."""
    if d["kind"] not in {"classification", "note"}:
        raise Invalid("Unknown research note kind")
    text(d["meeting_id"], "meeting_id")
    text(d["classifier"], "classifier")
    race = d.get("race_no")
    if race is not None and (type(race) is not int or race < 1):
        raise Invalid("Note race_no must be a positive integer or null")
    if stamp(d["observed_at"]) > stamp(now()):
        raise Invalid("Note observation cannot be in the future")
    canonical(d)


class Notes:
    """Append-only classifications and researcher notes, separate from source snapshots."""
    def __init__(self, root="data"):
        Path(root).mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(Path(root) / "research_notes.sqlite")
        self.db.execute("CREATE TABLE IF NOT EXISTS notes(id TEXT PRIMARY KEY, kind TEXT NOT NULL, meeting TEXT NOT NULL, race INTEGER, target TEXT, observed TEXT NOT NULL, recorded TEXT NOT NULL, document TEXT NOT NULL)")
        for action in ("UPDATE", "DELETE"):
            self.db.execute(f"CREATE TRIGGER IF NOT EXISTS forbid_{action} BEFORE {action} ON notes BEGIN SELECT RAISE(ABORT, 'Research notes are immutable'); END")
        self.db.commit()

    def close(self):
        self.db.close()

    def add(self, d):
        validate_note(d)
        observed = stamp(d["observed_at"])
        sid = digest(d)
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO notes VALUES(?,?,?,?,?,?,?,?)",
                            (sid, d["kind"], d["meeting_id"], d.get("race_no"), d.get("evidence_id"), observed.isoformat(), now(), canonical(d)))
        return sid

    def all(self, meeting, cutoff=None):
        """Notes recorded (not merely observed) by the cutoff, so a later classification cannot leak into an earlier report."""
        out = []
        for sid, recorded, raw in self.db.execute("SELECT id, recorded, document FROM notes WHERE meeting=?", (meeting,)):
            d = json.loads(raw)
            if digest(d) != sid:
                raise Invalid("Stored research note hash mismatch")
            if cutoff is None or stamp(recorded) <= stamp(cutoff):
                out.append(dict(d, id=sid, recorded_at=recorded))
        return sorted(out, key=lambda d: (stamp(d["observed_at"]), d["id"]))


def import_pack(path, store, notes, config, cache="data/private/pages"):
    """Validate the whole pack against the store first, then write. Re-importing is idempotent."""
    pack = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    evidence, labels, coverage, extra = build(pack, store, config, cache)
    ids = [store.add(d, config) for d in evidence]
    for sid, label in zip(ids, labels):
        if label["evidence_id"] != sid:
            raise Invalid("Evidence identity changed during import")
    for label in labels:
        notes.add(label)
    for d in coverage:
        store.add(d, config)
    for n in extra:
        notes.add(n)
    return {"evidence": len(evidence), "coverage": len(coverage), "notes": len(extra), "labels": len(labels) - len(evidence),
            "verified": sum(d["payload"]["reviewed"] for d in evidence)}
