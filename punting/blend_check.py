"""Does the model add information beyond the market? A diagnostic, never a feature.

Fits p ∝ exp(a·log p_model + b·log p_market) on training races and scores June
development validation. a ≈ 0 means a gap between model and market ratings is
not evidence of value: the market price already contains the model's information.
"""
import argparse
import json
import math
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

from .model import archive_rows, build_features, load_races, predict


def fit_blend(data):
    """data: (log model p, log market p, winner mask) per race. Returns (a, b)."""
    def loss(params):
        a,b=params;total=0.
        for lm,lk,y in data:
            s=a*lm+b*lk;s=s-s.max()
            total-=s[y].sum()-math.log(np.exp(s).sum())
        return total/len(data)
    return tuple(minimize(loss,[.3,1.],method="Nelder-Mead",options={"xatol":1e-5,"fatol":1e-9,"maxiter":2000}).x)


def race_losses(params, data):
    a,b=params;out=[]
    for lm,lk,y in data:
        s=a*lm+b*lk;s=s-s.max()
        out.append(-(s[y].sum()-math.log(np.exp(s).sum())))
    return out


def blend_data(model, races, prices=None):
    """Market is normalised BSP, or pre-off prices keyed by (market ID, selection ID); skip races without a full pre-off book."""
    data,days=[],[]
    for race in races:
        if prices is None:
            market=np.array(race["market_p"])
        else:
            q=[prices.get((race["id"],r["SELECTION_ID"])) for r in race["rows"]]
            if any(v is None or not v>1 for v in q):continue
            market=1/np.array(q);market=market/market.sum()
        y=np.array([r["WIN_RESULT"]=="WINNER" for r in race["rows"]])
        data.append((np.log(predict(model,race["x"])),np.log(market),y));days.append(race["date"])
    return data,days


def check(artifact_path, root="data/history"):
    model=json.loads(Path(artifact_path).read_text(encoding="utf-8"))["model"]
    races,_=load_races(root);races,_=build_features(races)
    races=[r for r in races if r["jurisdiction"]=="AU"]
    preoff={}
    for r in archive_rows(root):
        try:preoff[(r["WIN_MARKET_ID"],r["SELECTION_ID"])]=float(r["BEST_AVAIL_BACK_AT_SCHEDULED_OFF"])
        except (KeyError,TypeError,ValueError):pass
    results={}
    for label,prices in (("BSP_hindsight",None),("best_back_at_scheduled_off",preoff)):
        train,_=blend_data(model,[r for r in races if "2025-01-01"<=r["date"]<"2026-06-01"],prices)
        valid,days=blend_data(model,[r for r in races if "2026-06-01"<=r["date"]<"2026-07-01"],prices)
        a,b=fit_blend(train)
        alone=fit_blend([(np.zeros_like(lk),lk,y) for _,lk,y in train])[1]
        diff=np.array(race_losses((a,b),valid))-np.array(race_losses((0,alone),valid))
        blocks={}
        for day,v in zip(days,diff):blocks.setdefault(day,[]).append(v)
        blocks=list(blocks.values());rng=np.random.default_rng(20260923)
        boot=[np.mean([v for i in rng.integers(0,len(blocks),len(blocks)) for v in blocks[i]]) for _ in range(500)]
        results[label]={"training_races":len(train),"validation_races":len(valid),"model_weight":a,"market_weight":b,
                        "validation_blend_minus_market_log_loss":float(diff.mean()),"daily_bootstrap_95pct":np.quantile(boot,[.025,.975]).tolist()}
    return results


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--artifact",help="model artifact; defaults to data/model/latest.txt")
    args=parser.parse_args()
    path=args.artifact or Path("data/model")/Path("data/model/latest.txt").read_text().strip()
    print(json.dumps(check(path),indent=2))
