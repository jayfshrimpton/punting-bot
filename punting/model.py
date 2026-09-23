"""PuntingPowerAI History v1. Prior-day features; race-level conditional logit."""
import csv
import hashlib
import io
import json
import math
import zipfile
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

from .core import Invalid, digest, namekey, now

FEATURES = ["log_prior_starts", "smoothed_win_rate", "recent_market_strength", "last_market_strength", "recent_outperformance", "log_days_since_start", "distance_change_km", "no_history"]
AU = {"NSW", "VIC", "QLD", "SA", "WA", "TAS", "NT", "ACT"}
SCHEMA = "history-v1.1"


def archive_rows(root):
    root = Path(root)
    manifest = json.loads((root / "manifest.json").read_text())
    for entry in manifest:
        path = root / entry["name"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise Invalid("Historical archive checksum mismatch: "+path.name)
        if path.suffix == ".zip":
            with zipfile.ZipFile(path) as z:
                members = [x for x in z.infolist() if x.filename.lower().endswith(".csv") and not x.is_dir()]
                if not members or sum(x.file_size for x in members)>500*1024*1024:
                    raise Invalid("Unexpected archive size/content")
                for member in members:
                    with z.open(member) as f:
                        yield from csv.DictReader(io.TextIOWrapper(f,encoding="utf-8-sig"))
        else:
            with path.open(encoding="utf-8-sig",newline="") as f:
                yield from csv.DictReader(f)


def load_races(root):
    grouped = defaultdict(list)
    exclusions = Counter()
    for r in archive_rows(root):
        if r.get("STATE_CODE") not in AU or r.get("RACING_TYPE", "").lower() != "thoroughbred":
            exclusions["non_AU_or_non_thoroughbred_rows"] += 1
            continue
        if not r.get("WIN_MARKET_ID"):
            exclusions["missing_market_rows"] += 1
            continue
        grouped[r["WIN_MARKET_ID"]].append(r)
    races = []
    for mid, rows in grouped.items():
        # Place records can duplicate win records. Compare all win-relevant fields.
        by_id = {}
        conflict = False
        for r in rows:
            sid = r.get("SELECTION_ID")
            selected = {k:r.get(k) for k in ("LOCAL_MEETING_DATE","TRACK","STATE_CODE","RACE_NO","SELECTION_ID","SELECTION_NAME","WIN_RESULT","WIN_BSP","DISTANCE")}
            if sid in by_id and selected != by_id[sid]:
                conflict = True
            by_id[sid] = selected
        rows = list(by_id.values())
        identity = {(r["LOCAL_MEETING_DATE"],r["TRACK"],r["STATE_CODE"],r["RACE_NO"],r["DISTANCE"]) for r in rows}
        if conflict or len(identity)!=1 or not all(r["SELECTION_ID"] and r["SELECTION_NAME"] for r in rows):
            exclusions["conflicting_market"] += 1; continue
        if len({namekey(r["SELECTION_NAME"]) for r in rows}) != len(rows):
            exclusions["ambiguous_names"] += 1; continue
        # Removed runners are not starters. Unsupported settlements invalidate the race.
        rows = [r for r in rows if r["WIN_RESULT"] not in {"REMOVED", "REMOVED_VACANT"}]
        if len(rows)<2 or any(r["WIN_RESULT"] not in {"WINNER","LOSER"} for r in rows) or sum(r["WIN_RESULT"]=="WINNER" for r in rows)!=1:
            exclusions["unsupported_outcome_or_dead_heat"] += 1; continue
        try:
            for r in rows:
                r["bsp"] = float(r["WIN_BSP"])
                r["distance"] = float(r["DISTANCE"])
                if not math.isfinite(r["bsp"]) or r["bsp"]<=1 or not 400<=r["distance"]<=8000:
                    raise ValueError()
            day = date.fromisoformat(rows[0]["LOCAL_MEETING_DATE"])
            if not date(2024,1,1)<=day<=date(2026,8,31):
                raise ValueError()
        except (ValueError,TypeError):
            exclusions["invalid_price_distance_or_date"] += 1; continue
        rows.sort(key=lambda r:r["SELECTION_ID"])
        total = sum(1/r["bsp"] for r in rows)
        if not .8<=total<=1.2:
            exclusions["incomplete_or_inconsistent_BSP_field"] += 1; continue
        races.append({"id":mid,"date":day.isoformat(),"track":rows[0]["TRACK"],"rows":rows,"market_p":[1/r["bsp"]/total for r in rows]})
    return sorted(races,key=lambda r:(r["date"],r["id"])),dict(exclusions)


def features(history, day, distance):
    if not history:
        return [0,.1,-math.log(10),-math.log(10),0,math.log1p(90),0,1]
    recent = history["recent"]
    days = (date.fromisoformat(day)-date.fromisoformat(recent[-1]["date"])).days
    if days<=0:
        raise Invalid("History must precede the target calendar day")
    return [math.log1p(history["starts"]),(history["wins"]+1)/(history["starts"]+10),
            sum(-math.log(r["bsp"]) for r in recent)/len(recent),-math.log(recent[-1]["bsp"]),
            sum(r["won"]-r["market_p"] for r in recent)/len(recent),
            math.log1p(min(days,730)),min(abs(distance-recent[-1]["distance"])/1000,5),0]


def build_features(races):
    history = {}
    by_day = defaultdict(list)
    for race in races:
        by_day[race["date"]].append(race)
    out = []
    for day, daily in sorted(by_day.items()):
        daily_names=Counter(namekey(r["SELECTION_NAME"]) for race in daily for r in race["rows"])
        for race in daily:
            out.append({**race,"x":[features(history.get(namekey(r["SELECTION_NAME"])) if daily_names[namekey(r["SELECTION_NAME"])]==1 else None,day,r["distance"]) for r in race["rows"]]})
        # Outcomes cannot affect their own features or another race on the same day.
        for race in daily:
            for r,mp in zip(race["rows"],race["market_p"]):
                sid = namekey(r["SELECTION_NAME"])
                if daily_names[sid]!=1:
                    # Same exact name in multiple races today is ambiguous. Do not
                    # merge either outcome into an existing horse's history.
                    history.pop(sid,None)
                    continue
                h = history.setdefault(sid,{"starts":0,"wins":0,"names":[],"recent":[]})
                h["starts"]+=1
                won=int(r["WIN_RESULT"]=="WINNER");h["wins"]+=won
                if r["SELECTION_NAME"] not in h["names"]:
                    h["names"].append(r["SELECTION_NAME"])
                h["recent"]=(h["recent"]+[{"date":day,"bsp":r["bsp"],"distance":r["distance"],"won":won,"market_p":mp}])[-5:]
    return out,history


def packed(races):
    lengths = np.array([len(r["rows"]) for r in races],dtype=int)
    if not len(lengths):
        raise Invalid("Empty training/evaluation split")
    starts=np.r_[0,np.cumsum(lengths)[:-1]]
    groups=np.repeat(np.arange(len(races)),lengths)
    x=np.array([x for race in races for x in race["x"]],dtype=float)
    y=np.array([r["WIN_RESULT"]=="WINNER" for race in races for r in race["rows"]],dtype=float)
    return x,y,starts,groups


def probabilities(scores, starts, groups):
    exp=np.exp(scores-np.maximum.reduceat(scores,starts)[groups])
    return exp/np.add.reduceat(exp,starts)[groups]


def fit(races):
    x,y,starts,groups=packed(races)
    mean=x.mean(axis=0);scale=x.std(axis=0);scale[scale<1e-10]=1
    x=(x-mean)/scale
    def objective(w):
        p=probabilities(x@w,starts,groups)
        loss=-np.log(np.maximum(p[y==1],1e-300)).mean()+.01*np.dot(w,w)/2
        grad=x.T@(p-y)/len(starts)+.01*w
        return loss,grad
    result=minimize(objective,np.zeros(x.shape[1]),jac=True,method="L-BFGS-B",options={"maxiter":300,"ftol":1e-10})
    if not result.success:
        raise Invalid("Model optimiser did not converge: "+str(result.message))
    return {"features":FEATURES,"mean":mean.tolist(),"scale":scale.tolist(),"weights":result.x.tolist(),"iterations":int(result.nit),"penalty":.01}


def predict(model, x):
    x=np.array(x,dtype=float)
    if x.ndim!=2 or x.shape[1]!=len(FEATURES) or not np.isfinite(x).all():
        raise Invalid("Invalid feature matrix")
    scores=((x-np.array(model["mean"]))/np.array(model["scale"]))@np.array(model["weights"])
    exp=np.exp(scores-scores.max())
    return (exp/exp.sum()).tolist()


def evaluate(model,races):
    metrics={"races":len(races),"from":races[0]["date"],"through":races[-1]["date"],"runners":sum(len(r["rows"]) for r in races)}
    scores=defaultdict(list);daily=defaultdict(list);calibration=[[] for _ in range(10)];returns={str(c):[] for c in [0,.05,.08]}
    for race in races:
        pred=predict(model,race["x"])
        y=[int(r["WIN_RESULT"]=="WINNER") for r in race["rows"]]
        winner=y.index(1)
        for label,p in [("model",pred),("uniform",[1/len(y)]*len(y)),("BSP_hindsight",race["market_p"])]:
            scores[label+"_log_loss"].append(-math.log(max(p[winner],1e-300)))
            scores[label+"_race_brier"].append(sum((a-b)**2 for a,b in zip(p,y)))
            scores[label+"_top_win_rate"].append(y[max(range(len(p)),key=p.__getitem__)])
        daily[race["date"]].append(scores["model_log_loss"][-1]-scores["BSP_hindsight_log_loss"][-1])
        leader=max(range(len(pred)),key=pred.__getitem__)
        for c in returns:
            returns[c].append((race["rows"][leader]["bsp"]-1)*(1-float(c)) if y[leader] else -1)
        for p,win in zip(pred,y):
            calibration[min(int(p*10),9)].append((p,win))
    metrics.update({k:float(np.mean(v)) for k,v in scores.items()})
    rng=np.random.default_rng(20260923)
    days=list(daily.values());boot=[]
    for _ in range(500):
        selected=rng.integers(0,len(days),size=len(days))
        boot.append(np.mean([v for i in selected for v in days[i]]))
    metrics["model_minus_BSP_log_loss_daily_bootstrap_95pct"]=np.quantile(boot,[.025,.975]).tolist()
    metrics["calibration"]=[{"range":f"{i/10:.1f}–{(i+1)/10:.1f}","runners":len(b),"mean_p":float(np.mean([x[0] for x in b])) if b else None,"win_rate":float(np.mean([x[1] for x in b])) if b else None} for i,b in enumerate(calibration)]
    metrics["BSP_settlement_diagnostic"]={}
    for c,rr in returns.items():
        equity=np.r_[0,np.cumsum(rr)];drawdown=np.maximum.accumulate(equity)-equity
        by_day=defaultdict(list)
        for race,ret in zip(races,rr):by_day[race["date"]].append(ret)
        blocks=list(by_day.values());roi_boot=[]
        roi_rng=np.random.default_rng(20260923)
        for _ in range(500):
            selected=roi_rng.integers(0,len(blocks),size=len(blocks))
            roi_boot.append(sum(sum(blocks[i]) for i in selected)/sum(len(blocks[i]) for i in selected))
        metrics["BSP_settlement_diagnostic"][c]={"profit_units":float(sum(rr)),"return_per_unit":float(np.mean(rr)),"max_drawdown_units":float(drawdown.max()),"return_daily_bootstrap_95pct":np.quantile(roi_boot,[.025,.975]).tolist()}
    return metrics


def train(root="data/history",output="data/model"):
    root=Path(root);output=Path(output);output.mkdir(parents=True,exist_ok=True)
    races,excluded=load_races(root)
    print(f"Validated {len(races):,} races; building strictly lagged features",flush=True)
    races,history=build_features(races)
    training=[r for r in races if "2025-01-01"<=r["date"]<"2026-06-01"]
    validation=[r for r in races if "2026-06-01"<=r["date"]<"2026-07-01"]
    diagnostic=[r for r in races if "2026-07-01"<=r["date"]<"2026-09-01"]
    if len(training)<500 or len(validation)<100 or len(diagnostic)<100:
        raise Invalid("Insufficient chronological data for the frozen protocol")
    model=fit(training)
    print(f"Fit converged in {model['iterations']} iterations; evaluating chronological splits",flush=True)
    model.update({"schema":SCHEMA,"name":"PuntingPowerAI History v1.1","created_at":now(),"trained_through":"2026-05-31","history_through":max(r["date"] for r in races),"sources":json.loads((root/"manifest.json").read_text()),"protocol_sha256":hashlib.sha256(Path("MODEL_PROTOCOL.md").read_bytes()).hexdigest(),"live_approved":False})
    metrics={"training_races":len(training),"excluded":excluded,"validation":evaluate(model,validation),"diagnostic_not_holdout":evaluate(model,diagnostic)}
    artifact={"model":model,"metrics":metrics,"history":history}
    sid=digest(artifact)
    path=output/(sid+".json")
    if not path.exists():
        with path.open("x",encoding="utf-8") as f:json.dump(artifact,f,indent=2,allow_nan=False)
    (output/"latest.txt").write_text(path.name,encoding="utf-8")
    report=render_model(model,metrics,sid)
    (output/(sid+".md")).write_text(report,encoding="utf-8")
    print(path,flush=True)
    return path


def render_model(model,metrics,sid):
    lines=[f"# {model['name']} — first statistical model", "", "Research baseline. Not approved for live decisions. No demonstrated betting edge.","",f"Trained through {model['trained_through']}; history through {model['history_through']}. Missing September history blocks current weekend predictions.","",f"Training races: {metrics['training_races']:,}. Artifact: {sid}","", "## Chronological evaluation", "", "July–August is a diagnostic, not an untouched holdout. Lower log loss and Brier score are better. BSP uses final prices and is a hindsight benchmark, unavailable for an earlier prediction.","", "| Period | Races | Model log loss | Uniform log loss | BSP hindsight log loss | Model Brier | Model top win rate |", "|---|---:|---:|---:|---:|---:|---:|"]
    for key in ("validation","diagnostic_not_holdout"):
        m=metrics[key]
        lines.append(f"| {m['from']} to {m['through']} | {m['races']} | {m['model_log_loss']:.4f} | {m['uniform_log_loss']:.4f} | {m['BSP_hindsight_log_loss']:.4f} | {m['model_race_brier']:.4f} | {m['model_top_win_rate']:.1%} |")
    d=metrics["diagnostic_not_holdout"]
    lo,hi=d["model_minus_BSP_log_loss_daily_bootstrap_95pct"]
    lines += ["",f"Daily-block bootstrap 95% interval for model minus BSP diagnostic log loss: [{lo:.4f}, {hi:.4f}]. Positive values favour BSP.","", "## Paper settlement diagnostic", "", "One accounting unit on the highest model probability; ties resolved by selection ID. Settled at BSP. These are explicit commission scenarios, not your account's fees or a pre-race executable-price backtest. Return uncertainty uses 500 daily-block bootstrap samples; it excludes model-selection and data-quality uncertainty.","", "| Commission | Return per unit | 95% return interval | Profit units | Maximum drawdown units |", "|---|---:|---:|---:|---:|"]
    for c,m in d["BSP_settlement_diagnostic"].items():
        low,high=m['return_daily_bootstrap_95pct']
        lines.append(f"| {float(c):.0%} | {m['return_per_unit']:.2%} | {low:.2%} to {high:.2%} | {m['profit_units']:.2f} | {m['max_drawdown_units']:.2f} |")
    lines += ["", "## Calibration", "", "| Probability bin | Runners | Mean probability | Observed win rate |", "|---|---:|---:|---:|"]
    for b in d["calibration"]:
        if b["runners"]:lines.append(f"| {b['range']} | {b['runners']} | {b['mean_p']:.3f} | {b['win_rate']:.3f} |")
    lines += ["", "## Fitted feature weights", "", "Standardised coefficients are associations, not causal effects.","", "| Feature | Weight |", "|---|---:|"]
    lines += [f"| {name} | {w:.5f} |" for name,w in zip(FEATURES,model["weights"])]
    lines += ["", "## Limitations", "", "Previous-race market prices supply a proxy for ability. This omits sectional, jockey, trainer, going and class features used in richer form models. Historical exports have no original publication audit; lagging by a whole day is an explicit availability assumption. Race completeness is checked through settlement and BSP consistency, but these checks are not equivalent to an independently archived official field.","", "Cross-race history uses exact normalised horse names, retaining country suffixes. Betfair selection IDs proved unstable across starts in this archive. Same-day duplicate names are not merged. Name reuse, spelling changes and missing country suffixes remain identity limitations; there is no authoritative cross-provider horse ID mapping yet.","", "No current-race BSP or result enters a feature. Scaling and coefficients are fitted only on training races. Outcomes update history only after every race on that date has been featurised. This is our fitted model, not a copy of Betfair's proprietary model.","", "Exclusions: "+json.dumps(metrics["excluded"],sort_keys=True),""]
    return "\n".join(lines)


def project(store, config, artifact_path):
    """Save explicitly experimental projections; never erase coverage limitations."""
    raw=Path(artifact_path).read_text(encoding="utf-8")
    artifact=json.loads(raw)
    sid=digest(artifact)
    if Path(artifact_path).stem!=sid:
        raise Invalid("Model artifact hash does not match filename")
    model=artifact["model"]
    if model["schema"]!=SCHEMA:
        raise Invalid("Unsupported feature schema")
    from .core import stamp
    names=defaultdict(set)
    for horse_id,h in artifact["history"].items():
        for n in h["names"]:names[namekey(n)].add(horse_id)
    output=[]
    for meeting in config["meetings"]:
        if model["history_through"]>=meeting["date"] or model["trained_through"]>=meeting["date"]:
            raise Invalid("Model/history cutoff must precede the target meeting date")
        latest={}
        for d in store.all(meeting["id"]):
            if d["kind"]=="field":latest[d["race_no"]]=d
        for n,field in sorted(latest.items()):
            if stamp(now())>=stamp(field["payload"]["start_at"]):
                output.append(f"{meeting['id']} R{n}: skipped, race started");continue
            if any(r["status"]=="emergency" for r in field["payload"]["runners"]):
                output.append(f"{meeting['id']} R{n}: skipped, emergency starters unresolved");continue
            distance=re_distance(field["payload"]["race_name"])
            active=[r for r in field["payload"]["runners"] if r["status"]=="active"]
            x=[];unknown=[]
            for r in active:
                matches=names.get(namekey(r["name"]),set())
                h=artifact["history"][next(iter(matches))] if len(matches)==1 else None
                if h is None:unknown.append(r["name"])
                x.append(features(h,meeting["date"],distance))
            probs=predict(model,x)
            limits=[f"History ends {model['history_through']}; September starts are missing", "Baseline is weaker than the hindsight market benchmark; no demonstrated edge"]
            if unknown:limits.append("Cold-start prior (no unique exact historical name match): "+", ".join(unknown))
            observed=now()
            d={"kind":"model","meeting_id":meeting["id"],"race_no":n,"source_url":"https://github.com/jayfshrimpton/punting-bot", "publisher":"PuntingPowerAI local statistical model", "observed_at":observed,"published_at":None,
               "payload":{"field_id":field["id"],"model":model["name"],"version":sid,"experimental":True,"limitations":limits,
                          "rows":[{"runner_id":r["id"],"name":r["name"],"rated_price":1/p} for r,p in zip(active,probs)]}}
            snapshot=store.add(d,config)
            output.append(f"{meeting['id']} R{n}: experimental projection {snapshot[:12]}, {len(unknown)} cold starts")
    return output


def re_distance(title):
    import re
    match=re.search(r"\((\d+) METRES\)",title)
    if not match:raise Invalid("No verified race distance in official field")
    return int(match[1])


if __name__=="__main__":
    train()
