"""Restrained public official-fields adapter. No credentials, paywalls or results."""
import hashlib
import html
import json
import re
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote, urljoin, urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
from .core import Invalid, now


class Text(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def plain(raw):
    p = Text(); p.feed(raw)
    return " ".join(" ".join(p.parts).split())


def official_url(meeting):
    day = datetime.fromisoformat(meeting["date"]).strftime("%Y%b%d")
    key = f"{day},{meeting['state']},{meeting['venue']}"
    return "https://www.racingaustralia.horse/FreeFields/Acceptances.aspx?Key=" + quote(key)


def parse_fields(raw, meeting, observed, source_url):
    page = plain(raw)
    day = datetime.fromisoformat(meeting["date"])
    if meeting["venue"] not in page or day.strftime("%d %B %Y").lstrip("0") not in page:
        raise Invalid("Official page does not identify the requested venue/date")
    races = list(re.finditer(r"Race (\d+)\s*-\s*(\d{1,2}:\d{2}[AP]M)\s+([^<]+)</span>", raw))
    total = re.search(r"Total Number of acceptors for this meeting \(including emergencies\)\s*(\d+)", page)
    if not races or not total:
        raise Invalid("No complete final field found; page may be unpublished or format changed")
    if [int(m[1]) for m in races] != list(range(1, len(races)+1)):
        raise Invalid("Nonconsecutive or duplicate official race numbers")
    going = re.search(r"Track Condition:\s*(.*?)\s+Weather:", page)
    rail = re.search(r"Rail Position:\s*(.*?)\s+Dual Track Meeting:", page)
    publication = re.search(r"FinalFields Last Published:\s*\w+ (\d{2}-\w{3}-\d{2} \d{1,2}:\d{2}[AP]M) (AEST|AEDT)", page)
    published = None
    if publication:
        published = datetime.strptime(publication[1], "%d-%b-%y %I:%M%p").replace(tzinfo=ZoneInfo(meeting["timezone"])).isoformat()
    documents = []
    count = 0
    for i, match in enumerate(races):
        section = raw[match.end():races[i+1].start() if i+1<len(races) else len(raw)]
        table = re.search(r'<table\b[^>]*class=[\'\"]race-strip-fields[\'\"][^>]*>(.*?)</table>', section, re.S|re.I)
        if not table:
            raise Invalid(f"Missing runners table for race {match[1]}")
        runners = []
        for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>', table[1], re.S|re.I):
            cells = {cls: (plain(body), body) for cls, body in re.findall(r'<td\b[^>]*class=[\'\"]([^\'\"]+)[\'\"][^>]*>(.*?)</td>', row, re.S|re.I)}
            if not cells:
                continue
            if not {"no", "horse"} <= cells.keys():
                raise Invalid("Unrecognized runner row")
            horse = cells["horse"]
            link = re.search(r'href="([^"]*HorseFullForm[^\"]*)"', horse[1], re.I)
            if not link:
                raise Invalid("Runner lacks official identity link")
            address = urljoin(source_url, html.unescape(link[1]))
            horsecode = parse_qs(urlsplit(address).query).get("horsecode", [None])[0]
            if not horsecode:
                raise Invalid("Missing official horse code")
            number = cells["no"][0]
            scratched = bool(re.search(r'<(?:s|strike|del)\b|line-through|scratched', row, re.I))
            status = "scratched" if scratched else "emergency" if number.lower().endswith("e") else "active"
            runners.append({"id": "ra:"+horsecode, "name": horse[0], "number":number, "status":status,
                            "official_url":address, **{k:cells.get(c,("",))[0] for k,c in (("barrier","barrier"),("jockey","jockey"),("trainer","trainer"),("weight","weight"),("form","last"))}})
        count += len(runners)
        start = datetime.strptime(meeting["date"]+" "+match[2], "%Y-%m-%d %I:%M%p").replace(tzinfo=ZoneInfo(meeting["timezone"])).isoformat()
        documents.append({"kind":"field", "meeting_id":meeting["id"], "race_no":int(match[1]), "source_url":source_url,
                          "publisher":"Racing Australia", "observed_at":observed, "published_at":published,
                          "payload":{"race_name":plain(match[3]), "start_at":start, "runners":runners,
                                     "going":going[1] if going else None, "rail":rail[1] if rail else None,
                                     "official":True, "card_races":len(races)}})
    if count != int(total[1]):
        raise Invalid(f"Parsed {count} runners but official acceptor total is {total[1]}; refusing partial card")
    return documents


def fetch_fields(meeting, store, config):
    address = official_url(meeting)
    observed = now()
    try:
        with urlopen(Request(address, headers={"User-Agent":"PuntingPowerAI/0.1 local research"}), timeout=30) as response:
            raw = response.read(3_000_001)
            if len(raw)>3_000_000:
                raise Invalid("Official page exceeds size limit")
        observed = now()
        documents = parse_fields(raw.decode("utf-8-sig"), meeting, observed, address)
        # Validate the entire card before inserting any race.
        from .core import validate
        for d in documents:
            validate(d,config)
        ids = [store.add(d,config) for d in documents]
        detail = f"Verified complete official card: {len(documents)} races, {sum(len(d['payload']['runners']) for d in documents)} acceptors. Response SHA256 {hashlib.sha256(raw).hexdigest()}."
        status = "checked with relevant evidence"
    except Exception as exc:
        ids = []
        status, detail = "failed", f"{type(exc).__name__}: {exc}. Failure does not establish that fields are unpublished."
    store.add({"kind":"coverage", "meeting_id":meeting["id"], "source_url":address, "publisher":"Racing Australia", "observed_at":observed,
               "published_at":None, "payload":{"source":"Official fields", "status":status, "detail":detail, "checked_urls":[address]}},config)
    return ids, detail
