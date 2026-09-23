"""Append-only SQLite snapshots. Validated canonical documents and hashes retained."""
import json
import sqlite3
from pathlib import Path
from .core import Invalid, canonical, digest, namekey, now, stamp, validate


class Store:
    def __init__(self, root="data"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / "research.sqlite")
        self.db.execute("CREATE TABLE IF NOT EXISTS snapshots(id TEXT PRIMARY KEY, kind TEXT NOT NULL, meeting TEXT NOT NULL, race INTEGER, observed TEXT NOT NULL, imported TEXT NOT NULL, document TEXT NOT NULL)")
        for action in ("UPDATE", "DELETE"):
            self.db.execute(f"CREATE TRIGGER IF NOT EXISTS forbid_{action} BEFORE {action} ON snapshots BEGIN SELECT RAISE(ABORT, 'Snapshots are immutable'); END")
        self.db.commit()

    def close(self):
        self.db.close()

    def all(self, meeting=None, cutoff=None):
        rows = self.db.execute("SELECT id,document FROM snapshots" + (" WHERE meeting=?" if meeting else ""), (meeting,) if meeting else ())
        result = []
        for sid, raw in rows:
            d = json.loads(raw)
            if digest(d) != sid:
                raise Invalid("Stored snapshot hash mismatch")
            if cutoff is None or stamp(d["observed_at"]) <= stamp(cutoff):
                result.append(dict(d, id=sid))
        return sorted(result, key=lambda d: (stamp(d["observed_at"]), d["id"]))

    def add(self, d, config):
        validate(d, config)
        all_docs = self.all(d["meeting_id"], d["observed_at"])
        fields = [x for x in all_docs if x["kind"] == "field" and x.get("race_no") == d.get("race_no")]
        p = d["payload"]
        if d["kind"] in {"model", "quotes", "decision"} or (d["kind"] == "evidence" and d.get("race_no")):
            if not fields:
                raise Invalid("Import the correct official field first")
            field = fields[-1]
            if stamp(d["observed_at"]) >= stamp(field["payload"]["start_at"]):
                raise Invalid("Current-race post-start inputs are prohibited")
            runners = {r["id"]: r for r in field["payload"]["runners"]}
            if d["kind"] in {"model", "quotes"}:
                based = next((f for f in fields if f["id"] == p["field_id"]), None)
                if based is None:
                    raise Invalid("Numeric data refers to a missing, future or wrong-race field")
                runners = {r["id"]: r for r in based["payload"]["runners"]}
                active = {rid for rid, r in runners.items() if r["status"] == "active"}
                if any(r["status"] == "emergency" for r in runners.values()):
                    raise Invalid("Resolve emergency starters before importing a numeric field")
                ids = {r["runner_id"] for r in p["rows"]}
                if not ids <= active or (d["kind"] == "model" and ids != active):
                    raise Invalid("Model must cover the entire active field; quotes must match active runners")
                for r in p["rows"]:
                    if namekey(r["name"]) != namekey(runners[r["runner_id"]]["name"]):
                        raise Invalid("Runner ID/name mismatch; resolve explicitly, never fuzzy join")
                if d["kind"] == "model":
                    total = sum(1/r["rated_price"] for r in p["rows"])
                    if abs(total-1) > config["probability_sum_tolerance"] + 1e-12:
                        raise Invalid(f"Full-field implied probabilities sum to {total:.6f}; exceeds tolerance")
            elif d["kind"] == "evidence":
                if not set(p["runner_ids"]) <= runners.keys():
                    raise Invalid("Evidence attributed to a runner outside this race")
            elif p["runner_id"] is not None and p["runner_id"] not in runners:
                raise Invalid("Human decision references wrong runner")
        sid = digest(d)
        folder = self.root / "snapshots"
        folder.mkdir(exist_ok=True)
        path = folder / f"{sid}.json"
        raw = canonical(d)
        if path.exists() and path.read_text(encoding="utf-8") != raw:
            raise Invalid("Immutable snapshot file was modified")
        if not path.exists():
            with path.open("x", encoding="utf-8") as f:
                f.write(raw)
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO snapshots VALUES(?,?,?,?,?,?,?)", (sid,d["kind"],d["meeting_id"],d.get("race_no"),stamp(d["observed_at"]).isoformat(),now(),raw))
        return sid
