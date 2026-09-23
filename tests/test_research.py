import copy
import json
import math
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from punting.core import Invalid, break_even, expected_return, field_signature, local, stamp
from punting.store import Store
from punting.report import assess, build, render_evidence, to_html
from punting.sources import fetch_fields, parse_fields

CONFIG=json.loads(Path("config.json").read_text())
MID="rosehill-2026-09-26"
OBS="2026-09-23T00:00:00+00:00"


def doc(kind,payload,race=1,observed=OBS):
    return {"kind":kind,"meeting_id":MID,"race_no":race,"source_url":"https://example.com/synthetic","publisher":"Synthetic test fixture","observed_at":observed,"published_at":None,"payload":payload}


def field():
    return doc("field",{"race_name":"Synthetic test (1200 METRES)","start_at":"2026-09-26T12:00:00+10:00","runners":[{"id":"a","name":"Alpha (NZ)","number":"1","status":"active"},{"id":"b","name":"Beta","number":"2","status":"active"}],"going":"Good 4","rail":"True","official":True,"card_races":1})


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(Path(self.temp.name)/"data")
        self.fid=self.store.add(field(),CONFIG)

    def tearDown(self):
        self.store.close();self.temp.cleanup()

    def model(self):
        return doc("model",{"field_id":self.fid,"model":"Synthetic equal-chance model","version":"test","rows":[{"runner_id":"a","name":"Alpha (NZ)","rated_price":2.0},{"runner_id":"b","name":"Beta","rated_price":2.0}]})

    def quotes(self):
        return doc("quotes",{"field_id":self.fid,"provider":"Synthetic provider","market":"exchange_back_win","commission":.05,"terms":"Synthetic executable size","rows":[{"runner_id":"a","name":"Alpha (NZ)","odds":3.0,"size":20}]})

    def assessment(self,cutoff="2026-09-23T00:01:00+00:00"):
        ds=self.store.all(MID,cutoff);f=[d for d in ds if d["kind"]=="field"][-1]
        return assess(f,ds,cutoff,CONFIG)

    def test_commission_and_break_even(self):
        self.assertAlmostEqual(expected_return(.25,5,.08),.17)
        self.assertAlmostEqual(expected_return(.25,break_even(.25,.08),.08),0)
        for x in [float("nan"),float("inf"),True]:
            with self.assertRaises(Invalid):expected_return(x,5,.05)

    def test_wrong_meeting_and_date(self):
        d=field();d["meeting_id"]="wrong"
        with self.assertRaises(Invalid):self.store.add(d,CONFIG)
        d=field();d["payload"]["start_at"]="2026-09-27T12:00:00+10:00"
        with self.assertRaises(Invalid):self.store.add(d,CONFIG)

    def test_full_field_and_identity(self):
        d=self.model();d["payload"]["rows"].pop()
        with self.assertRaises(Invalid):self.store.add(d,CONFIG)
        d=self.model();d["payload"]["rows"][0]["name"]="Alpha"
        with self.assertRaises(Invalid):self.store.add(d,CONFIG)
        d=self.model();d["race_no"]=2
        with self.assertRaises(Invalid):self.store.add(d,CONFIG)

    def test_duplicate_and_probability_consistency(self):
        d=field();d["payload"]["runners"][1]["name"]="ALPHA (NZ)"
        with self.assertRaises(Invalid):self.store.add(d,CONFIG)
        for price in [float("nan"),0,1,10]:
            d=self.model();d["payload"]["rows"][0]["rated_price"]=price
            with self.assertRaises(Invalid):self.store.add(d,CONFIG)

    def test_small_rounding_normalization_disclosed(self):
        d=self.model();d["payload"]["rows"][0]["rated_price"]=2.01
        self.store.add(d,CONFIG);a=self.assessment()
        self.assertAlmostEqual(sum(r["p"] for r in a["rows"]),1)
        self.assertNotEqual(a["sum"],1)

    def test_fresh_candidate_stale_and_unknown_commission(self):
        self.store.add(self.model(),CONFIG);self.store.add(self.quotes(),CONFIG)
        self.assertEqual(self.assessment()["rows"][0]["state"],"candidate for human review")
        self.assertEqual(self.assessment("2026-09-23T00:06:00+00:00")["rows"][0]["state"],"watch / recheck")
        d=self.quotes();d["observed_at"]="2026-09-23T00:00:30+00:00";d["payload"]["commission"]=None
        self.store.add(d,CONFIG)
        self.assertIsNone(self.assessment()["rows"][0]["best"])

    def test_scratch_invalidates_value_and_preserves_raw_model(self):
        self.store.add(self.model(),CONFIG);self.store.add(self.quotes(),CONFIG)
        d=field();d["observed_at"]="2026-09-23T00:00:30+00:00";d["payload"]["runners"][1]["status"]="scratched"
        self.store.add(d,CONFIG);a=self.assessment()
        self.assertEqual(a["rows"][0]["p"],.5)
        self.assertEqual(a["rows"][0]["state"],"watch / recheck")
        self.assertEqual(a["rows"][1]["state"],"scratched")

    def test_experimental_scores_never_become_candidates(self):
        d=self.model();d["payload"]["experimental"]=True
        self.store.add(d,CONFIG);self.store.add(self.quotes(),CONFIG)
        self.assertEqual(self.assessment()["rows"][0]["state"],"watch / recheck")

    def test_emergencies_block_numeric_import(self):
        d=field();d["observed_at"]="2026-09-23T00:00:01+00:00";d["payload"]["runners"][1]["status"]="emergency"
        sid=self.store.add(d,CONFIG);m=self.model();m["observed_at"]="2026-09-23T00:00:02+00:00";m["payload"]["field_id"]=sid
        with self.assertRaises(Invalid):self.store.add(m,CONFIG)

    def test_explicit_emergency_scenario_rates_every_runner_but_never_candidates(self):
        d=field();d["observed_at"]="2026-09-23T00:00:01+00:00";d["payload"]["runners"][1]["status"]="emergency"
        sid=self.store.add(d,CONFIG);m=self.model();m["observed_at"]="2026-09-23T00:00:02+00:00"
        m["payload"].update(field_id=sid,experimental=True,includes_emergencies=True)
        self.store.add(m,CONFIG)
        a=self.assessment()
        self.assertAlmostEqual(sum(r['p'] for r in a['rows']),1)
        self.assertEqual(a['rows'][1]['state'],'emergency')
        self.assertEqual(a['rows'][1]['p'],.5)
        self.assertTrue(any('emergencies' in x for x in a['issues']))
        self.assertFalse(any(r['state']=='candidate for human review' for r in a['rows']))
        m['payload']['rows'].pop()
        with self.assertRaises(Invalid):self.store.add(m,CONFIG)
        m=self.model();m['payload'].update(includes_emergencies=True,experimental=False)
        with self.assertRaises(Invalid):self.store.add(m,CONFIG)
        q=self.quotes();q['observed_at']='2026-09-23T00:00:03+00:00';q['payload']['field_id']=sid
        with self.assertRaises(Invalid):self.store.add(q,CONFIG)

    def test_cutoff_and_outcome_boundary(self):
        m=self.model();m["observed_at"]="2026-09-23T00:05:00+00:00";self.store.add(m,CONFIG)
        self.assertIsNone(self.assessment()["model"])
        m=self.model();m["payload"]["WIN_BSP"]=3
        with self.assertRaises(Invalid):self.store.add(m,CONFIG)

    def test_post_start_import_rejected_even_with_past_timestamps(self):
        config=copy.deepcopy(CONFIG);config["meetings"][0]["date"]="2026-09-22"
        f=field();f["observed_at"]="2026-09-21T00:00:00Z";f["payload"]["start_at"]="2026-09-22T12:00:00+10:00"
        sid=self.store.add(f,config)
        m=self.model();m["payload"]["field_id"]=sid;m["observed_at"]="2026-09-22T03:00:00Z"
        with self.assertRaises(Invalid):self.store.add(m,config)
        m=self.model();m["published_at"]="2026-09-23T01:00:00+00:00"
        with self.assertRaises(Invalid):self.store.add(m,CONFIG)

    def test_evidence_identity_conditions_and_syndication(self):
        e=doc("evidence",{"runner_ids":["wrong"],"author":"Analyst","original_url":"https://example.com/original","claim_id":"one","excerpt":"","summary":"Likes Alpha if rain arrives","type":"opinion","conditions":["rain required"],"reviewed":True})
        with self.assertRaises(Invalid):self.store.add(e,CONFIG)
        e["payload"]["runner_ids"]=["a"];self.store.add(e,CONFIG)
        copy_e=copy.deepcopy(e);copy_e["source_url"]="https://example.com/syndicated";self.store.add(copy_e,CONFIG)
        lines=render_evidence([d for d in self.store.all() if d["kind"]=="evidence"],{"a":"Alpha (NZ)"})
        self.assertEqual(len(lines),1);self.assertIn("rain required",lines[0])

    def test_failed_source_is_not_absence(self):
        d=doc("coverage",{"source":"Punters","status":"failed","detail":"HTTP 403","checked_urls":["https://example.com/"]});d.pop("race_no")
        self.store.add(d,CONFIG)
        version=build(self.store,CONFIG,MID,OBS,Path(self.temp.name)/"reports")
        result=(version/"brief.md").read_text(encoding="utf-8")
        self.assertIn("| Punters | failed |",result)
        self.assertIn("Model unavailable",result)

    def test_immutable_and_reports_escape_html(self):
        with self.assertRaises(sqlite3.IntegrityError):self.store.db.execute("DELETE FROM snapshots")
        out=to_html('# Test\n\n<script>alert(1)</script>\n\n[bad](javascript:alert(1))')
        self.assertNotIn("<script>",out);self.assertNotIn('href="javascript:',out)
        first=build(self.store,CONFIG,MID,OBS,Path(self.temp.name)/"reports")
        second=build(self.store,CONFIG,MID,OBS,Path(self.temp.name)/"reports")
        self.assertNotEqual(first,second);self.assertTrue((first/"brief.md").exists())

    def test_daylight_saving(self):
        self.assertIn("AEST",local("2026-09-26T00:00:00Z"))
        self.assertIn("AEDT",local("2026-10-10T00:00:00Z"))

    def test_parser_rejects_partial_official_card(self):
        raw='Rosehill Gardens Saturday, 26 September 2026 Total Number of acceptors for this meeting (including emergencies) 3 <span>Race 1 - 12:00PM Test (1200 METRES)</span><table class="race-strip-fields"><tr><td class="no">1</td><td class="horse"><a href="../HorseFullForm.aspx?horsecode=abc">Alpha</a></td></tr></table>'
        with self.assertRaises(Invalid):parse_fields(raw,CONFIG["meetings"][0],OBS,"https://example.com/")

    def test_race_day_refresh_keeps_races_not_yet_started(self):
        config=copy.deepcopy(CONFIG);meeting=config["meetings"][0];meeting["date"]="2026-09-22"
        row=lambda n,code,name:f'<tr><td class="no">{n}</td><td class="horse"><a href="../HorseFullForm.aspx?horsecode={code}">{name}</a></td></tr>'
        raw=('Rosehill Gardens Tuesday, 22 September 2026 Total Number of acceptors for this meeting (including emergencies) 4 '
             '<span>Race 1 - 12:00PM Early (1200 METRES)</span><table class="race-strip-fields">'+row(1,"a","ALPHA")+row(2,"b","BETA")+'</table>'
             '<span>Race 2 - 4:00PM Late (1400 METRES)</span><table class="race-strip-fields">'+row(1,"c","GAMMA")+row(2,"d","DELTA")+'</table>')
        response=mock.MagicMock();response.__enter__.return_value.read.return_value=raw.encode()
        # 1:30pm Sydney: race 1 has started, race 2 has not.
        with mock.patch("punting.sources.urlopen",return_value=response),mock.patch("punting.sources.now",return_value="2026-09-22T03:30:00+00:00"):
            ids,detail,ok=fetch_fields(meeting,self.store,config)
        self.assertTrue(ok);self.assertIn("already started: R1",detail)
        self.assertEqual([d["payload"]["race_name"] for d in self.store.all(MID) if d["id"] in ids],["Late (1400 METRES)"])


if __name__=="__main__":unittest.main()
