"""BOM précis forecasts from the Bureau's anonymous FTP product feed.

www.bom.gov.au/fwo/ is robots-disallowed for generic agents; the same products are published at
ftp.bom.gov.au/anon/gen/fwo/ for automated retrieval. Forecasts become meeting-level evidence whose
publication time is the product issue time. They are race context, never probability adjustments.
"""
import hashlib
import xml.etree.ElementTree as ET
from datetime import date
from ftplib import FTP, all_errors
from pathlib import Path
from zoneinfo import ZoneInfo
from ..core import Invalid, local, now, stamp

HOST = "ftp.bom.gov.au"
FOLDER = "/anon/gen/fwo"
PRODUCTS = {"NSW": "IDN11060", "ACT": "IDN11060", "VIC": "IDV10753"}
# Nearest précis locations, primary first. Rosehill Gardens sits about 2 km east of Parramatta, with
# Sydney Olympic Park 5 km further east. Caulfield lies between Melbourne (CBD) and Moorabbin.
LOCATIONS = {"Rosehill Gardens": ["Parramatta", "Sydney Olympic Park"], "Randwick": ["Sydney"], "Royal Randwick": ["Sydney"],
             "Canterbury Park": ["Canterbury"], "Warwick Farm": ["Liverpool"], "Caulfield": ["Melbourne", "Moorabbin"],
             "Flemington": ["Melbourne"], "Moonee Valley": ["Melbourne"], "Sandown": ["Dandenong"]}
MAX_BYTES = 5_000_000


def citation(product):
    return f"https://www.bom.gov.au/fwo/{product}.xml"


def download(product, connect=FTP):
    try:
        ftp = connect(HOST, timeout=30)
        ftp.login()
        ftp.cwd(FOLDER)
        buf = bytearray()
        ftp.retrbinary(f"RETR {product}.xml", buf.extend)
        ftp.quit()
    except all_errors as e:
        raise Invalid(f"BOM FTP {product}: {type(e).__name__}: {e}") from None
    if len(buf) > MAX_BYTES:
        raise Invalid("BOM product exceeds size limit")
    return bytes(buf)


def parse(raw):
    if b"<!DOCTYPE" in raw[:2000] or b"<!ENTITY" in raw:
        raise Invalid("Refusing XML with a DOCTYPE or entity declarations")
    root = ET.fromstring(raw)
    amoc = root.find("amoc")
    if amoc is None or amoc.findtext("product-type") != "F":
        raise Invalid("Not a BOM forecast product")
    issued = amoc.findtext("issue-time-utc")
    areas = {}
    for area in root.iter("area"):
        if area.get("type") != "location":
            continue
        periods = []
        for fp in area.findall("forecast-period"):
            v = {e.get("type"): (e.text or "").strip() for e in fp}
            periods.append({"start": fp.get("start-time-local"), "precis": v.get("precis"), "pop": v.get("probability_of_precipitation"),
                            "rain": v.get("precipitation_range"), "min": v.get("air_temperature_minimum"), "max": v.get("air_temperature_maximum")})
        areas[area.get("description")] = periods
    return {"product": amoc.findtext("identifier"), "issued_at": stamp(issued).isoformat(), "status": amoc.findtext("status"), "areas": areas}


def describe(p):
    day = date.fromisoformat(p["start"][:10]).strftime("%a %d %b")
    parts = [p["precis"] or "no précis", f"rain chance {p['pop'] or 'not given'}"]
    if p["rain"]:
        parts.append(p["rain"])
    if p["max"]:
        parts.append(f"max {p['max']}°C")
    return f"{day}: " + ", ".join(parts)


def forecast_docs(meeting, parsed, observed):
    """One evidence document per location whose forecast window reaches race day, plus the coverage record."""
    if meeting["venue"] not in LOCATIONS:
        raise Invalid(f"No BOM location mapping for {meeting['venue']}")
    product, day = parsed["product"], meeting["date"]
    today = stamp(observed).astimezone(ZoneInfo(meeting["timezone"])).date().isoformat()
    docs, missing = [], []
    for name in LOCATIONS[meeting["venue"]]:
        periods = parsed["areas"].get(name)
        if periods is None:
            raise Invalid(f"{name} is missing from BOM product {product}")
        race_day = [p for p in periods if p["start"][:10] == day]
        if not race_day:
            missing.append(name)
            continue
        lead = [p for p in periods if today <= p["start"][:10] < day and p["max"]]
        summary = (f"BOM {product} précis for {name} (issued {local(parsed['issued_at'])}). Race day — {describe(race_day[0])}."
                   + (" Lead-in — " + "; ".join(describe(p) for p in lead) + "." if lead else ""))
        docs.append({"kind": "evidence", "meeting_id": meeting["id"], "source_url": citation(product), "publisher": "Bureau of Meteorology",
                     "observed_at": observed, "published_at": parsed["issued_at"],
                     "payload": {"runner_ids": [], "author": None, "original_url": citation(product),
                                 "claim_id": f"bom:{product}:{name}:{day}:{parsed['issued_at']}", "excerpt": race_day[0]["precis"] or "",
                                 "summary": summary, "type": "forecast", "conditions": [], "reviewed": True}})
    status = "checked with relevant evidence" if docs else "not yet published"
    detail = (f"Précis product {product} issued {local(parsed['issued_at'])}, retrieved via anonymous FTP ftp://{HOST}{FOLDER}/{product}.xml. "
              f"Locations: {', '.join(LOCATIONS[meeting['venue']])}."
              + (f" Race day outside the forecast window for: {', '.join(missing)}." if missing else "")
              + " Forecasts are context only; the official track rating decides the going.")
    coverage = {"kind": "coverage", "meeting_id": meeting["id"], "source_url": citation(product), "publisher": "Bureau of Meteorology",
                "observed_at": observed, "published_at": None,
                "payload": {"source": "BOM", "status": status, "detail": detail, "checked_urls": [citation(product)]}}
    return docs, coverage


def refresh(store, config, meeting_ids=None, root="data", connect=FTP):
    """Fetch each needed product once, archive the official XML privately, store forecasts and coverage."""
    results, cache = [], {}
    for m in config["meetings"]:
        if meeting_ids and m["id"] not in meeting_ids:
            continue
        product = PRODUCTS.get(m["state"])
        observed = now()
        try:
            if product is None:
                raise Invalid(f"No BOM précis product configured for {m['state']}")
            if product not in cache:
                raw = download(product, connect)
                observed = now()
                folder = Path(root) / "private" / "bom"
                folder.mkdir(parents=True, exist_ok=True)
                sha = hashlib.sha256(raw).hexdigest()
                path = folder / f"{product}-{sha[:16]}.xml"
                if not path.exists():
                    path.write_bytes(raw)
                cache[product] = (parse(raw), observed, sha)
            parsed, observed, sha = cache[product]
            docs, coverage = forecast_docs(m, parsed, observed)
            coverage["payload"]["detail"] += f" Product SHA256 {sha}."
            ids = [store.add(d, config) for d in docs]
            store.add(coverage, config)
            results.append(f"{m['id']}: {len(ids)} forecast record(s); {coverage['payload']['status']}")
        except Invalid as e:
            store.add({"kind": "coverage", "meeting_id": m["id"], "source_url": citation(product or "IDN11060"), "publisher": "Bureau of Meteorology",
                       "observed_at": observed, "published_at": None,
                       "payload": {"source": "BOM", "status": "failed", "detail": f"{e}. A failed retrieval is not evidence of settled weather.",
                                   "checked_urls": [citation(product or "IDN11060")]}}, config)
            results.append(f"{m['id']}: failed — {e}")
    return results
