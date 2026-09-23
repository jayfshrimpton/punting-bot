import copy
import unittest
from datetime import date
from punting.core import Invalid
from punting.history_recent import normalise
from punting.model import build_features

class RecentHistoryTests(unittest.TestCase):
    def row(self):
        return dict(event_name='R2 1400m Hcap',menu_hint='Rosehill (AUS) 12th Sep',event_dt='12-09-2026 04:00',selection_name='3. Test Horse',event_id='123',selection_id='456',win_lose='1',bsp='3.2')

    def convert(self,row):
        return normalise(row,{'rosehill':{'NSW'}},date(2026,8,31),date(2026,9,22))

    def test_local_date_name_and_outcome(self):
        row,reason=self.convert(self.row())
        self.assertIsNone(reason)
        self.assertEqual(row['LOCAL_MEETING_DATE'],'2026-09-12')
        self.assertEqual(row['SELECTION_NAME'],'Test Horse')
        self.assertEqual(row['WIN_RESULT'],'WINNER')

    def test_non_thoroughbred_unknown_track_future_and_conflicting_dates(self):
        for title in ['R2 1609m Pace M','R2 2200m Trot S','Unrecognised']:
            r=self.row();r['event_name']=title
            self.assertIsNone(self.convert(r)[0])
        r=self.row();r['menu_hint']='New Track (AUS) 12th Sep'
        self.assertIsNone(self.convert(r)[0])
        r=self.row();r['menu_hint']='Rosehill (AUS) 26th Sep'
        self.assertIsNone(self.convert(r)[0])
        r=self.row();r['event_dt']='01-09-2026 04:00'
        with self.assertRaises(Invalid):self.convert(r)

    def test_history_refresh_does_not_mutate_parent_and_keeps_same_day_lag(self):
        original={'ALPHA':{'starts':1,'wins':0,'names':['Alpha'],'recent':[{'date':'2026-08-30','distance':1200,'bsp':4.,'won':0,'market_p':.25}]}}
        before=copy.deepcopy(original)
        races=[{'id':'x','date':'2026-09-01','rows':[{'SELECTION_NAME':'Alpha','WIN_RESULT':'WINNER','bsp':2.,'distance':1200}], 'market_p':[1.]}]
        processed,updated=build_features(races,original)
        self.assertEqual(original,before)
        self.assertEqual(updated['ALPHA']['starts'],2)
        self.assertAlmostEqual(processed[0]['x'][0][3],-__import__('math').log(4.))

if __name__=='__main__':unittest.main()
