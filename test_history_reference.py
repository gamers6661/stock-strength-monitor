"""历史重算参考隔离、后续增补、资金未来行与失败重试。"""
from datetime import datetime,timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import config
import fund_confirmation
import fund_history as fh
import history_reference as hr
import stock_strength as ss
from test_trend_consolidation import fixture

class HistoryTests(unittest.TestCase):
    def test_reference_twenty_days_future_excluded_incremental_and_real_preferred(self):
        bars,calendar,asof,day=fixture()
        first=datetime.fromisoformat(bars[0]['date']);extra=[]
        while len(extra)<10:
            first-=timedelta(days=1)
            if first.weekday()<5:extra.append(dict(bars[0],date=first.date().isoformat()))
        bars=list(reversed(extra))+bars;calendar=[b['date'] for b in bars]
        with tempfile.TemporaryDirectory() as root,patch.object(config,'CACHE_DIR',Path(root)):
            a=hr.ensure({'600001':bars},asof)
            self.assertEqual(len(a['available_days']),20)
            old=hr.load(calendar[-2]);self.assertEqual(old['asof'],calendar[-2]);self.assertNotIn('observed_at',old)
            self.assertFalse(ss._daily_path(calendar[-2]).exists())
            before=(hr.directory()/(calendar[-2]+'.json')).read_bytes()
            newer=dict(bars[-1],date=day)
            b=hr.ensure({'600001':bars+[newer]},day)
            self.assertEqual(b['generated'],[day]);self.assertEqual(len(b['available_days']),20)
            self.assertEqual((hr.directory()/(calendar[-2]+'.json')).read_bytes(),before)
            row={'code':'600001','stock_strength_percentile':50}
            ss.attach_history([row],calendar[-2],calendar[-6])
            self.assertEqual(row['strength_delta5_source'],'历史日线重算')
            path=ss._daily_path(calendar[-2]);path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'version':ss.VERSION,'asof':calendar[-2],'stocks':{'600001':{'percentile':10}}}),encoding='utf-8')
            ss.attach_history([row],calendar[-2],calendar[-6]);self.assertEqual(row['strength_delta1'],40)
            self.assertEqual(row['strength_delta1_source'],'真实收盘留档')
            path.write_text(json.dumps({'version':ss.VERSION,'asof':calendar[-2],'stocks':{}}),encoding='utf-8')
            ss.attach_history([row],calendar[-2],calendar[-6])
            self.assertIsNotNone(row['strength_delta1']);self.assertEqual(row['strength_delta1_source'],'历史日线重算')

    def test_fund_history_excludes_future_merges_then_updates_new_day(self):
        days=['2026-09-28','2026-09-29','2026-09-30']
        rows=[{'date':d,'main_net':1e8} for d in days]
        with tempfile.TemporaryDirectory() as root,patch.object(config,'CACHE_DIR',Path(root)),patch.object(fh.datafeed,'fetch_sina_fundflow',return_value=rows) as fetch:
            fh.refresh(['600001'],days[:-1]);self.assertEqual(len(fh.load()['600001']['rows']),2)
            fh.refresh(['600001'],days[:-1]);self.assertEqual(fetch.call_count,1)
            fh.refresh(['600001'],days);self.assertEqual(len(fh.load()['600001']['rows']),3)
            stock={'code':'600001'};fund_confirmation.attach([stock],days,fetch=False)
            self.assertEqual(stock['fund3_yi'],3);self.assertIsNone(stock['fund5_yi'])
            self.assertEqual(stock['fund_history_days'],3)

    def test_fund_failure_keeps_old_rows_and_retries_after_cooldown(self):
        with tempfile.TemporaryDirectory() as root,patch.object(config,'CACHE_DIR',Path(root)),patch.object(fh.datafeed,'fetch_sina_fundflow',side_effect=ValueError('缺口')) as fetch:
            p=fh.path();p.parent.mkdir(parents=True)
            p.write_text(json.dumps({'version':fh.VERSION,'stocks':{'600001':{'source':fh.SOURCE,'rows':[{'date':'2026-09-28','main_net':1}]}}}),encoding='utf-8')
            fh.refresh(['600001'],['2026-09-29']);fh.refresh(['600001'],['2026-09-29'])
            self.assertEqual(fetch.call_count,1);self.assertEqual(len(fh.load()['600001']['rows']),1)
            data=json.loads(p.read_text(encoding='utf-8'));data['stocks']['600001']['checked_at']=(datetime.now()-timedelta(minutes=31)).isoformat()
            p.write_text(json.dumps(data),encoding='utf-8');fh.refresh(['600001'],['2026-09-29'])
            self.assertEqual(fetch.call_count,2)

    def test_nonfinite_fund_values_do_not_confirm(self):
        for value in (True,float('nan'),float('inf'),None):
            result=fund_confirmation._summarize([{'date':str(i),'main_net':value} for i in range(10)],[str(i) for i in range(10)])
            self.assertIsNone(result[3])

if __name__=='__main__':unittest.main()
