import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from punting import betfair
from punting.core import Invalid
from punting.store import Store

CONFIG=json.loads(Path("config.json").read_text())
MID="rosehill-2026-09-26"
OBS="2026-09-23T00:00:00+00:00"


def field(status="active"):
    return {"kind":"field","meeting_id":MID,"race_no":1,"source_url":"https://example.com/synthetic","publisher":"Synthetic test fixture","observed_at":OBS,"published_at":None,
            "payload":{"race_name":"Synthetic test (1200 METRES)","start_at":"2026-09-26T12:00:00+10:00","going":"Good 4","rail":"True","official":True,"card_races":1,
                       "runners":[{"id":"a","name":"CROSS TASMAN (NZ)","number":"1","status":"active"},{"id":"b","name":"SURFIN’ BIRD","number":"2","status":status}]}}


def market(start="2026-09-26T02:00:00.000Z",name="R1 1200m Hcap"):
    return {"marketId":"1.23","marketName":name,"marketStartTime":start,"description":{"marketBaseRate":8.0},
            "runners":[{"selectionId":11,"runnerName":"1. Cross Tasman","metadata":{"CLOTH_NUMBER":"1"}},
                       {"selectionId":22,"runnerName":"2. Surfin Bird","metadata":{"CLOTH_NUMBER":"2"}}]}


def prices(status="OPEN",inplay=False):
    return {"marketId":"1.23","status":status,"inplay":inplay,"isMarketDataDelayed":True,
            "runners":[{"selectionId":11,"status":"ACTIVE","ex":{"availableToBack":[{"price":3.5,"size":120.0}],"availableToLay":[{"price":3.65,"size":40.0}]}},
                       {"selectionId":22,"status":"REMOVED","ex":{"availableToBack":[]}}]}


class BetfairTests(unittest.TestCase):
    def test_settings_read_env_file_and_require_the_app_key(self):
        with tempfile.TemporaryDirectory() as root, mock.patch.dict(os.environ,{},clear=True):
            path=Path(root,".env")
            path.write_text('# comment\nBETFAIR_APP_KEY="abc123"\nBETFAIR_USERNAME=\n',encoding="utf-8")
            self.assertEqual(betfair.settings(path)["BETFAIR_APP_KEY"],"abc123")
            path.write_text("BETFAIR_APP_KEY=\n",encoding="utf-8")
            with self.assertRaises(Invalid):betfair.settings(path)

    def test_login_keeps_only_the_token(self):
        calls=[]
        def reply(url,body=None,headers=None):
            calls.append((url,body))
            return {"status":"SUCCESS","token":"session-token"} if url.endswith("login") else {"status":"SUCCESS"}
        with tempfile.TemporaryDirectory() as root, mock.patch.object(betfair,"request",reply), \
             mock.patch.object(betfair.getpass,"getpass",return_value="secret-password"):
            session=Path(root,"private","betfair-session.json")
            betfair.login({"BETFAIR_APP_KEY":"key","BETFAIR_USERNAME":"jay"},session)
            saved=session.read_text(encoding="utf-8")
        self.assertEqual(set(json.loads(saved)),{"token","saved_at"})
        self.assertNotIn("secret-password",saved)
        self.assertIn(b"password=secret-password",calls[0][1])
        self.assertTrue(calls[1][0].endswith("keepAlive"))

    def test_failed_login_saves_nothing(self):
        with tempfile.TemporaryDirectory() as root, mock.patch.object(betfair,"request",return_value={"status":"FAIL","error":"INVALID_USERNAME_OR_PASSWORD"}), \
             mock.patch.object(betfair.getpass,"getpass",return_value="wrong"):
            session=Path(root,"betfair-session.json")
            with self.assertRaises(Invalid):betfair.login({"BETFAIR_APP_KEY":"key","BETFAIR_USERNAME":"jay"},session)
            self.assertFalse(session.exists())

    def test_markets_match_on_race_time_saddlecloth_and_name(self):
        f=dict(field(),id="f1")
        (m,selections,unmatched),=betfair.match([market()],{1:f}).values()
        self.assertEqual(selections,{"a":11,"b":22});self.assertEqual(unmatched,[])
        self.assertEqual(betfair.match([market(start="2026-09-26T03:00:00.000Z")],{1:f}),{})
        other=market();other["runners"][1]["runnerName"]="2. Some Other Horse"
        self.assertEqual(betfair.match([other],{1:f})[1][2],["SURFIN’ BIRD (number or name differs on Betfair)"])
        gone=market();gone["runners"].pop()
        self.assertIn("not in the Betfair market",betfair.match([gone],{1:f})[1][2][0])

    def test_quotes_are_best_back_prices_that_the_store_accepts(self):
        with tempfile.TemporaryDirectory() as root:
            store=Store(Path(root)/"data")
            try:
                f=field();f["id"]=store.add(f,CONFIG)
                d,reason=betfair.quotes_document(MID,1,f,market(),prices(),{"a":11,"b":22},"2026-09-23T00:01:00+00:00")
                self.assertIsNone(reason)
                self.assertEqual(d["payload"]["rows"],[{"runner_id":"a","name":"CROSS TASMAN (NZ)","odds":3.5,"size":120.0,"lay_odds":3.65,"lay_size":40.0}])
                self.assertEqual(d["payload"]["commission"],.08)
                store.add(d,CONFIG)
            finally:store.close()
        self.assertEqual(betfair.quotes_document(MID,1,f,market(),prices(inplay=True),{"a":11},OBS)[0],None)
        self.assertEqual(betfair.quotes_document(MID,1,f,market(),prices(status="SUSPENDED"),{"a":11},OBS)[0],None)
        # A lay offer shorter than the back offer is impossible; fixed odds carry no lay side.
        bad=json.loads(json.dumps(d));bad["payload"]["rows"][0]["lay_odds"]=3.0
        fixed=json.loads(json.dumps(d));fixed["payload"].update(market="fixed_win",commission=0)
        for wrong in (bad,fixed):
            with tempfile.TemporaryDirectory() as root:
                store=Store(Path(root)/"data")
                try:
                    wrong["payload"]["field_id"]=store.add(field(),CONFIG)
                    with self.assertRaises(Invalid):store.add(wrong,CONFIG)
                finally:store.close()
        pending=field("emergency");pending["id"]="f2"
        self.assertIn("emergencies",betfair.quotes_document(MID,1,pending,market(),prices(),{"a":11},OBS)[1])

    def test_market_is_read_only_when_prices_are_tight(self):
        row=lambda rid,back,lay:{"runner_id":rid,"name":rid,"odds":back,"size":50,"lay_odds":lay,"lay_size":50}
        view,note=betfair.market_view([row("a",1.95,2.0),row("b",2.0,2.06),row("c",60,80)])
        self.assertAlmostEqual(sum(view.values()),1);self.assertGreater(view["a"],view["b"]);self.assertIn("book",note)
        # Early placeholder backs such as 1.16 against a lay of 30 are not prices.
        self.assertIsNone(betfair.market_view([row("a",1.16,30),row("b",2.0,2.06)])[0])
        self.assertIsNone(betfair.market_view([row("a",4,4.2),row("b",4,4.2)])[0])


if __name__=="__main__":unittest.main()
