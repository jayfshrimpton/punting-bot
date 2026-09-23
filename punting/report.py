"""Cutoff-aware readable reports. Unknown values remain unknown."""
import html
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import quote
from .core import Invalid, break_even, digest, expected_return, field_signature, local, now, stamp


def clean(value):
    return str(value if value is not None and value != "" else "Unknown").replace("|", "/").replace("\n", " ").replace("[", "(").replace("]", ")").replace("*", "")


def cite(d):
    return f"[{clean(d['publisher'])}]({quote(d['source_url'],safe=':/?=&%+#')}) · observed {local(d['observed_at'])} · published {local(d['published_at']) if d['published_at'] else 'unknown'} · snapshot {d['id'][:12]}"


def age(d, cutoff):
    return (stamp(cutoff)-stamp(d["observed_at"])).total_seconds()/60


def assess(field, docs, cutoff, config):
    race = [d for d in docs if d.get("race_no")==field["race_no"]]
    models = [d for d in race if d["kind"]=="model"]
    model=models[-1] if models else None
    allfields={d["id"]:d for d in race if d["kind"]=="field"}
    issues=[]
    if not field["payload"]["official"]:issues.append("Field is not verified official")
    if age(field,cutoff)>config["field_max_age_minutes"]:issues.append("Official field/scratchings check is stale")
    if stamp(cutoff)>=stamp(field["payload"]["start_at"]):issues.append("Race start reached: pre-race candidates disabled")
    probs={}
    total=None
    if model:
        if model["payload"].get("includes_emergencies"):
            issues.append("Full declared field assumed: emergencies are rated but may not start; recalculate after scratchings")
        issues.extend(model["payload"].get("limitations", []))
        if model["payload"].get("experimental"):
            issues.append("Experimental model: numerical research only; candidates disabled")
        total=sum(1/r["rated_price"] for r in model["payload"]["rows"])
        probs={r["runner_id"]:1/r["rated_price"]/total for r in model["payload"]["rows"]}
        based=allfields[model["payload"]["field_id"]]
        if field_signature(based)!=field_signature(field):issues.append("Model based on older field: scratchings/runner changes require rerun")
        if age(model,cutoff)>config["model_max_age_hours"]*60:issues.append("Model observation is stale")
    else:
        issues.append("Model unavailable: our historical baseline is not approved for current predictions")
    latest={}
    for q in (d for d in race if d["kind"]=="quotes"):
        latest[q["payload"]["provider"],q["payload"]["market"],q["payload"]["terms"]]=q
    rows=[]
    for runner in field["payload"]["runners"]:
        rid=runner["id"];p=probs.get(rid);offers=[]
        for q in latest.values():
            row=next((r for r in q["payload"]["rows"] if r["runner_id"]==rid),None)
            if not row:continue
            qp=q["payload"];reasons=[]
            if age(q,cutoff)>config["quote_max_age_minutes"]:reasons.append("stale quote")
            if field_signature(allfields[qp["field_id"]])!=field_signature(field):reasons.append("older field")
            commission=0 if qp["market"]=="fixed_win" else qp["commission"]
            if commission is None:reasons.append("commission unknown")
            if row["size"] is None or row["size"]<=0:reasons.append("liquidity/limit unknown or zero")
            er=expected_return(p,row["odds"],commission) if p is not None and commission is not None and not reasons and not issues else None
            offers.append({"snapshot":q,"row":row,"issues":reasons,"er":er,"break_even":break_even(p,commission) if p and commission is not None else None})
        valid=[x for x in offers if x["er"] is not None]
        best=max(valid,key=lambda x:x["er"]) if valid else None
        if runner["status"]!="active":state=runner["status"]
        elif best and best["er"]>config["minimum_expected_return"]:state="candidate for human review"
        elif best:state="pass at checked prices"
        else:state="watch / recheck"
        rows.append({"runner":runner,"p":p,"offers":offers,"best":best,"state":state})
    return {"model":model,"sum":total,"issues":issues,"rows":rows}


def build(store, config, meeting_id, cutoff, output="reports"):
    meeting=next(m for m in config["meetings"] if m["id"]==meeting_id)
    if stamp(cutoff)>stamp(now()):raise Invalid("Cannot create a report with a future cutoff")
    docs=store.all(meeting_id,cutoff)
    fields={}
    for d in docs:
        if d["kind"]=="field":fields[d["race_no"]]=d
    sources={}
    for d in docs:
        if d["kind"]=="coverage" and "race_no" not in d:sources[d["payload"]["source"]]=d
    assessments={n:assess(f,docs,cutoff,config) for n,f in fields.items()}
    expected=max((f["payload"]["card_races"] for f in fields.values()),default=0)
    complete=bool(expected and set(fields)==set(range(1,expected+1)))
    partial=not complete or any(not a["model"] or a["model"]["payload"].get("experimental") for a in assessments.values())
    lines=[f"# {meeting['venue']} — {meeting['date']}","",f"Research cutoff: {local(cutoff)}. Generated {local(now())}.","", "PARTIAL DELIVERY — current model-plus-research objective remains incomplete." if partial else "Provisional research — verify all gaps before deciding.","",f"Official card coverage: {len(fields)}/{expected or 'unknown'} races; {sum(len(f['payload']['runners']) for f in fields.values())} runner records including scratchings/emergencies.","", "## Meeting shortlist",""]
    candidates=[(n,r) for n,a in assessments.items() for r in a["rows"] if r["state"]=="candidate for human review"]
    if candidates:
        for n,r in candidates:lines.append(f"- R{n} {clean(r['runner']['name'])}: model-implied return {r['best']['er']:.1%}; review source evidence and price terms. Not a proven edge.")
    else:lines.append("No actionable model shortlist. Watch/recheck: obtain current validated model inputs, fresh quotes and current scratchings. Missing commentary is not a negative signal.")
    lines += ["", "## Conditions and sourced meeting context", ""]
    for f in list(fields.values())[:1]:lines.append(f"Official observation: going {clean(f['payload']['going'])}; rail {clean(f['payload']['rail'])}. {cite(f)}")
    meeting_evidence=[d for d in docs if d["kind"]=="evidence" and "race_no" not in d]
    lines+=render_evidence(meeting_evidence)
    lines += ["", "## Source coverage", "", "Statuses apply only to the pages/queries recorded below; a failed fetch does not mean nothing was published. Race-specific gaps are listed with each race.","", "| Source | Status | Detail and checked pages |", "|---|---|---|"]
    for source in config["required_sources"]:
        d=sources.get(source)
        if not d:lines.append(f"| {source} | Not checked | No attempt recorded |")
        else:
            p=d["payload"];links=" ".join(f"[page {i+1}]({quote(u,safe=':/?=&%+#')})" for i,u in enumerate(p["checked_urls"]))
            lines.append(f"| {source} | {p['status']} | {clean(p['detail'])} {links}; {local(d['observed_at'])} |")
    for n,field in sorted(fields.items()):
        a=assessments[n];p=field["payload"]
        lines += ["",f"## Race {n} — {clean(p['race_name'])}","",f"Scheduled {local(p['start_at'])}. {cite(field)}", "", "Status: "+"; ".join(a["issues"]) if a["issues"] else "Inputs pass freshness and field consistency gates.",""]
        if a["model"]:
            model=a["model"]
            lines += [f"Model: {clean(model['payload']['model'])}; version {clean(model['payload']['version'])}. {cite(model)}", "", f"Raw inverse-price sum: {a['sum']:.8f}. Whole-field normalization multiplier: {1/a['sum']:.8f}. Raw rated prices retained. Older-field probabilities, if flagged above, are not adjusted for scratchings.",""]
        else:lines+= ["Model unavailable. Handicap ratings and tipster ranks are not winning probabilities.",""]
        lines += ["| No. | Runner | Status | Barrier | Jockey | Model win % | Fair price | Observed quotes | Decision state |", "|---|---|---|---|---|---:|---:|---|---|"]
        for r in a["rows"]:
            horse=r["runner"];prob=r["p"]
            prices=[]
            for offer in r["offers"]:
                q=offer["snapshot"]
                prices.append(f"{clean(q['payload']['provider'])} {offer['row']['odds']:.2f} ({local(q['observed_at'])}; {', '.join(offer['issues']) or 'fresh'}; return {offer['er']:.1%})" if offer["er"] is not None else f"{clean(q['payload']['provider'])} {offer['row']['odds']:.2f} ({local(q['observed_at'])}; {', '.join(offer['issues']) or 'calculation blocked'})")
            lines.append("| "+" | ".join([clean(horse["number"]),clean(horse["name"]),horse["status"],clean(horse.get("barrier")),clean(horse.get("jockey")),f"{prob*100:.2f}" if prob else "Missing",f"{1/prob:.2f}" if prob else "Missing","; ".join(prices) or "Missing",r["state"]])+" |")
        if a["model"]:
            leaders=sorted([r for r in a["rows"] if r["p"]],key=lambda r:r["p"],reverse=True)[:3]
            lines += ["", "Model leaders: "+", ".join(f"{clean(r['runner']['name'])} ({r['p']:.1%})" for r in leaders)+". This is a model ranking, not a causal form explanation."]
        lines += ["", "### Research and disagreements", ""]
        lines+=render_evidence([d for d in docs if d["kind"]=="evidence" and d.get("race_no")==n],{r["id"]:r["name"] for r in p["runners"]})
        lines += ["", "Outstanding checks: current prices and limits; late scratchings; model inputs; pace/map, class/distance suitability and trainer/jockey context where no reviewed evidence is shown."]
        for source in config["required_sources"]:
            scoped=[d for d in docs if d["kind"]=="coverage" and d.get("race_no")==n and d["payload"]["source"]==source]
            if scoped:lines.append(f"- {source}: {scoped[-1]['payload']['status']} — {clean(scoped[-1]['payload']['detail'])}")
        lines += ["", "### Human notes", ""]
        decisions=[d for d in docs if d["kind"]=="decision" and d.get("race_no")==n]
        for d in decisions:
            q=d["payload"];horse=next((r["name"] for r in p["runners"] if r["id"]==q["runner_id"]),"Race")
            lines.append(f"- {local(d['observed_at'])}: {q['action']} — {clean(horse)}; price {clean(q['price'])}; {clean(q['reason'])}")
        if not decisions:lines.append("No user decision recorded.")
    lines += ["", "## Calculation and refresh policy", "",f"Quote freshness: {config['quote_max_age_minutes']} minutes; official field check: {config['field_max_age_minutes']} minutes; model observation: {config['model_max_age_hours']} hours. Screening threshold: {config['minimum_expected_return']:.1%}. {config['margin_rationale']}","", "Fixed WIN expected return: p × odds − 1. Exchange single-back expected return: p × (1 + (odds − 1) × (1 − commission)) − 1. Break-even fixed price: 1/p; exchange: 1 + (1/p − 1)/(1 − commission). These do not settle dead heats or multiple positions. Comparison is best observed among checked providers, under the stated terms; no universally best-price claim."]
    for q in (d for d in docs if d["kind"]=="quotes"):
        lines.append(f"- R{q['race_no']} {clean(q['payload']['provider'])}: {q['payload']['market']}; commission {clean(q['payload']['commission'])}; terms {clean(q['payload']['terms'])}; {cite(q)}")
    generated=now()
    code_version=digest({p.name:p.read_text(encoding="utf-8") for p in sorted(Path(__file__).parent.glob("*.py"))})
    manifest={"meeting_id":meeting_id,"cutoff":cutoff,"generated_at":generated,"snapshot_ids":[d["id"] for d in docs],"config":config,"config_sha256":digest(config),"code_sha256":code_version,"review_status":"Provisional; only individually marked evidence reviewed","fields":{str(n):f["id"] for n,f in fields.items()}}
    out=Path(output)/meeting_id;out.mkdir(parents=True,exist_ok=True)
    old=sorted(out.glob("*/manifest.json"),key=lambda p:p.stat().st_mtime)
    lines += ["", "## Changes since prior report", ""]
    if old:
        previous=json.loads(old[-1].read_text(encoding="utf-8"))
        added=set(manifest["snapshot_ids"])-set(previous["snapshot_ids"])
        changed=[n for n,sid in manifest["fields"].items() if previous.get("fields",{}).get(n)!=sid]
        lines.append(f"{len(added)} newly included snapshots; field observations changed for races {', '.join(changed) or 'none'}. Prior report retained. All freshness states recalculated at this cutoff.")
    else:lines.append("First report version. No prior comparison.")
    lines += ["",f"Code SHA256: {code_version}. Config SHA256: {manifest['config_sha256']}. Review status: {manifest['review_status']}."]
    markdown="\n".join(lines)+"\n"
    manifest["report_sha256"]=hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    version=out/(stamp(generated).strftime("%Y%m%dT%H%M%S%fZ")+"-"+digest(manifest)[:8]);version.mkdir()
    (version/"brief.md").write_text(markdown,encoding="utf-8")
    (version/"brief.html").write_text(to_html(markdown),encoding="utf-8")
    (version/"manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    return version


def render_evidence(records, names=None):
    lines=[];seen=set();names=names or {}
    for d in records:
        p=d["payload"]
        # Same underlying statement remains one source even if syndicated.
        key=(p["original_url"],p["claim_id"])
        if key in seen:continue
        seen.add(key)
        who=", ".join(clean(names.get(r,r)) for r in p["runner_ids"]) or "Meeting"
        lines.append(f"- {who} — {p['type']} ({'reviewed' if p['reviewed'] else 'UNREVIEWED'}): {clean(p['summary'])} Author: {clean(p['author'])}. Conditions: {clean('; '.join(p['conditions']))}. {cite(d)}. [Original]({quote(p['original_url'],safe=':/?=&%+#')})")
    return lines or ["No reviewed race-specific evidence imported. Supporting claims, concerns and disagreements remain unassessed."]


def to_html(markdown):
    def inline(s):
        escaped=html.escape(s)
        return re.sub(r'\[([^\]]+)\]\((https?://[^\s)]+)\)',r'<a href="\2" rel="noreferrer">\1</a>',escaped)
    blocks=[];table=False;head=False
    for line in markdown.splitlines():
        if line.startswith("|"):
            if re.match(r'^\|[\s:|\-]+\|$',line):continue
            if not table:blocks.append('<div class="table"><table>');table=True;head=True
            tag="th" if head else "td";head=False
            blocks.append("<tr>"+"".join(f"<{tag}>"+inline(c.strip())+f"</{tag}>" for c in line.strip("|").split("|"))+"</tr>")
            continue
        if table:blocks.append("</table></div>");table=False
        if not line:continue
        if line.startswith("#"):
            level=len(line)-len(line.lstrip("#"));blocks.append(f"<h{level}>"+inline(line[level:].strip())+f"</h{level}>")
        else:blocks.append("<p>"+inline(line)+"</p>")
    if table:blocks.append("</table></div>")
    return '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PuntingPowerAI research</title><style>body{font:16px/1.6 system-ui,sans-serif;background:#f5f4ef;color:#172b35;margin:0}main{max-width:1200px;margin:auto;padding:32px 24px}h1{font-size:36px;line-height:1.2}h2{margin-top:48px;border-top:2px solid #bfd0cc;padding-top:24px}h3{margin-top:28px}a{color:#006357;overflow-wrap:anywhere}p{max-width:100ch;overflow-wrap:anywhere}.table{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px;background:#fff}td,th{padding:10px;border:1px solid #d3ded9;vertical-align:top;text-align:left}th{background:#173e38;color:white}tr:nth-child(even){background:#eef3ef}@media print{body{background:white}main{padding:0}h2{break-before:page}.table{overflow:visible}table{font-size:10px}}</style><main>'+"\n".join(blocks)+"</main></html>"
