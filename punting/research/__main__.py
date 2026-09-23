"""python -m punting.research <command>: research acquisition CLI. See RESEARCH.md for the workflow."""
import argparse
import json
import sys
from pathlib import Path
from ..core import Invalid, now
from ..store import Store


def main():
    parser = argparse.ArgumentParser(description="PuntingPowerAI research: sources, evidence packs, BOM forecasts, research digests")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--data", default="data")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("sources", help="print the source access policy")
    fetch = commands.add_parser("fetch", help="capture pages whose source allows automated fetching; prints page records")
    fetch.add_argument("urls", nargs="+")
    discover = commands.add_parser("links", help="list same-host article links on a listing page (policy and robots gated)")
    discover.add_argument("url")
    discover.add_argument("--match", default=".")
    register = commands.add_parser("register", help="register visible text captured in a browser (or pasted by the user)")
    register.add_argument("file")
    register.add_argument("--url", required=True)
    register.add_argument("--observed", required=True, help="timezone-aware ISO time the page was read")
    register.add_argument("--route", choices=["browser", "manual"], default="browser")
    checker = commands.add_parser("checker", help="print the in-browser verification call for one browser-route page of a pack")
    checker.add_argument("pack")
    checker.add_argument("--page", required=True)
    commands.add_parser("purge-text", help="delete transient captured page text (metadata and hashes stay in the store)")
    names = commands.add_parser("runners", help="official runner names for pack authoring")
    names.add_argument("--meeting", required=True)
    names.add_argument("--race", type=int)
    weather = commands.add_parser("weather", help="store BOM précis forecasts for configured meetings")
    weather.add_argument("--meeting", action="append")
    check = commands.add_parser("check", help="validate evidence packs against the store without writing")
    check.add_argument("packs", nargs="+")
    imports = commands.add_parser("import", help="verify and import evidence packs")
    imports.add_argument("packs", nargs="+")
    report = commands.add_parser("digest", help="write the research digest for each meeting")
    report.add_argument("--meeting")
    report.add_argument("--cutoff")
    report.add_argument("--output", default="reports")
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    cache = Path(args.data) / "private" / "pages"
    if args.command == "sources":
        from .access import POLICY, SUPPLEMENTARY
        for name, p in POLICY.items():
            print(f"{name}: route={p['route']}; hosts={', '.join(p['hosts'])}\n  {p['why']}")
        print("Supplementary (attributed, not a named source): " + ", ".join(f"{v} ({k})" for k, v in SUPPLEMENTARY.items()))
        return
    if args.command == "fetch":
        from .access import fetch as capture
        failures = 0
        for u in args.urls:
            try:
                print(json.dumps(capture(u, cache), indent=2))
            except Invalid as e:
                failures += 1
                print(f"Refused/failed {u}: {e}", file=sys.stderr)
        if failures:
            raise Invalid(f"{failures} page(s) not captured")
        return
    if args.command == "links":
        from .access import links
        print("\n".join(links(args.url, args.match)))
        return
    if args.command == "register":
        from .access import register_text
        print(json.dumps(register_text(args.file, args.url, args.observed, args.route, cache), indent=2))
        return
    if args.command == "checker":
        from .access import checker_call
        from .evidence import latest_field, ref_name
        pack = json.loads(Path(args.pack).read_text(encoding="utf-8-sig"))
        claims = [{"excerpt": c["excerpt"], "runners": [ref_name(r) for r in c["runners"]]} for c in pack["claims"] if c["page"] == args.page]
        names = []
        labelled = [x["evidence_id"] for x in pack.get("labels", []) if x.get("page") == args.page]
        if labelled:  # labels confirm existing records by official runner name, so resolve those names now
            store = Store(args.data)
            try:
                for d in (d for d in store.all(pack["meeting_id"]) if d["id"] in labelled and d["payload"]["runner_ids"]):
                    runners = latest_field(store, pack["meeting_id"], d["race_no"], d["observed_at"])["payload"]["runners"]
                    names += [r["name"] for r in runners if r["id"] in d["payload"]["runner_ids"]]
            finally:
                store.close()
        if not claims and not names:
            raise Invalid(f"No claims or labels for page {args.page}")
        print(checker_call(claims, names))
        return
    if args.command == "purge-text":
        from .access import purge_text
        print(f"Removed {purge_text(cache)} cached page text file(s)")
        return
    store = Store(args.data)
    try:
        if args.command == "runners":
            fields = [d for d in store.all(args.meeting) if d["kind"] == "field" and (args.race is None or d["race_no"] == args.race)]
            latest = {}
            for d in fields:
                latest[d["race_no"]] = d
            for n, d in sorted(latest.items()):
                p = d["payload"]
                print(f"R{n} {p['race_name']} — {p['start_at']} (field {d['id'][:12]}, observed {d['observed_at']})")
                for r in p["runners"]:
                    print(f"  {r['number']:>3} {r['name']} [{r['status']}] b{r.get('barrier', '?')} {r.get('jockey', '')} / {r.get('trainer', '')}")
        elif args.command == "weather":
            from .weather import refresh
            for line in refresh(store, config, args.meeting, args.data):
                print(line)
        elif args.command in {"check", "import"}:
            from .evidence import Notes, build, import_pack
            notes = Notes(args.data)
            try:
                for path in args.packs:
                    if args.command == "check":
                        evidence, labels, coverage, extra = build(json.loads(Path(path).read_text(encoding="utf-8-sig")), store, config, cache)
                        print(f"{path}: OK — {len(evidence)} claims ({sum(d['payload']['reviewed'] for d in evidence)} verified), {len(coverage)} coverage, {len(extra)} notes")
                    else:
                        print(f"{path}: " + json.dumps(import_pack(path, store, notes, config, cache)))
            finally:
                notes.close()
        elif args.command == "digest":
            from .digest import build as write
            from .evidence import Notes
            notes = Notes(args.data)
            try:
                for m in config["meetings"]:
                    if not args.meeting or args.meeting == m["id"]:
                        print(write(store, notes, config, m["id"], args.cutoff or now(), args.output) / "digest.html")
            finally:
                notes.close()
    finally:
        store.close()


if __name__ == "__main__":
    try:
        main()
    except (Invalid, ValueError, OSError, KeyError) as exc:
        print("Error: " + str(exc), file=sys.stderr)
        sys.exit(1)
