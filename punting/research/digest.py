"""Research digest: what the sources say about each race and runner, grouped for a human decision.

Complements report.build (model numbers, prices, decision states). Counts here are research attention,
not probabilities: a runner nobody wrote about is not a weaker runner.
"""
import html
import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path
from urllib.parse import quote
from ..core import digest, local, now, stamp
from .access import POLICY

SIGN = {"positive": "For", "negative": "Against", "mixed": "Mixed", "neutral": "Context", "unclassified": "Unclassified"}
ORDER = {"positive": 0, "mixed": 1, "neutral": 2, "unclassified": 3, "negative": 4}
UNLABELLED = {"stance": "unclassified", "topic": "other", "tip": None}


def cell(value):
    """Plain text safe for a Markdown table cell or link label."""
    return " ".join(str(value if value not in (None, "") else "Unknown").replace("|", "/").replace("[", "(").replace("]", ")").replace("*", "").split())


def link(label, address):
    return f"[{cell(label)}]({quote(address, safe=':/?=&%+#~')})"


GROUP = 3  # a claim naming this many runners is race context, not a note on each horse


def speaker(author):
    """'Michael Kent Jnr, reported by Trent Masenhelder' and 'Michael Kent Jnr' are the same person."""
    return re.split(r",|\(| reported by | via ", author, maxsplit=1)[0].strip().casefold()


def voice(e):
    """Independent origin of a claim. A quoted person is one voice whichever outlet carries the quote;
    otherwise original publisher plus author, so syndicated copies share a voice."""
    if e["payload"]["type"] == "attributed statement" and e["payload"]["author"]:
        return ("Quoted", speaker(e["payload"]["author"]))
    return (e["label"].get("original_publisher") or e["publisher"], e["payload"]["author"] or "unattributed")


def when(e):
    published = local(e["published_at"]) if e["published_at"] else (e["label"].get("published_note") or "publication time unknown")
    return f"published {published}; observed {local(e['observed_at'])}"


def line(e, names=None):
    p, label = e["payload"], e["label"]
    who = e["publisher"] + (f" · {p['author']}" if p["author"] else "")
    tip = f" ({label['tip']})" if label.get("tip") else ""
    cond = f" Conditions: {cell('; '.join(p['conditions']))}." if p["conditions"] else ""
    method = label.get("verification", {}).get("method")
    if p["reviewed"] and p["excerpt"]:
        check = "excerpt verified in browser" if method == "browser receipt" else "excerpt verified in captured text"
    elif p["reviewed"]:
        check = "marked reviewed but no excerpt to verify" + ("; horse confirmed on source page" if method == "source page re-read" else "")
    else:
        check = "UNVERIFIED manual import"
    runners = f"{', '.join(cell(names[r]) for r in p['runner_ids'])}: " if names and len(p["runner_ids"]) > 1 else ""
    return f"- **{SIGN[label['stance']]}{tip}** — {runners}{cell(p['summary'])}{cond} {link(who, e['source_url'])} — {p['type']}; {when(e)}; {check}."


def collect(store, notes, meeting_id, cutoff):
    docs = store.all(meeting_id, cutoff)
    recorded = notes.all(meeting_id, cutoff)
    labels = {}
    for n in sorted((n for n in recorded if n["kind"] == "classification"), key=lambda n: stamp(n["recorded_at"])):
        labels[n["evidence_id"]] = n  # the most recently recorded label wins
    chosen = {}
    for d in docs:
        if d["kind"] != "evidence" or d["payload"]["claim_id"].startswith("bom:"):
            continue
        key = (d["payload"]["original_url"], d["payload"]["claim_id"])  # syndicated copies share this identity
        current = dict(d, label=labels.get(d["id"], UNLABELLED))
        rank = (d["id"] in labels, d["payload"]["reviewed"] and bool(d["payload"]["excerpt"]))
        if key not in chosen or rank > chosen[key][0]:
            chosen[key] = (rank, current)
    evidence = sorted((c for _, c in chosen.values()), key=lambda e: (stamp(e["observed_at"]), e["id"]))
    fields, coverage = {}, defaultdict(dict)
    for d in docs:
        if d["kind"] == "field":
            fields[d["race_no"]] = d
        elif d["kind"] == "coverage":
            coverage[d.get("race_no")][d["payload"]["source"]] = d
    forecasts = {}
    for d in docs:
        if d["kind"] == "evidence" and d["payload"]["type"] == "forecast" and d["payload"]["claim_id"].startswith("bom:"):
            forecasts[d["payload"]["claim_id"].split(":", 4)[2]] = d  # latest issue per location
    researcher = [n for n in recorded if n["kind"] == "note"]
    return docs, fields, evidence, coverage, list(forecasts.values()), researcher


def tally(evidence, runner_id):
    out = {"for": set(), "against": set(), "tips": [], "conditions": []}
    for e in evidence:
        if runner_id not in e["payload"]["runner_ids"]:
            continue
        v = voice(e)
        if e["label"]["stance"] == "positive":
            out["for"].add(v)
        elif e["label"]["stance"] == "negative":
            out["against"].add(v)
        if e["label"].get("tip"):
            out["tips"].append(f"{e['label']['tip']} — {v[0]}" + ("" if v[1] == "unattributed" else f" ({v[1]})"))
        out["conditions"] += e["payload"]["conditions"]
    return out


def number(runner):
    digits = re.match(r"\d+", runner["number"])
    return int(digits[0]) if digits else 999


def render(store, notes, config, meeting_id, cutoff):
    meeting = next(m for m in config["meetings"] if m["id"] == meeting_id)
    docs, fields, evidence, coverage, forecasts, researcher = collect(store, notes, meeting_id, cutoff)
    lines = [f"# Research digest — {meeting['venue']}, {date.fromisoformat(meeting['date']).strftime('%A %d %B %Y')}", "",
             f"Research cutoff {local(cutoff)}; generated {local(now())}. Sources, tips and conditions only: no probabilities, prices or bets. "
             "Model numbers and prices belong to the main brief (`python -m punting report`).", "",
             "**For / Against** count independent voices (original publisher plus author) after syndicated copies are collapsed. "
             "They show where commentary points, not a horse's chance, and silence is not a negative signal. "
             "Every claim links to its source with publication and observation times.", "", "## Conditions", ""]
    if fields:
        f = fields[max(fields)]
        lines.append(f"- Official at acceptances: going **{cell(f['payload']['going'])}**, rail **{cell(f['payload']['rail'])}** "
                     f"({link(f['publisher'], f['source_url'])}; observed {local(f['observed_at'])}; published "
                     f"{local(f['published_at']) if f['published_at'] else 'unknown'}). Recheck the official track report on race morning.")
    lines += [line(e) for e in evidence if e.get("race_no") is None]
    for d in forecasts:
        lines.append(f"- Forecast — {cell(d['payload']['summary'])} {link('BOM', d['source_url'])}; retrieved {local(d['observed_at'])}.")
    if not fields and not forecasts:
        lines.append("- No official conditions or forecasts recorded yet.")
    for n in researcher:
        if n["race_no"] is None:
            lines.append(f"- **Researcher inference** ({cell(n['classifier'])}, {local(n['observed_at'])}): {cell(n['text'])} Basis: "
                         + ", ".join(link(b["publisher"], b["url"]) for b in n["basis"]) + ".")
    lines += ["", "## Where the commentary points", "",
              "Runners with at least one independent supporting voice, most-supported first. Horses to inspect, not selections.", "",
              "| Race | No. | Runner | For | Against | Selections recorded | Conditions attached |", "|---|---|---|---:|---:|---|---|"]
    board = []
    for n, f in fields.items():
        for r in f["payload"]["runners"]:
            t = tally(evidence, r["id"])
            if t["for"]:
                board.append(((-len(t["for"]), len(t["against"]), n, number(r)), n, r, t))
    for _, n, r, t in sorted(board, key=lambda x: x[0]):
        status = "" if r["status"] == "active" else f" ({r['status']})"
        lines.append(f"| R{n} | {cell(r['number'])} | {cell(r['name'])}{status} | {len(t['for'])} | {len(t['against'])} | "
                     f"{cell('; '.join(t['tips'])) if t['tips'] else '—'} | {cell('; '.join(dict.fromkeys(t['conditions']))) if t['conditions'] else '—'} |")
    if not board:
        lines.append("| — | — | No supporting commentary imported yet | 0 | 0 | — | — |")
    lines += ["", "## Source coverage", "", "Latest recorded check per source. A failed or blocked check is a gap, not an absence of commentary.", "",
              "| Source | Meeting-level status | Detail | Race-level checks |", "|---|---|---|---|"]
    for source in config["required_sources"]:
        d = coverage[None].get(source)
        races = sorted(n for n in coverage if n is not None and source in coverage[n])
        route = POLICY.get(source, {}).get("route")
        detail = f"{cell(d['payload']['detail'])} ({local(d['observed_at'])})" if d else "No check recorded" + (f"; access route: {route}" if route else "")
        lines.append(f"| {source} | {d['payload']['status'] if d else 'not checked'} | {detail} | {', '.join(f'R{n}' for n in races) or '—'} |")
    for n, f in sorted(fields.items()):
        p = f["payload"]
        names = {r["id"]: r["name"] for r in p["runners"]}
        race_evidence = [e for e in evidence if e.get("race_no") == n]
        counts = {s: sum(r["status"] == s for r in p["runners"]) for s in ("active", "emergency", "scratched")}
        lines += ["", f"## Race {n} — {cell(p['race_name'])}", "",
                  f"Starts {local(p['start_at'])}. {counts['active']} active, {counts['emergency']} emergencies, {counts['scratched']} scratched "
                  f"(official field observed {local(f['observed_at'])}).", "",
                  "| No. | Runner | Bar. | Jockey | Trainer | Wt | Form | For | Against | Selections |", "|---|---|---|---|---|---|---|---:|---:|---|"]
        for r in p["runners"]:
            t = tally(race_evidence, r["id"])
            status = "" if r["status"] == "active" else f" ({r['status']})"
            lines.append(f"| {cell(r['number'])} | {cell(r['name'])}{status} | {cell(r.get('barrier'))} | {cell(r.get('jockey'))} | {cell(r.get('trainer'))} | "
                         f"{cell(r.get('weight'))} | {cell(r.get('form'))} | {len(t['for']) or ''} | {len(t['against']) or ''} | {cell('; '.join(t['tips'])) if t['tips'] else ''} |")
        general = [e for e in race_evidence if not e["payload"]["runner_ids"] or len(e["payload"]["runner_ids"]) >= GROUP]
        if general:
            lines += ["", "### Race shape and context", ""] + [line(e, names) for e in sorted(general, key=lambda e: ORDER[e["label"]["stance"]])]
        specific = [e for e in race_evidence if 0 < len(e["payload"]["runner_ids"]) < GROUP]
        mentioned = [r for r in p["runners"] if any(r["id"] in e["payload"]["runner_ids"] for e in specific)]
        if mentioned:
            lines += ["", "### What the sources say", ""]
            for r in mentioned:
                mine = [e for e in specific if r["id"] in e["payload"]["runner_ids"]]
                lines += [f"#### {cell(r['number'])}. {cell(r['name'])}", ""] + [line(e, names) for e in sorted(mine, key=lambda e: ORDER[e["label"]["stance"]])] + [""]
        split, mixed = [], []
        for r in p["runners"]:
            t = tally(race_evidence, r["id"])
            if t["for"] and t["against"]:
                (mixed if t["for"] == t["against"] else split).append(f"{cell(r['name'])} ({len(t['for'])} for, {len(t['against'])} against)")
        if split:
            lines += ["", "Sources disagree: " + "; ".join(split) + ". Read both sides; do not net them off."]
        if mixed:
            lines += ["", "Mixed signals from the same source: " + "; ".join(mixed) + "."]
        mine = [x for x in researcher if x["race_no"] == n]
        if mine:
            lines += ["", "### Researcher inference", ""]
            lines += [f"- {cell(x['text'])} ({cell(x['classifier'])}, {local(x['observed_at'])}; basis: "
                      + ", ".join(link(b["publisher"], b["url"]) for b in x["basis"]) + ")" for x in mine]
        lines += ["", "### Coverage for this race", ""]
        scoped = coverage.get(n, {})
        lines += [f"- {s}: {d['payload']['status']} — {cell(d['payload']['detail'])} ({local(d['observed_at'])})" for s, d in scoped.items()] or ["- No race-specific source checks recorded yet."]
        if not race_evidence:
            lines.append("- No commentary imported for this race. That is a coverage gap, not a signal about the runners.")
    return docs, evidence, "\n".join(lines) + "\n"


def inline(s):
    s = html.escape(s, quote=False)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return re.sub(r"\[([^\]]+)\]\((https?://[^\s)\"<>]+)\)", r'<a href="\2" rel="noreferrer">\1</a>', s)


def page(markdown, title):
    out, table, head, bullets = [], False, False, False
    for raw in markdown.splitlines():
        if raw.startswith("|"):
            if re.match(r"^\|[\s:|\-]+\|$", raw):
                continue
            if bullets:
                out.append("</ul>"); bullets = False
            if not table:
                out.append('<div class="table"><table>'); table, head = True, True
            tag = "th" if head else "td"
            head = False
            out.append("<tr>" + "".join(f"<{tag}>{inline(c.strip())}</{tag}>" for c in raw.strip().strip("|").split("|")) + "</tr>")
            continue
        if table:
            out.append("</table></div>"); table = False
        if raw.startswith("- "):
            if not bullets:
                out.append("<ul>"); bullets = True
            out.append(f"<li>{inline(raw[2:])}</li>")
            continue
        if bullets:
            out.append("</ul>"); bullets = False
        if not raw.strip():
            continue
        if raw.startswith("#"):
            level = len(raw) - len(raw.lstrip("#"))
            out.append(f"<h{level}>{inline(raw[level:].strip())}</h{level}>")
        else:
            out.append(f"<p>{inline(raw)}</p>")
    out.append("</table></div>" if table else "</ul>" if bullets else "")
    style = ("body{font:16px/1.55 system-ui,sans-serif;background:#f6f5f0;color:#18282f;margin:0}main{max-width:1180px;margin:auto;padding:28px 16px}"
             "h1{font-size:30px;line-height:1.2}h2{margin-top:44px;border-top:2px solid #c3d2cd;padding-top:20px}h4{margin:18px 0 6px}"
             "a{color:#00645a;overflow-wrap:anywhere}p,li{max-width:110ch;overflow-wrap:anywhere}li{margin:4px 0}.table{overflow-x:auto}"
             "table{border-collapse:collapse;width:100%;font-size:14px;background:#fff}td,th{padding:8px;border:1px solid #d4dfda;vertical-align:top;text-align:left}"
             "th{background:#173e38;color:#fff}tr:nth-child(even){background:#eff4f0}code{background:#e8ece9;padding:1px 4px}"
             "@media (prefers-color-scheme:dark){body{background:#111a1d;color:#e2e8e6}a{color:#6fd3c3}table{background:#162226}"
             "td,th{border-color:#2c3c40}tr:nth-child(even){background:#1b2a2e}code{background:#22343a}h2{border-color:#2c3c40}}")
    return (f'<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{html.escape(title)}</title><style>{style}</style><main>" + "\n".join(out) + "</main></html>")


def build(store, notes, config, meeting_id, cutoff, output="reports"):
    docs, evidence, markdown = render(store, notes, config, meeting_id, cutoff)
    manifest = {"meeting_id": meeting_id, "cutoff": cutoff, "generated_at": now(), "evidence_ids": [e["id"] for e in evidence],
                "snapshot_ids": [d["id"] for d in docs], "code_sha256": digest({p.name: p.read_text(encoding="utf-8") for p in sorted(Path(__file__).parent.glob("*.py"))})}
    out = Path(output) / meeting_id / "research"
    out.mkdir(parents=True, exist_ok=True)
    old = sorted(out.glob("*/manifest.json"), key=lambda p: p.stat().st_mtime)
    change = "First research digest for this meeting."
    if old:
        previous = json.loads(old[-1].read_text(encoding="utf-8"))
        added = [e for e in evidence if e["id"] not in set(previous["evidence_ids"])]
        races = sorted({e["race_no"] for e in added if e.get("race_no")})
        change = (f"{len(added)} new claim(s) since the digest generated {local(previous['generated_at'])}; "
                  f"races affected: {', '.join(f'R{r}' for r in races) or 'meeting-level only'}.")
    markdown += f"\n## Changes since the previous digest\n\n{change}\n"
    manifest["digest_sha256"] = digest(markdown)
    version = out / (stamp(manifest["generated_at"]).strftime("%Y%m%dT%H%M%S%fZ") + "-" + digest(manifest)[:8])
    version.mkdir()
    (version / "digest.md").write_text(markdown, encoding="utf-8")
    (version / "digest.html").write_text(page(markdown, f"Research digest {meeting_id}"), encoding="utf-8")
    (version / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return version
