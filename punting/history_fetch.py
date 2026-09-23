"""Download the fixed research dataset from Betfair's public listing; no login."""
import hashlib
import html
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import urlopen
from .core import Invalid, now

LISTING = "https://betfair-datascientists.github.io/data/dataListing/"
NAMES = ["ANZ_Thoroughbreds_2024.zip", "ANZ_Thoroughbreds_2025.zip"] + [f"ANZ_Thoroughbreds_2026_{month:02}.csv" for month in range(1,9)]


def download(address):
    if urlsplit(address).hostname != "betfair-datascientists.github.io":
        raise Invalid("Unexpected download host")
    with urlopen(address, timeout=45) as r:
        if urlsplit(r.url).hostname != "betfair-datascientists.github.io":
            raise Invalid("Unexpected redirect")
        data = r.read(80*1024*1024+1)
    if len(data)>80*1024*1024:
        raise Invalid("Source exceeds 80 MiB limit")
    return data


def fetch(root="data/history"):
    root = Path(root); root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else []
    known = {item["name"]:item for item in manifest}
    listing = download(LISTING).decode()
    links = {Path(urlsplit(urljoin(LISTING,html.unescape(h))).path).name:urljoin(LISTING,html.unescape(h)) for h in re.findall(r'href="([^"]+)"',listing)}
    for name in NAMES:
        path = root / name
        if path.exists():
            if name not in known or hashlib.sha256(path.read_bytes()).hexdigest()!=known[name]["sha256"]:
                raise Invalid("Unverified or modified cached archive: "+name)
            print("Verified "+name, flush=True)
            continue
        if name not in links:
            raise Invalid("Requested source is not in official listing: "+name)
        data = download(links[name])
        if data[:200].lstrip().startswith(b"<"):
            raise Invalid("Expected archive, received HTML")
        with path.open("xb") as f:
            f.write(data)
        manifest.append({"name":name,"source_url":links[name],"observed_at":now(),"sha256":hashlib.sha256(data).hexdigest(),"bytes":len(data)})
        manifest_path.write_text(json.dumps(manifest,indent=2),encoding="utf-8")
        print(f"Downloaded {name}: {len(data):,} bytes",flush=True)


if __name__ == "__main__":
    fetch()
