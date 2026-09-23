"""Read-only Betfair Exchange prices for the configured meetings. Never places bets.

You log in yourself with `python -m punting.betfair login`. Your password goes once
to Betfair's Australian login endpoint and is never stored; only the session token
is kept, in data/private/ (ignored by Git). No command prints the token.
"""
import argparse
import getpass
import json
import os
import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .core import Invalid, local, now, stamp
from .model import history_key

IDENTITY = "https://identitysso.betfair.com.au/api/"  # Australian and New Zealand accounts
BETTING = "https://api.betfair.com/exchange/betting/json-rpc/v1"
HORSE_RACING = "7"
# Official venue names that Betfair shortens.
VENUES = {"Rosehill Gardens": "Rosehill"}
START_TOLERANCE_MINUTES = 10
TERMS = "Best available back price and size; delayed API key (1-180 s); commission is the market base rate, before any personal discount"


def settings(path=".env"):
    """KEY=VALUE lines from .env, overridden by BETFAIR_* environment variables. Values are never printed."""
    values = {}
    if Path(path).exists():
        for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and key and not key.startswith("#"):
                values[key.strip()] = value.strip().strip("\"'")
    values.update({k: v for k, v in os.environ.items() if k.startswith("BETFAIR_")})
    if not values.get("BETFAIR_APP_KEY"):
        raise Invalid("Put your Delayed key in .env as BETFAIR_APP_KEY (see .env.example)")
    return values


def request(url, body=None, headers=None):
    try:
        with urlopen(Request(url, data=body, headers=headers or {}), timeout=30) as response:
            return json.load(response)
    except HTTPError as e:
        raise Invalid(f"Betfair returned HTTP {e.code} for {url.rsplit('/', 1)[-1]}") from None
    except URLError as e:
        raise Invalid(f"Could not reach Betfair: {e.reason}") from None


def login(values, session, ssoid=False):
    """You type the password (or paste a browser ssoid); only the resulting token is saved."""
    if ssoid:
        token = getpass.getpass("Paste the ssoid from your betfair.com.au cookies (hidden): ").strip()
    else:
        user = values.get("BETFAIR_USERNAME") or input("Betfair username: ").strip()
        password = getpass.getpass("Betfair password (hidden; add your 2-step code to the end if you use one): ")
        reply = request(IDENTITY + "login", urlencode({"username": user, "password": password}).encode(),
                        {"X-Application": values["BETFAIR_APP_KEY"], "Accept": "application/json",
                         "Content-Type": "application/x-www-form-urlencoded"})
        if reply.get("status") != "SUCCESS":
            raise Invalid("Betfair login failed: " + (reply.get("error") or reply.get("status") or "unknown reason"))
        token = reply.get("token", "")
    if not token:
        raise Invalid("Betfair returned no session token")
    session.parent.mkdir(parents=True, exist_ok=True)
    session.write_text(json.dumps({"token": token, "saved_at": now()}), encoding="utf-8")
    keep_alive(values, session)


def keep_alive(values, session):
    """Verify and extend the saved session. Returns the token for API headers; never prints it."""
    if not session.exists():
        raise Invalid("No Betfair session: run `python -m punting.betfair login` yourself first")
    token = json.loads(session.read_text(encoding="utf-8"))["token"]
    reply = request(IDENTITY + "keepAlive", None, {"X-Application": values["BETFAIR_APP_KEY"], "X-Authentication": token, "Accept": "application/json"})
    if reply.get("status") != "SUCCESS":
        raise Invalid("Betfair session expired or invalid (" + (reply.get("error") or "unknown") + "): log in again")
    return token


def call(values, token, method, params):
    body = json.dumps({"jsonrpc": "2.0", "method": "SportsAPING/v1.0/" + method, "params": params, "id": 1}).encode()
    reply = request(BETTING, body, {"X-Application": values["BETFAIR_APP_KEY"], "X-Authentication": token,
                                    "Content-Type": "application/json", "Accept": "application/json"})
    if "error" in reply:
        error = reply["error"]
        raise Invalid(f"Betfair {method} failed: " + str(error.get("data", {}).get("APINGException", {}).get("errorCode") or error.get("message")))
    return reply["result"]


def utc(moment):
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def catalogue(values, token, meeting):
    """Australian WIN markets at the meeting's venue on its local date."""
    start = datetime.combine(date.fromisoformat(meeting["date"]), time(), ZoneInfo(meeting["timezone"]))
    return call(values, token, "listMarketCatalogue", {
        "filter": {"eventTypeIds": [HORSE_RACING], "marketCountries": ["AU"], "marketTypeCodes": ["WIN"],
                   "venues": [VENUES.get(meeting["venue"], meeting["venue"])],
                   "marketStartTime": {"from": utc(start), "to": utc(start + timedelta(days=1))}},
        "marketProjection": ["MARKET_START_TIME", "RUNNER_DESCRIPTION", "RUNNER_METADATA", "MARKET_DESCRIPTION", "EVENT"],
        "sort": "FIRST_TO_START", "maxResults": 60})


def plain_name(runner_name):
    # Australian runner names carry the saddlecloth: "1. Guest House".
    return re.sub(r"^\d+[a-z]?\.\s*", "", runner_name)


def match(markets, fields):
    """Official race number -> (market, {official runner id: selection id}, unmatched official names).
    A market must agree on race number and start time; a runner on saddlecloth number and name. No fuzzy joins."""
    matched = {}
    for market in markets:
        number = re.match(r"R(\d+)\b", market.get("marketName", ""))
        field = fields.get(int(number[1])) if number else None
        if not field:
            continue
        gap = abs((stamp(market["marketStartTime"]) - stamp(field["payload"]["start_at"])).total_seconds())
        if gap > START_TOLERANCE_MINUTES*60:
            continue
        selections, unmatched = {}, []
        for runner in field["payload"]["runners"]:
            if runner["status"] == "scratched":
                continue
            found = [s["selectionId"] for s in market.get("runners", [])
                     if str((s.get("metadata") or {}).get("CLOTH_NUMBER", "")).strip() == runner["number"].rstrip("e")
                     and history_key(plain_name(s["runnerName"])) == history_key(runner["name"])]
            if len(found) == 1:
                selections[runner["id"]] = found[0]
            else:
                unmatched.append(runner["name"])
        matched[int(number[1])] = (market, selections, unmatched)
    return matched


def book(values, token, market_ids):
    if not market_ids:
        return {}
    result = call(values, token, "listMarketBook", {"marketIds": market_ids, "priceProjection": {
        "priceData": ["EX_BEST_OFFERS"], "virtualise": True, "exBestOffersOverrides": {"bestPricesDepth": 1}}})
    return {b["marketId"]: b for b in result}


def quotes_document(meeting_id, race_no, field, market, prices, selections, observed):
    """A store `quotes` snapshot of best back prices, or (None, reason) when the market can't be stored."""
    if prices.get("status") != "OPEN" or prices.get("inplay"):
        return None, f"market {prices.get('status', 'missing').lower()}{', in-play' if prices.get('inplay') else ''}"
    if any(r["status"] == "emergency" for r in field["payload"]["runners"]):
        return None, "emergencies unresolved: refresh the official field before storing prices"
    names = {r["id"]: r["name"] for r in field["payload"]["runners"]}
    by_selection = {r["selectionId"]: r for r in prices.get("runners", [])}
    rows = []
    for runner_id, selection in selections.items():
        runner = by_selection.get(selection)
        back = (runner or {}).get("ex", {}).get("availableToBack") or []
        if runner and runner.get("status") == "ACTIVE" and back:
            rows.append({"runner_id": runner_id, "name": names[runner_id], "odds": back[0]["price"], "size": back[0]["size"]})
    if not rows:
        return None, "no back prices yet"
    rate = (market.get("description") or {}).get("marketBaseRate")
    return {"kind": "quotes", "meeting_id": meeting_id, "race_no": race_no,
            "source_url": f"https://www.betfair.com.au/exchange/plus/horse-racing/market/{market['marketId']}",
            "publisher": "Betfair Exchange API", "observed_at": observed, "published_at": None,
            "payload": {"field_id": field["id"], "provider": "Betfair Exchange", "market": "exchange_back_win",
                        "commission": rate/100 if rate is not None else None, "terms": TERMS, "rows": rows}}, None


def run(store, config, values, token, save):
    """Match every configured race to its Betfair market; store best back prices when `save`."""
    output = []
    for meeting in config["meetings"]:
        fields = {}
        for d in store.all(meeting["id"]):
            if d["kind"] == "field":
                fields[d["race_no"]] = d
        matched = match(catalogue(values, token, meeting), fields)
        books = book(values, token, [m["marketId"] for m, _, _ in matched.values()])
        for n in sorted(fields):
            if n not in matched:
                output.append(f"{meeting['id']} R{n}: no Betfair WIN market found yet")
                continue
            market, selections, unmatched = matched[n]
            prices = books.get(market["marketId"], {})
            line = f"{meeting['id']} R{n}: {market['marketName']} ({market['marketId']}), {len(selections)} runners matched, market {prices.get('status', 'missing')}"
            if prices.get("isMarketDataDelayed"):
                line += ", delayed prices"
            if unmatched:
                line += "; unmatched: " + ", ".join(unmatched)
            if save:
                observed = now()
                d, reason = quotes_document(meeting["id"], n, fields[n], market, prices, selections, observed)
                try:
                    line += f"; stored {store.add(d, config)[:12]}" if d else f"; not stored: {reason}"
                except Invalid as e:
                    line += f"; not stored: {e}"
            output.append(line)
    return output


def main():
    parser = argparse.ArgumentParser(description="Read-only Betfair Exchange prices; never places bets")
    parser.add_argument("command", choices=["login", "check", "snapshot"],
                        help="login: you log in; check: match markets without storing; snapshot: store best back prices")
    parser.add_argument("--ssoid", action="store_true", help="paste a browser session token instead of typing your password")
    parser.add_argument("--data", default="data")
    parser.add_argument("--config", default="config.json")
    args = parser.parse_args()
    values = settings()
    session = Path(args.data)/"private"/"betfair-session.json"
    if args.command == "login":
        login(values, session, args.ssoid)
        print(f"Logged in. Session saved to {session} (ignored by Git); the token is not shown.")
        return
    from .store import Store
    token = keep_alive(values, session)
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    store = Store(args.data)
    try:
        print(f"Checked at {local(now())}")
        print("\n".join(run(store, config, values, token, args.command == "snapshot")))
    finally:
        store.close()


if __name__ == "__main__":
    import sys
    try:
        main()
    except (Invalid, ValueError, OSError, KeyError) as exc:
        print("Error: " + str(exc), file=sys.stderr)
        sys.exit(1)
