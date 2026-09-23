import copy
import unittest
from punting.model import build_features, features, fit, predict
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


if __name__=="__main__":unittest.main()
