import argparse
import json
import sys
from pathlib import Path
from .core import Invalid, now
from .store import Store


def main():
    parser=argparse.ArgumentParser(description="PuntingPowerAI: local statistical research and sourced race reports")
    parser.add_argument("--config",default="config.json")
    parser.add_argument("--data",default="data")
    commands=parser.add_subparsers(dest="command",required=True)
    refresh=commands.add_parser("refresh-fields");refresh.add_argument("--meeting")
    commands.add_parser("fetch-history")
    commands.add_parser("train")
    project=commands.add_parser("project");project.add_argument("--artifact")
    imports=commands.add_parser("import");imports.add_argument("path")
    report=commands.add_parser("report");report.add_argument("--meeting");report.add_argument("--cutoff");report.add_argument("--output",default="reports")
    commands.add_parser("status")
    template=commands.add_parser("template");template.add_argument("kind",choices=["model","quotes","evidence","coverage","decision"]);template.add_argument("--meeting",required=True);template.add_argument("--race",type=int);template.add_argument("--output",required=True)
    args=parser.parse_args();config=json.loads(Path(args.config).read_text(encoding="utf-8"))
    if getattr(args,"meeting",None) and args.meeting not in {m["id"] for m in config["meetings"]}:
        raise Invalid("Unknown configured meeting")
    if args.command=="fetch-history":
        from .history_fetch import fetch
        fetch(Path(args.data)/"history");return
    if args.command=="train":
        from .model import train
        train(Path(args.data)/"history",Path(args.data)/"model");return
    store=Store(args.data)
    try:
        if args.command=="refresh-fields":
            from .sources import fetch_fields
            failures=0
            for m in config["meetings"]:
                if args.meeting and args.meeting!=m["id"]:continue
                ids,detail=fetch_fields(m,store,config);print(m["id"]+": "+detail);failures+=not bool(ids)
            if failures:raise Invalid(f"{failures} field fetch(es) failed; attempts logged")
        elif args.command=="import":
            raw=Path(args.path).read_text(encoding="utf-8-sig")
            docs=json.loads(raw)
            for d in docs if isinstance(docs,list) else [docs]:print(store.add(d,config))
        elif args.command=="project":
            from .model import project
            root=Path(args.data)/"model"
            artifact=Path(args.artifact) if args.artifact else root/(root/"latest.txt").read_text().strip()
            print("\n".join(project(store,config,artifact)))
        elif args.command=="report":
            from .report import build
            cutoff=args.cutoff or now()
            for m in config["meetings"]:
                if not args.meeting or args.meeting==m["id"]:print(build(store,config,m["id"],cutoff,args.output)/"brief.html")
        elif args.command=="status":
            for m in config["meetings"]:
                docs=store.all(m["id"])
                print(m["id"],json.dumps({kind:sum(d["kind"]==kind for d in docs) for kind in sorted({d["kind"] for d in docs})}))
        elif args.command=="template":
            docs=store.all(args.meeting)
            fields=[d for d in docs if d["kind"]=="field" and d.get("race_no")==args.race]
            field=fields[-1] if fields else None
            if args.kind in {"model","quotes","decision"} and field is None:raise Invalid("Import official fields and specify --race first")
            d={"kind":args.kind,"meeting_id":args.meeting,"source_url":"https://example.com/replace-with-original-source","publisher":"REPLACE","observed_at":None,"published_at":None,"payload":{}}
            if args.race:d["race_no"]=args.race
            p=d["payload"]
            if args.kind in {"model","quotes"}:
                p.update(field_id=field["id"],rows=[{"runner_id":r["id"],"name":r["name"],**({"rated_price":None} if args.kind=="model" else {"odds":None,"size":None})} for r in field["payload"]["runners"] if r["status"]=="active"])
                p.update({"model":"REPLACE exact model identity","version":None} if args.kind=="model" else {"provider":"REPLACE","market":"fixed_win","commission":None,"terms":"REPLACE price terms and limitations"})
            elif args.kind=="evidence":p.update(runner_ids=[],author=None,original_url=d["source_url"],claim_id="REPLACE original statement identity",excerpt="",summary="REPLACE",type="opinion",conditions=[],reviewed=False)
            elif args.kind=="coverage":p.update(source="Punters",status="manual import needed",detail="REPLACE",checked_urls=[d["source_url"]])
            else:p.update(runner_id=None,action="pass",reason="REPLACE",price=None)
            path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True)
            with path.open("x",encoding="utf-8") as f:json.dump(d,f,indent=2)
            print(path)
    finally:store.close()


if __name__=="__main__":
    try:main()
    except (Invalid,ValueError,OSError,KeyError) as exc:
        print("Error: "+str(exc),file=sys.stderr);sys.exit(1)
