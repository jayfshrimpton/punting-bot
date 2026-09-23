import copy
import math
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from punting.model import build_features, features, fit, history_index, load_races, match_history, predict
from punting.core import Invalid


def race(day,mid,winner="a",prices=(2,2)):
    return {"id":mid,"date":day,"track":"Synthetic", "rows":[{"SELECTION_ID":sid,"SELECTION_NAME":sid,"distance":1200,"bsp":price,"WIN_RESULT":"WINNER" if sid==winner else "LOSER"} for sid,price in zip(["a","b"],prices)],"market_p":[.5,.5]}


class ModelTests(unittest.TestCase):
    def test_target_outcome_and_BSP_cannot_change_its_features(self):
        past=race("2025-01-01","one")
        target=race("2025-01-03","two")
        a,_=build_features([past,target])
        changed=race("2025-01-03","two","b",(10,1.1))
        b,_=build_features([past,changed])
        self.assertEqual(a[1]["x"],b[1]["x"])

    def test_same_day_outcomes_cannot_leak(self):
        a,_=build_features([race("2025-01-01","one"),race("2025-01-01","two")])
        self.assertEqual(a[0]["x"],a[1]["x"])

    def test_history_inference_rejects_same_or_later_day(self):
        _,h=build_features([race("2025-01-01","one")])
        with self.assertRaises(Invalid):features(h["A"],"2025-01-01",1200)

    def test_changing_selection_ids_does_not_split_horse_history(self):
        first=race("2025-01-01","one")
        second=race("2025-01-03","two")
        second["rows"][0]["SELECTION_ID"]="different-market-selection-id"
        data,h=build_features([first,second])
        self.assertEqual(h["A"]["starts"],2)
        self.assertGreater(data[1]["x"][0][0],0)

    def test_ambiguous_same_day_names_do_not_merge_histories(self):
        data,h=build_features([race("2025-01-01","one"),race("2025-01-01","two")])
        self.assertEqual(h,{})

    def test_fitted_probabilities_are_complete_and_permutation_equivariant(self):
        data,_=build_features([race(f"2025-01-{i:02}",str(i),"a" if i%3 else "b") for i in range(1,25)])
        model=fit(data[:20]);p=predict(model,data[-1]["x"])
        self.assertAlmostEqual(sum(p),1);self.assertTrue(all(0<x<1 for x in p))
        self.assertEqual(p,list(reversed(predict(model,list(reversed(data[-1]["x"]))))))
        altered=copy.deepcopy(data[-1]["x"]);altered[0][0]=1e6
        before=copy.deepcopy(model);predict(model,altered)
        self.assertEqual(before,model)

    def test_official_names_match_suffix_free_archive_names(self):
        history={k:{} for k in ["CROSS TASMAN","SURFIN BIRD","ALABAMA STATE","ZAMBARDO","SUN SHINE","SUNSHINE"]}
        index=history_index(history)
        self.assertEqual(match_history(["CROSS TASMAN (NZ)","SURFIN’ BIRD","Alabama State","FRESHMAN (NZ)","SUN-SHINE"],history,index),
                         ["CROSS TASMAN","SURFIN BIRD","ALABAMA STATE",None,None])
        # The archive drops suffixes, so a local and an imported horse sharing a name cannot be told apart.
        self.assertEqual(match_history(["ZAMBARDO","ZAMBARDO (NZ)"],history,index),[None,None])

    def test_same_price_against_stronger_opposition_rates_higher_class(self):
        def named(day,mid,names,prices):
            total=sum(1/p for p in prices)
            return {"id":mid,"date":day,"track":"Synthetic","rows":[{"SELECTION_ID":n,"SELECTION_NAME":n,"distance":1200,"bsp":p,"WIN_RESULT":"WINNER" if i==0 else "LOSER"} for i,(n,p) in enumerate(zip(names,prices))],"market_p":[1/p/total for p in prices]}
        # ACE was a clear favourite and DUD an outsider; HERO and ZERO then ran at even money against them.
        data,_=build_features([named("2025-01-01","r1",["ACE","DUD"],[1.25,5]),
                               named("2025-01-02","r2",["HERO","ACE"],[2,2]),named("2025-01-02","r3",["ZERO","DUD"],[2,2]),
                               named("2025-01-03","r4",["HERO","ZERO"],[2,2])])
        hero,zero=data[-1]["x"]
        self.assertEqual(hero[2:4],zero[2:4])
        self.assertGreater(hero[8],zero[8])
        self.assertAlmostEqual(hero[9]-zero[9],math.log(2.6/1.4))

    def test_older_wins_count_less(self):
        _,h=build_features([race("2025-01-01","one")])
        soon=features(h["A"],"2025-01-08",1200)[1];later=features(h["A"],"2027-01-01",1200)[1]
        self.assertGreater(soon,later);self.assertGreater(later,.1)
        self.assertAlmostEqual(later,(.25+1)/(.25+10),places=3)

    def test_new_zealand_form_counts_but_other_jurisdictions_are_excluded(self):
        header="LOCAL_MEETING_DATE,TRACK,STATE_CODE,RACE_NO,WIN_MARKET_ID,RACING_TYPE,DISTANCE,SELECTION_ID,SELECTION_NAME,WIN_RESULT,WIN_BSP\n"
        rows="".join(f"{day},Synthetic,{state},1,{mid},Thoroughbred,1200,{sid},{sid},{result},2\n" for day,state,mid in [("2025-01-01","NZ","m1"),("2025-01-02","HK","m2"),("2025-01-03","NSW","m3")] for sid,result in [("A","WINNER"),("B","LOSER")])
        with tempfile.TemporaryDirectory() as root:
            data=(header+rows).encode()
            Path(root,"sample.csv").write_bytes(data)
            Path(root,"manifest.json").write_text(json.dumps([{"name":"sample.csv","sha256":hashlib.sha256(data).hexdigest()}]))
            races,excluded=load_races(root)
        self.assertEqual([r["jurisdiction"] for r in races],["NZ","AU"])
        self.assertEqual(excluded,{"unknown_jurisdiction_or_non_thoroughbred_rows":2})
        data,h=build_features(races)
        self.assertEqual(h["A"]["starts"],2)
        # The Australian race sees the New Zealand start as form.
        self.assertEqual(data[1]["x"][0][10],1)

    def test_day_first_archive_dates_are_loaded_and_bad_dates_counted(self):
        header="LOCAL_MEETING_DATE,TRACK,STATE_CODE,RACE_NO,WIN_MARKET_ID,RACING_TYPE,DISTANCE,SELECTION_ID,SELECTION_NAME,WIN_RESULT,WIN_BSP\n"
        rows="".join(f"{day},Synthetic,NSW,1,{mid},Thoroughbred,1200,{sid},{sid},{result},2\n" for day,mid in [("1/04/2025","m1"),("April 2025","m2")] for sid,result in [("A","WINNER"),("B","LOSER")])
        with tempfile.TemporaryDirectory() as root:
            data=(header+rows).encode()
            Path(root,"sample.csv").write_bytes(data)
            Path(root,"manifest.json").write_text(json.dumps([{"name":"sample.csv","sha256":hashlib.sha256(data).hexdigest()}]))
            races,excluded=load_races(root)
        self.assertEqual([r["date"] for r in races],["2025-04-01"])
        self.assertEqual(excluded,{"invalid_date":1})


if __name__=="__main__":unittest.main()
