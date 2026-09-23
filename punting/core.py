"""Strict import boundary; timestamps are observations, never guessed publication times."""
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo


class Invalid(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def stamp(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.utcoffset() is None:
            raise ValueError()
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError):
        raise Invalid(f"Expected timezone-aware ISO timestamp: {value!r}") from None


def local(value):
    return stamp(value).astimezone(ZoneInfo("Australia/Sydney")).strftime("%d %b %Y %H:%M:%S %Z")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def namekey(value):
    # Preserve country suffixes and punctuation: no speculative fuzzy joins.
    return " ".join(value.upper().split())


def text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise Invalid(f"{label} must be nonempty text")


def url(value):
    text(value, "source_url")
    p = urlsplit(value)
    if p.scheme not in {"https", "http"} or not p.hostname or p.username or p.password:
        raise Invalid("Source URL must be an ordinary HTTP(S) URL without credentials")


def number(value, low, high, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise Invalid(f"Invalid {label}: {value!r}")


def keys(obj, required, optional=()):
    if not isinstance(obj, dict):
        raise Invalid("Expected an object")
    missing = set(required) - obj.keys()
    extra = obj.keys() - set(required) - set(optional)
    if missing or extra:
        raise Invalid(f"Schema mismatch; missing={sorted(missing)}, unexpected={sorted(extra)}")


STATUSES = {"checked with relevant evidence", "checked with nothing relevant", "not yet published", "access unavailable", "manual import needed", "failed", "stale"}


def validate(d, config):
    keys(d, ("kind", "meeting_id", "source_url", "publisher", "observed_at", "published_at", "payload"), ("race_no",))
    meetings = {m["id"]: m for m in config["meetings"]}
    if d["meeting_id"] not in meetings:
        raise Invalid("Unknown meeting/date; use a configured meeting ID")
    url(d["source_url"])
    text(d["publisher"], "publisher")
    observed = stamp(d["observed_at"])
    if observed > stamp(now()):
        raise Invalid("Observation time cannot be in the future")
    if d["published_at"] is not None and stamp(d["published_at"]) > observed:
        raise Invalid("Publication cannot be after observation")
    if "race_no" in d and (type(d["race_no"]) is not int or d["race_no"] < 1):
        raise Invalid("race_no must be a positive integer")
    p, kind = d["payload"], d["kind"]
    if kind in {"field", "model", "quotes", "decision"} and "race_no" not in d:
        raise Invalid("A race number is required")
    if kind == "field":
        keys(p, ("race_name", "start_at", "runners", "going", "rail", "official", "card_races"))
        text(p["race_name"], "race_name")
        start = stamp(p["start_at"])
        if start.astimezone(ZoneInfo(meetings[d["meeting_id"]]["timezone"])).date().isoformat() != meetings[d["meeting_id"]]["date"]:
            raise Invalid("Race start does not match meeting date")
        if observed >= start:
            raise Invalid("Field snapshot must be observed before race start")
        if type(p["official"]) is not bool or type(p["card_races"]) is not int or p["card_races"] < d["race_no"]:
            raise Invalid("Invalid official/card_races metadata")
        if not isinstance(p["runners"], list) or len(p["runners"]) < 2:
            raise Invalid("Field needs at least two runner records")
        ids, names, nos = set(), set(), set()
        for r in p["runners"]:
            keys(r, ("id", "name", "number", "status"), ("barrier", "jockey", "trainer", "weight", "form", "official_url"))
            for k in ("id", "name", "number"):
                text(r[k], k)
            if r["id"] in ids or namekey(r["name"]) in names or r["number"] in nos:
                raise Invalid("Duplicate/ambiguous runner identity")
            ids.add(r["id"]); names.add(namekey(r["name"])); nos.add(r["number"])
            if r["status"] not in {"active", "scratched", "emergency"}:
                raise Invalid("Unknown runner status")
            if r.get("official_url"):
                url(r["official_url"])
    elif kind in {"model", "quotes"}:
        required = ("field_id", "rows", "model", "version") if kind == "model" else ("field_id", "rows", "provider", "market", "commission", "terms")
        keys(p, required, ("limitations", "experimental", "includes_emergencies") if kind == "model" else ())
        text(p["field_id"], "field_id")
        if not isinstance(p["rows"], list) or not p["rows"]:
            raise Invalid("Empty numeric snapshot")
        if kind == "model":
            text(p["model"], "model identity")
            if "experimental" in p and type(p["experimental"]) is not bool:
                raise Invalid("experimental must be boolean")
            if "includes_emergencies" in p and type(p["includes_emergencies"]) is not bool:
                raise Invalid("includes_emergencies must be boolean")
            if p.get("includes_emergencies") and not p.get("experimental"):
                raise Invalid("Emergency-inclusive ratings must be experimental")
            if "limitations" in p and (not isinstance(p["limitations"], list) or not all(isinstance(x,str) for x in p["limitations"])):
                raise Invalid("limitations must be a list of strings")
            if p["version"] is not None:
                text(p["version"], "version")
        else:
            text(p["provider"], "provider")
            text(p["terms"], "terms")
            if p["market"] not in {"fixed_win", "exchange_back_win"}:
                raise Invalid("Only fixed WIN and exchange back WIN quotes supported")
            if p["commission"] is not None:
                number(p["commission"], 0, .99, "commission")
            if p["market"] == "fixed_win" and p["commission"] not in {None, 0}:
                raise Invalid("Fixed odds do not use exchange commission")
        ids = set()
        # Exchange quotes may also record the best lay offer, so thin markets can be recognised.
        lay = ("lay_odds", "lay_size") if kind == "quotes" and p["market"] == "exchange_back_win" else ()
        for r in p["rows"]:
            keys(r, ("runner_id", "name", "rated_price") if kind == "model" else ("runner_id", "name", "odds", "size"), lay)
            text(r["runner_id"], "runner_id"); text(r["name"], "name")
            if r["runner_id"] in ids:
                raise Invalid("Duplicate numeric runner")
            ids.add(r["runner_id"])
            number(r["rated_price"] if kind == "model" else r["odds"], 1.00000001, 1e9, "decimal price")
            if kind == "quotes" and r["size"] is not None:
                number(r["size"], 0, 1e12, "size")
            if r.get("lay_odds") is not None:
                number(r["lay_odds"], r["odds"], 1e9, "lay price")
            if r.get("lay_size") is not None:
                number(r["lay_size"], 0, 1e12, "lay size")
    elif kind == "evidence":
        keys(p, ("runner_ids", "author", "original_url", "claim_id", "excerpt", "summary", "type", "conditions", "reviewed"))
        url(p["original_url"])
        for k in ("claim_id", "summary"):
            text(p[k], k)
        if p["author"] is not None:
            text(p["author"], "author")
        if not isinstance(p["excerpt"], str) or len(p["excerpt"].split()) > 25:
            raise Invalid("Keep necessary excerpts to at most 25 words; prefer your own summary")
        if p["type"] not in {"official observation", "forecast", "opinion", "attributed statement", "inference"}:
            raise Invalid("Unknown evidence type")
        if type(p["reviewed"]) is not bool or not isinstance(p["conditions"], list) or not all(isinstance(x, str) for x in p["conditions"]):
            raise Invalid("Invalid review/conditions fields")
        if not isinstance(p["runner_ids"], list) or not all(isinstance(x, str) for x in p["runner_ids"]):
            raise Invalid("runner_ids must be a list of canonical IDs")
        if p["runner_ids"] and "race_no" not in d:
            raise Invalid("Runner evidence requires a race number")
    elif kind == "coverage":
        keys(p, ("source", "status", "detail", "checked_urls"))
        if p["source"] not in config["required_sources"] or p["status"] not in STATUSES:
            raise Invalid("Unknown coverage source/status")
        text(p["detail"], "detail")
        if not isinstance(p["checked_urls"], list) or not p["checked_urls"]:
            raise Invalid("Coverage needs checked pages or search URLs")
        for u in p["checked_urls"]:
            url(u)
    elif kind == "decision":
        keys(p, ("runner_id", "action", "reason", "price"))
        if p["action"] not in {"watch", "select", "pass"}:
            raise Invalid("Invalid human action")
        text(p["reason"], "reason")
        if p["price"] is not None:
            number(p["price"], 1.00000001, 1e9, "decision price")
    else:
        raise Invalid(f"Unsupported snapshot kind: {kind}")
    canonical(d)


def field_signature(field):
    return digest(sorted((r["id"], namekey(r["name"]), r["status"]) for r in field["payload"]["runners"]))


def expected_return(p, odds, commission=0):
    number(p, 0, 1, "probability"); number(odds, 1, 1e9, "odds"); number(commission, 0, .99, "commission")
    return p * (1 + (odds - 1) * (1 - commission)) - 1


def break_even(p, commission=0):
    number(p, 1e-12, 1, "probability"); number(commission, 0, .99, "commission")
    return 1 + (1 / p - 1) / (1 - commission)
