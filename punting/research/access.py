"""Source access policy, RFC 9309 robots evaluation and polite page capture.

Routes were decided from robots.txt and live requests on 23 Sep 2026 (RESEARCH.md has the evidence):
http    this code may fetch the page itself
ftp     an official product feed intended for automated retrieval
browser a person reads the page in a normal browser; its visible text is registered here
manual  user-provided exports or excerpts only
Captured page text goes to a private local cache so excerpts can be verified verbatim; it is never committed.
"""
import hashlib
import json
import re
import time
import unicodedata
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from ..core import Invalid, now, stamp, url

AGENT = "PuntingPowerAI"
UA = AGENT + "/0.1 local research (personal, non-commercial)"
MAX_BYTES = 5_000_000
MIN_INTERVAL = 3.0  # seconds between requests to one host, raised by any Crawl-delay

# "hosts" own the fetch route. "also_on" lists hosts that carry this source's material (attribution only).
POLICY = {
    "Official fields": {"route": "http", "hosts": ["www.racingnsw.com.au", "www.australianturfclub.com.au", "www.racingvictoria.com.au"],
                        "also_on": ["www.racingaustralia.horse", "racingaustralia.horse", "www.racing.com"],
                        "why": "Racing NSW, ATC and RV pages allow generic agents. Racing Australia FreeFields is robots-disallowed (User-agent * Disallow: /FreeFields/), so read it in a browser or import it."},
    "BOM": {"route": "ftp", "hosts": ["ftp.bom.gov.au"], "also_on": ["www.bom.gov.au"],
            "why": "www.bom.gov.au robots.txt disallows /fwo/ for generic agents; the Bureau's anonymous FTP publishes the same forecast products for automated retrieval."},
    "Just Horse Racing": {"route": "browser", "hosts": ["www.justhorseracing.com.au"],
                          "why": "Returns HTTP 403 to non-browser clients, including for robots.txt. Read in a browser; no bypass."},
    "Punters": {"route": "browser", "hosts": ["www.punters.com.au"],
                "why": "robots.txt disallows every path for generic agents. Read individual pages in a browser only."},
    "Wolfden": {"route": "manual", "hosts": ["wolfden.bet", "www.wolfden.bet", "www.wolfden.win"], "also_on": ["www.betfair.com.au"],
                "why": "Tips live in the Wolfden app (wolfden.win redirects to it). Use user-provided excerpts, or Wolfden-attributed posts on Betfair Hub."},
    "The Daily Punt": {"route": "http", "hosts": ["thedailypunt.com.au"],
                       "why": "robots.txt allows all but /admin and /api/. thedailypunt.com is an unrelated football site. Its ratings are supplied by PuntersTech: a separate numeric product."},
    "Racing.com": {"route": "http", "hosts": ["www.racing.com"],
                   "why": "robots.txt allows all. News renders server-side; form guide and speed map pages need JavaScript, so read those in a browser."},
}
# Supplementary publishers: usable, attributed evidence, but not one of the named coverage sources.
SUPPLEMENTARY = {"www.justracing.com.au": "Just Racing", "www.racingfans.com.au": "RacingFans", "www.betfair.com.au": "Betfair Hub"}


def owner(host):
    """The one source that owns a host's fetch route, or None."""
    named = [name for name, p in POLICY.items() if host in p["hosts"]]
    if len(named) > 1:
        raise Invalid(f"Host {host} has conflicting source policies")
    return named[0] if named else SUPPLEMENTARY.get(host)


def attributable(source, host):
    """Whether material on this host may be recorded as coming from this source."""
    if source in POLICY:
        return host in POLICY[source]["hosts"] or host in POLICY[source].get("also_on", [])
    return SUPPLEMENTARY.get(host) == source

_last = {}
_robots = {}


def pattern_regex(pattern):
    """RFC 9309 path pattern: '*' matches any sequence, a trailing '$' anchors the end."""
    anchored = pattern.endswith("$")
    body = re.escape(pattern[:-1] if anchored else pattern).replace(r"\*", ".*")
    return re.compile(body + ("$" if anchored else ""))


def robots_rules(body, agent=AGENT):
    """Rules for our product token, else the '*' groups. Groups naming the same agent are merged."""
    groups, current, in_rules = [], None, False
    for raw in body.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = (x.strip() for x in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if current is None or in_rules:
                current = {"agents": set(), "rules": [], "delay": None}
                groups.append(current)
                in_rules = False
            current["agents"].add(value.lower())
        elif current is not None and key in {"allow", "disallow"}:
            in_rules = True
            if value:
                current["rules"].append((key == "allow", value))
        elif current is not None and key == "crawl-delay":
            in_rules = True
            try:
                current["delay"] = float(value)
            except ValueError:
                pass
    mine = [g for g in groups if agent.lower() in g["agents"]] or [g for g in groups if "*" in g["agents"]]
    delays = [g["delay"] for g in mine if g["delay"] is not None]
    return {"rules": [r for g in mine for r in g["rules"]], "delay": max(delays) if delays else None}


def robots_allows(policy, path):
    """Longest matching pattern wins; allow wins a tie. /robots.txt itself is always allowed."""
    if path == "/robots.txt":
        return True
    best = None
    for allow, pattern in policy["rules"]:
        if pattern_regex(pattern).match(path):
            rank = (len(pattern.encode()), allow)
            if best is None or rank > best:
                best = rank
    return best is None or best[1]


def robots_for(origin, opener=urlopen):
    """RFC 9309 status handling: 4xx means no restrictions; 5xx or unreachable means disallow everything."""
    if origin in _robots:
        return _robots[origin]
    try:
        with opener(Request(origin + "/robots.txt", headers={"User-Agent": UA}), timeout=20) as r:
            policy = dict(robots_rules(r.read(500_000).decode("utf-8", "replace")), status=r.status)
    except HTTPError as e:
        e.close()
        policy = {"rules": [] if 400 <= e.code < 500 else [(False, "/")], "delay": None, "status": e.code}
    except (URLError, OSError) as e:
        policy = {"rules": [(False, "/")], "delay": None, "status": type(e).__name__}
    _robots[origin] = policy
    return policy


def source_for(address):
    return owner(urlsplit(address).hostname or "")


class Readable(HTMLParser):
    """Visible text with block breaks. Scripts are skipped, except Next.js page data where articles often live."""
    SKIP = {"script", "style", "noscript", "template", "svg", "iframe", "head"}
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "td", "th", "section", "article", "header", "footer", "blockquote", "table", "ul", "ol", "figure", "figcaption"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.title, self.data, self.skip, self.mode = [], [], [], 0, None

    def handle_starttag(self, tag, attrs):
        if tag == "title" and not self.title:
            self.mode = "title"
        elif tag == "script" and dict(attrs).get("id") == "__NEXT_DATA__":
            self.mode = "data"
        if tag in self.SKIP:
            self.skip += 1
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"title", "script"}:
            self.mode = None
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.mode == "title":
            self.title.append(data)
        elif self.mode == "data":
            self.data.append(data)
        elif not self.skip:
            self.parts.append(data)


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from strings(v)


def readable(raw):
    p = Readable()
    p.feed(raw)
    lines = [" ".join(line.split()) for line in "".join(p.parts).splitlines()]
    out = "\n".join(line for line in lines if line)
    if p.data:
        try:
            embedded = []
            for s in strings(json.loads("".join(p.data))):
                s = readable(s)[1] if "<" in s else " ".join(s.split())
                if len(s.split()) >= 6 and s not in embedded:
                    embedded.append(s)
            if embedded:
                out += "\n[Embedded page data]\n" + "\n".join(embedded)
        except (ValueError, RecursionError):
            pass
    return " ".join("".join(p.title).split()), out


def normal(value):
    """Comparison form for verification: NFKC, straight quotes, plain dashes, casefolded, single spaces."""
    value = unicodedata.normalize("NFKC", value)
    value = re.sub(r"[‘’‚‛′`]", "'", value)
    value = re.sub(r"[“”„″]", '"', value)
    value = re.sub(r"[‐-―−]", "-", value)
    return " ".join(value.casefold().split())


def cache_text(content, cache):
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256(content.encode()).hexdigest()
    path = cache / f"{sha}.txt"
    if path.exists():
        if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            raise Invalid("Cached page text was modified: " + path.name)
    else:
        with path.open("x", encoding="utf-8", newline="") as f:
            f.write(content)
    return sha


def cached(sha, cache):
    path = Path(cache) / f"{sha}.txt"
    if not path.exists():
        return None
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != sha:
        raise Invalid("Cached page text was modified: " + path.name)
    return content.decode("utf-8")


def fetch(address, cache="data/private/pages", opener=urlopen, pause=time.sleep):
    """Fetch one page if policy and robots.txt allow it. Returns a page record for an evidence pack."""
    raw, status, source = get(address, opener, pause)
    observed = now()
    title, content = readable(raw.decode("utf-8", "replace"))
    return {"id": None, "source": source, "url": address, "publisher": source, "author": None, "title": title or None,
            "published_at": None, "observed_at": observed, "route": "http", "text_sha256": cache_text(content, cache),
            "http_status": status, "raw_sha256": hashlib.sha256(raw).hexdigest()}


def links(address, pattern=".", opener=urlopen, pause=time.sleep):
    """Same-host article links on a listing page, through the same policy and robots gates. Nothing is cached."""
    raw, _, _ = get(address, opener, pause)
    host = urlsplit(address).hostname
    found = []
    for href in re.findall(r'href="([^"#]+)"', raw.decode("utf-8", "replace")):
        full = href if href.startswith("http") else f"{urlsplit(address).scheme}://{host}{href}" if href.startswith("/") else None
        if full and urlsplit(full).hostname == host and re.search(pattern, full, re.I) and full not in found:
            found.append(full)
    return found


def get(address, opener=urlopen, pause=time.sleep):
    url(address)
    parts = urlsplit(address)
    source = source_for(address)
    route = POLICY[source]["route"] if source in POLICY else "http" if source else None
    if route != "http":
        why = POLICY[source]["why"] if source in POLICY else "host is not in the research source policy"
        raise Invalid(f"Automated fetch not permitted for {parts.hostname}: {why}")
    origin = f"{parts.scheme}://{parts.netloc}"
    robots = robots_for(origin, opener)
    path = (parts.path or "/") + ("?" + parts.query if parts.query else "")
    if not robots_allows(robots, path):
        raise Invalid(f"robots.txt disallows {path} for {AGENT} on {parts.hostname}")
    wait = max(MIN_INTERVAL, min(robots["delay"] or 0, 30)) - (time.monotonic() - _last.get(origin, -1e9))
    if wait > 0:
        pause(wait)
    _last[origin] = time.monotonic()
    try:
        with opener(Request(address, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml"}), timeout=30) as r:
            final = r.geturl() if hasattr(r, "geturl") else address
            if urlsplit(final).hostname != parts.hostname:
                raise Invalid(f"Refusing cross-host redirect to {final}")
            kind = (r.headers.get("Content-Type") or "").lower()
            if kind and not any(t in kind for t in ("html", "xml", "text")):
                raise Invalid(f"Unexpected content type {kind!r}")
            raw = r.read(MAX_BYTES + 1)
            status = r.status
    except HTTPError as e:
        e.close()
        raise Invalid(f"HTTP {e.code} from {address}; a failed fetch is not evidence that nothing was published") from None
    except (URLError, OSError) as e:
        raise Invalid(f"{type(e).__name__} fetching {address}: {e}") from None
    if len(raw) > MAX_BYTES:
        raise Invalid("Page exceeds size limit")
    return raw, status, source


# Runs inside a normal browser tab on a browser-route page, so the article never leaves the page.
# Mirrors normal()/horse_key()/named_in(): returns the visible-text SHA-256 and, per excerpt, whether it
# occurs verbatim and whether each claimed horse is named within 600 characters of it.
CHECKER = r"""async (input) => {
  const norm = s => s.normalize('NFKC').replace(/[‘’‚‛′`]/g, "'").replace(/[“”„″]/g, '"')
    .replace(/[‐-―−]/g, '-').toLowerCase().split(/\s+/).filter(Boolean).join(' ');
  const key = s => s.normalize('NFKC').toUpperCase().replace(/[‘’‛'`]/g, '').replace(/\s*\(([A-Z]{2,4})\)\s*$/, '')
    .replace(/[^A-Z0-9]+/g, ' ').trim();
  const named = (w, n) => { const k = ' ' + key(n) + ' '; return [w, w.replace(/'s\b/gi, '')].some(v => (' ' + key(v) + ' ').includes(k)); };
  const text = document.body.innerText.split('\n').map(l => l.split(/\s+/).filter(Boolean).join(' ')).filter(Boolean).join('\n');
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  const sha = Array.from(new Uint8Array(digest)).map(b => b.toString(16).padStart(2, '0')).join('');
  const hay = norm(text), excerpts = {};
  for (const c of input.claims) {
    const needle = norm(c.excerpt), wins = [];
    for (let i = needle ? hay.indexOf(needle) : -1; i >= 0; i = hay.indexOf(needle, i + 1)) wins.push(hay.slice(Math.max(0, i - 600), i + needle.length + 600));
    excerpts[c.excerpt] = {found: wins.length > 0, near: Object.fromEntries(c.runners.map(n => [n, wins.some(w => named(w, n))]))};
  }
  const names = Object.fromEntries((input.names || []).map(n => [n, named(hay, n)]));
  return {url: location.href, checked_at: new Date().toISOString(), text_sha256: sha, words: text.split(/\s+/).length, excerpts, names_in_page: names};
}"""


def checker_call(claims, names=()):
    """JavaScript to paste into a browser tab: claims are [{'excerpt': str, 'runners': [names]}]."""
    return f"await ({CHECKER})({json.dumps({'claims': claims, 'names': list(names)}, ensure_ascii=False)})"


def purge_text(cache="data/private/pages"):
    """Delete transient page text once packs are imported. Metadata and hashes stay in the store."""
    removed = 0
    for path in Path(cache).glob("*.txt"):
        path.unlink()
        removed += 1
    return removed


def register_text(path, address, observed_at, route="browser", cache="data/private/pages"):
    """Register visible text captured from a normal browser session or user paste."""
    url(address)
    if route not in {"browser", "manual"}:
        raise Invalid("Registered text must come from a browser session or manual import")
    stamp(observed_at)
    content = Path(path).read_text(encoding="utf-8-sig")
    lines = [" ".join(line.split()) for line in content.splitlines()]
    content = "\n".join(line for line in lines if line)
    if len(content.split()) < 20:
        raise Invalid("Captured text is too short to verify anything")
    source = source_for(address)
    return {"id": None, "source": source, "url": address, "publisher": source, "author": None, "title": None,
            "published_at": None, "observed_at": observed_at, "route": route, "text_sha256": cache_text(content, cache)}
