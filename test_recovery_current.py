"""Only the latest live five-session candidate is presented as a new event."""
import copy,csv,io,json,subprocess,unittest
from datetime import timedelta
from unittest.mock import patch
import ma_trend as T
from test_minute_recovery import candidate_fixture
from test_ma_trend import run
from test_market_strength_integration import render

def aged_fixture(completed_after):
    f=candidate_fixture();s,q,p,h,cal,now=f;code=next(iter(h));bars=h[code];day=now
    for _ in range(completed_after):
        date=day.date().isoformat();bars.append(dict(bars[-1],date=date,open=108.9,high=109.,low=108.8,close=108.9,volume=40))
        day+=timedelta(days=1)
        while day.weekday()>4:day+=timedelta(days=1)
    cal=sorted(set(cal+[b['date'] for b in bars]+[day.date().isoformat()]))
    q[code].update(quote_at=str(day),ts=str(day),last_close=108.9,price=109.,open=108.9,low=108.9,high=109.1,change_pct=100*(109/108.9-1))
    s['quote_capture_at']=str(day);s['generated_at']=str(day)
    return s,q,p,h,cal,day

class CurrentRecovery(unittest.TestCase):
    def test_fifth_trading_day_allowed_sixth_hidden_with_latest_quote(self):
        fifth=aged_fixture(3);m=run(fifth)
        self.assertEqual(m['recovery_candidate']['age_sessions'],5);self.assertTrue(m['recovery_current'])
        sixth=aged_fixture(4);m=run(sixth)
        self.assertEqual(m['recovery_candidate']['age_sessions'],6);self.assertFalse(m['recovery_current'])
        self.assertEqual(m['recovery_candidate']['state'],'候选已过期');self.assertFalse(m.get('startup_pending'))
        self.assertNotIn('涨停收复',m['events']);self.assertEqual(sixth[0]['ma_trend']['recovery_candidates'],[])
        self.assertNotIn('涨停收复',sixth[0]['stock_board_ranking']['all']['items'][m['code']]['style_labels'])

    def test_daily_window_expires_without_requiring_ma10_failure(self):
        f=aged_fixture(5);bars=next(iter(f[3].values()));setup=T.daily(bars,f[4],limit_pct=10)
        c=setup['recovery_candidate'];self.assertEqual(c['age_sessions'],6);self.assertFalse(c['active'])
        self.assertEqual(c['state'],'候选已过期');self.assertGreater(bars[-1]['close'],T.average(bars,len(bars)-1,10))

    def test_age_uses_trade_sessions_not_weekend_or_calendar_days(self):
        f=aged_fixture(4);m=run(f);c=m['recovery_candidate']
        self.assertEqual(c['age_sessions'],6)
        from datetime import date
        self.assertGreater((f[5].date()-date.fromisoformat(c['date'])).days+1,6)

    def test_no_future_bar_changes_current_candidate_cycle(self):
        f=aged_fixture(3);m=run(f);before=copy.deepcopy(m)
        bars=next(iter(f[3].values()));bars.append(dict(bars[-1],date='2099-01-01',close=1.,high=1.,low=1.,open=1.))
        after=run(f);self.assertEqual(before,after)

    def test_stale_quote_and_unverified_support_have_no_current_candidate(self):
        f=candidate_fixture();code=next(iter(f[1]));f[1][code]['quote_at']=str(f[5]-timedelta(minutes=11))
        m=run(f);self.assertFalse(m['recovery_current']);self.assertNotIn('涨停收复',m['events'])
        f=candidate_fixture();code=next(iter(f[1]));f[1][code]['low']=100.
        m=run(f);self.assertTrue(m['pending']);self.assertFalse(m['recovery_current']);self.assertFalse(m['startup_pending'])

    def test_historical_confirmed_failed_and_expired_labels_hidden_everywhere(self):
        for state in ('强势入口已确认','候选已失效','候选已过期'):
            f=candidate_fixture();m=run(f);m['recovery_candidate'].update(active=False,state=state)
            T.finalize_recovery(m)
            import board_stock_rank
            board_stock_rank.attach(f[0])
            action="var row=DATA.stocks[0];document.getElementById('proof').innerHTML=JSON.stringify({tag:msRecoveryTag(row.ma_trend),table:mtTable([row]),detail:mtDetail(row.ma_trend),rank:msRankTable([row])});"
            proof=json.loads(render(f[0],action)['els']['proof']['innerHTML'])
            self.assertEqual(proof['tag'],'')
            for key in ('table','detail','rank'):self.assertNotIn('ms-recovery-tag',proof[key],(state,key))
            self.assertNotIn('recovery_candidate',T.brief(m))
            request=json.dumps(dict(rows=f[0]['stocks'],data=f[0],contexts=dict(view='radar')),ensure_ascii=False)
            output=subprocess.run(['node','csv_export.js'],input=request,capture_output=True,text=True,encoding='utf-8',check=True)
            row=next(csv.DictReader(io.StringIO(output.stdout.lstrip('\ufeff'))))
            self.assertEqual(row['涨停收复候选日期'],'');self.assertEqual(row['涨停收复候选状态'],'')

    def test_candidate_pill_is_single_and_old_origin_not_shown(self):
        f=candidate_fixture();m=run(f)
        action="var row=DATA.stocks[0];document.getElementById('proof').innerHTML=JSON.stringify({table:mtTable([row]),detail:mtDetail(row.ma_trend)});"
        proof=json.loads(render(f[0],action)['els']['proof']['innerHTML'])
        self.assertEqual(proof['table'].count('class="ms-tag ms-recovery-tag"'),1)
        self.assertNotIn('历史启动',proof['table']);self.assertNotIn('历史波段起点',proof['detail'])
        self.assertIn('第 2 / 5 个交易日',proof['table'])
        self.assertNotIn('暂态MA—',proof['table']);self.assertIn('暂态MA10',proof['table'])

    def test_expired_page_never_falls_back_to_old_candidate_badge_or_origin(self):
        f=candidate_fixture();run(f)
        action="mtSnapshotFresh=function(){return false;};var m=DATA.stocks[0].ma_trend;document.getElementById('proof').innerHTML=JSON.stringify({status:mtStatus(m),origin:mtOrigin(m),detail:mtDetail(m)});"
        proof=json.loads(render(f[0],action)['els']['proof']['innerHTML'])
        self.assertIn('快照已过期',proof['status']);self.assertNotIn('新启动候选',proof['status'])
        self.assertNotIn('历史启动',proof['origin']);self.assertNotIn('历史波段起点',proof['detail'])
        self.assertNotIn('ms-recovery-tag',proof['detail'])

    def test_formal_entry_ends_old_candidate(self):
        f=aged_fixture(1);bars=next(iter(f[3].values()));bars[-1].update(open=108.9,close=120.,high=120.,low=108.8,volume=400)
        c=T.daily(bars,f[4],limit_pct=10)['recovery_candidate']
        self.assertFalse(c['active']);self.assertEqual(c['state'],'强势入口已确认')

    def test_prior_failed_candidate_cannot_contaminate_new_formal_wave(self):
        f=candidate_fixture();q=next(iter(f[1].values()));q.update(price=98.,low=98.)
        failed=run(f);self.assertEqual(failed['status'],'候选已失效');prior=copy.deepcopy(f[0])
        new=aged_fixture(1);bars=next(iter(new[3].values()));bars[-1].update(open=108.9,close=120.,high=120.,low=108.8,volume=400)
        q=next(iter(new[1].values()));q.update(last_close=120.,price=120.1,low=120.,high=120.2,open=120.,change_pct=100*(120.1/120-1))
        m=run(new,previous=prior)
        self.assertFalse(m.get('candidate_mode'));self.assertIsNone(m['exit_at']);self.assertEqual(m['stage'],5)
        self.assertFalse(m['recovery_current']);self.assertFalse(m['tracking'])

if __name__=='__main__':unittest.main()
