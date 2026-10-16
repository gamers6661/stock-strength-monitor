"""Verified cap chains, relay competition, peer exclusions and live boundaries."""
import copy,json,subprocess,tempfile,unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
import config,emotion_relay as E,relay_data as D,board_stock_rank as B,intraday,ui_payload
from test_market_strength import fixture

def sample():
    s,q,p,h,cal,now=fixture(20);codes=list(q)
    sealed={codes[0]:[-3,-2,-1],codes[1]:[-1],codes[2]:[-3,-2,-1],codes[3]:[-1],codes[4]:[-3,-2]}
    for code,indices in sealed.items():
        for i,b in enumerate(h[code]):
            previous=h[code][i-1]['close'] if i else 100.
            close=D.limit_price(previous) if i-len(cal) in indices else previous*.97 if code==codes[4] and i==len(cal)-1 else previous
            b.update(open=previous,close=close,high=max(previous,close),low=min(previous,close),volume=100.)
    evidence=dict(pools={day:dict(day=day,date_verified=True,entries={}) for day in cal[-21:]},raw={},fetch={})
    for code,bars in h.items():
        evidence['raw'][code]=dict(bars=copy.deepcopy(bars))
        for b in bars:
            if b['date'] in evidence['pools']:
                index=cal.index(b['date'])
                if index and b['close']==D.limit_price(bars[index-1]['close']):evidence['pools'][b['date']]['entries'][code]=dict(name=code,price=b['close'])
        last=bars[-1]['close'];up=D.limit_price(last);price=up if code in (codes[0],codes[1],codes[3]) else last*1.02 if code!=codes[2] else last*.96
        q[code].update(price=price,last_close=last,open=last,high=max(price,last),low=min(price,last),limit_up=up,turnover_pct=5.,change_pct=100*(price/last-1))
        row=s['stocks'][codes.index(code)];row.update(q[code]);row['ma_trend']=dict(stage=None,pending=False,status='未入选');row['market_strength']=dict(trend_score=50.,emotion_score=99.,emotion_strong=True,mode='连续竞价')
    s['board_catalog'][0].update(catalog_listed=True,type='theme',member_codes=codes[:8])
    B.attach(s)
    return s,q,p,h,cal,now,evidence

def run(f,previous=None):
    s,q,p,h,cal,now,evidence=f
    E.attach(s,q,p,h,cal,now=now,evidence=evidence,previous=previous,persist=False,fetch=False);E.validate(s)
    return {r['code']:r['emotion_relay'] for r in s['stocks']}

class RelayRules(unittest.TestCase):
    def test_latest_cap_break_and_reseal_update_current_height_without_mutating_history(self):
        f=sample();c=next(iter(f[1]));first=run(f)[c];prior=first['prior_height']
        self.assertEqual(first['height'],prior+1)
        self.assertIn(c,f[0]['emotion_relay']['lists']['sealed'])
        history=copy.deepcopy(first['history'])
        f[1][c]['price']-=.01
        opened=run(f)[c]
        self.assertFalse(opened['sealed']);self.assertEqual(opened['height'],prior)
        self.assertNotIn(c,f[0]['emotion_relay']['lists']['sealed'])
        self.assertTrue(all(c not in p['success_codes'] for p in f[0]['emotion_relay']['promotion']))
        f[1][c]['price']=f[1][c]['limit_up']
        resealed=run(f)[c]
        self.assertEqual(resealed['height'],prior+1)
        self.assertIn(c,f[0]['emotion_relay']['lists']['sealed'])
        self.assertEqual(resealed['history'],history)

    def test_one_price_limit_has_simple_label_and_disappears_after_opening(self):
        f=sample();c=next(iter(f[1]));q=f[1][c]
        for key in ('price','open','high','low'):q[key]=q['limit_up']
        self.assertIn('一字板',run(f)[c]['risks'])
        q['price']-=.01;q['low']=q['price']
        self.assertNotIn('一字板',run(f)[c]['risks'])

    def test_closed_height_and_live_promotion_are_distinct(self):
        f=sample();m=run(f);leader=m[next(iter(m))]
        self.assertEqual(leader['prior_height'],3);self.assertEqual(leader['height'],4)
        self.assertIn('空间高标',leader['roles']);self.assertIn('当前涨停',leader['events'])
        self.assertEqual(f[0]['emotion_relay']['highest_completed'],3);self.assertEqual(f[0]['emotion_relay']['highest_live'],4)

    def test_decimal_tick_rounding_and_unsealed_high_are_not_approximate_caps(self):
        self.assertEqual(D.limit_price(4.05),4.46)
        f=sample();c=list(f[1])[0];f[1][c]['price']-=.01
        m=run(f)[c];self.assertFalse(m['sealed']);self.assertTrue(m['touched']);self.assertIn('触板未封',m['events'])

    def test_unknown_day_breaks_chain_without_becoming_false_or_exact_first_board(self):
        f=sample();c=list(f[1])[0];f[6]['pools'][f[4][-2]]['date_verified']=False
        path=E.chain(c,f[4][-21:],f[4],f[3][c],f[6]);self.assertIsNone(path[-2]['sealed'])
        m=run(f)[c];self.assertFalse(m['height_exact']);self.assertNotIn('首板启动',m['roles']);self.assertNotIn('空间高标',m['roles'])

    def test_raw_history_and_pool_must_match_not_qfq_percentage(self):
        f=sample();c=list(f[1])[0];f[6]['raw'][c]['bars'][-1]['close']-=.01
        m=run(f)[c];self.assertFalse(m['height_exact']);self.assertIn('不一致',m['history_reason'])

    def test_corporate_action_and_historical_st_are_unknown(self):
        for variant in ('corporate','st'):
            f=sample();c=list(f[1])[0]
            if variant=='corporate':f[6]['raw'][c]['bars'][-1]['corporate_action']=True
            else:f[6]['pools'][f[4][-1]]['entries'][c]['name']='ST样例'
            m=run(f)[c];self.assertIsNone(m['prior_height']);self.assertFalse(m['height_exact'])

    def test_nontraded_completed_day_cannot_extend_chain(self):
        f=sample();c=list(f[1])[0];f[3][c][-1]['volume']=0
        self.assertIsNone(run(f)[c]['prior_height'])

    def test_shared_theme_low_board_without_dated_highest_core_node_is_not_continuation(self):
        f=sample();m=run(f);codes=list(m)
        self.assertFalse(m[codes[1]]['continuation'])
        self.assertFalse(m[codes[6]]['continuation'])
        self.assertNotIn('同题材接续候选',m[codes[1]]['roles'])

    def test_failed_core_cannot_authorize_continuation(self):
        f=sample();c=list(f[1])[0];f[1][c]['price']=f[1][c]['last_close']
        self.assertFalse(run(f)[list(f[1])[1]]['continuation'])

    def test_peer_coverage_excludes_self_and_does_not_make_missing_weak(self):
        f=sample();c=list(f[1])[0]
        for q in list(f[1].values())[3:]:q['amount_wan']=q['volume_shou']=0
        m=run(f)[c];rel=m['relations'][0]
        self.assertEqual(rel['expected'],7);self.assertEqual(rel['valid'],2);self.assertFalse(rel['reliable']);self.assertEqual(rel['state'],'联动待核验')
        self.assertFalse(run(sample())[list(f[1])[7]]['eligible'])

    def test_same_height_rivals_and_break_feedback_have_explicit_cohorts(self):
        f=sample();m=run(f);codes=list(m)
        self.assertIn(codes[2],m[codes[0]]['rivals']);self.assertIn('同身位竞争',m[codes[2]]['roles'])
        self.assertTrue(m[codes[4]]['broken_yesterday']);self.assertIn('断板反馈',m[codes[4]]['roles'])
        meta=f[0]['emotion_relay'];self.assertEqual(meta['broken_feedback']['expected'],1)
        self.assertEqual(meta['yesterday_feedback']['expected'],4)

    def test_missing_quote_is_not_counted_as_a_failed_promotion(self):
        f=sample();c=list(f[1])[0];f[1][c]['quote_at']=str(f[5]-timedelta(minutes=11))
        run(f);cohort=f[0]['emotion_relay']['yesterday_feedback']
        self.assertEqual(cohort['expected'],4);self.assertEqual(cohort['valid'],3)

    def test_unknown_chain_height_is_not_counted_as_exact_first_board_promotion(self):
        f=sample();c=list(f[1])[0];f[6]['raw'][c]['bars'][-2]['high']+=.01
        run(f);meta=f[0]['emotion_relay']
        first=next(p for p in meta['promotion'] if p['height']==1)
        self.assertEqual(first['expected'],2);self.assertEqual(meta['promotion_height_pending'],1)

    def test_unknown_quote_basis_and_fake_limit_price_disable_judgment(self):
        for variant in ('source','limit','future','impossible_high'):
            f=sample();c=list(f[1])[0]
            if variant=='source':f[1][c]['price_basis_source']='unverified'
            elif variant=='limit':f[1][c]['limit_up']+=1
            elif variant=='impossible_high':f[1][c]['high']=f[1][c]['limit_up']+.01
            else:f[1][c]['quote_at']=str(f[5]+timedelta(hours=1))
            m=run(f)[c];self.assertFalse(m['valid']);self.assertNotIn(c,f[0]['emotion_relay']['lists']['all'])

    def test_lunch_preserves_source_and_afternoon_rejects_morning_quote(self):
        f=sample();s,q,p,h,c,n,e=f
        for value in q.values():value['quote_at']=str(n.replace(hour=11,minute=30))
        s['session']='午间休市';m=run((s,q,p,h,c,n.replace(hour=12,minute=15),e));self.assertTrue(next(iter(m.values()))['valid'])
        self.assertIn('11:30:00',next(iter(m.values()))['quote_at'])
        s['session']='午盘';m=run((s,q,p,h,c,n.replace(hour=13,minute=10),e));self.assertFalse(next(iter(m.values()))['valid'])

    def test_auction_reference_does_not_generate_relay_events(self):
        f=sample();f[0]['session']='集合竞价';run(f)
        self.assertEqual(f[0]['emotion_relay']['lists']['all'],[]);self.assertEqual(f[0]['emotion_relay']['highest_completed'],3)

    def test_first_five_listing_sessions_cannot_assume_ordinary_limit_regime(self):
        f=sample();c=list(f[1])[0];f[3][c]=f[3][c][-4:]
        m=run(f)[c];self.assertFalse(m['valid']);self.assertFalse(m['sealed'])

    def test_formal_close_confirms_height(self):
        f=sample();s,q,p,h,c,n,e=f;s['session']='已收盘';n=n.replace(hour=15,minute=1)
        for row in s['stocks']:row['market_strength']['mode']='正式收盘'
        for value in q.values():value['quote_at']=str(n.replace(minute=0))
        m=run((s,q,p,h,c,n,e));leader=next(iter(m.values()))
        self.assertEqual(leader['completed_height'],4);self.assertIn('收盘封板',leader['events']);self.assertEqual(s['emotion_relay']['mode'],'正式收盘')
        self.assertEqual(s['emotion_relay']['highest_previous'],3);self.assertEqual(s['emotion_relay']['highest_completed'],4)

    def test_sampling_events_are_timestamped_not_full_intraday_claims(self):
        f=sample();run(f);prior=copy.deepcopy(f[0]);c=list(f[1])[0]
        now=f[5]+timedelta(minutes=2)
        for q in f[1].values():q['quote_at']=str(now)
        f[1][c]['price']-=.1;m=run((*f[:5],now,f[6]),previous=prior)[c]
        self.assertIn('采样观察到开板',m['events']);self.assertNotIn('开板次数',m)

    def test_future_daily_bars_do_not_change_relay_results(self):
        f=sample();before=copy.deepcopy(run(f))
        for bars in f[3].values():bars.append(dict(bars[-1],date='2099-01-01',close=9999.))
        self.assertEqual(before,run(f))

    def test_mainboard_scope_is_explicit_and_not_unknown_code_fallback(self):
        for c in ('920298','300001','688001','999999'):self.assertFalse(D.mainboard(c),c)
        self.assertTrue(D.mainboard('600001'));self.assertTrue(D.mainboard('000995'))

    def test_ma_and_original_scores_are_unchanged_and_full_members_retained(self):
        f=sample();before=[(copy.deepcopy(r['ma_trend']),copy.deepcopy(r['market_strength'])) for r in f[0]['stocks']]
        run(f);self.assertEqual(before,[(r['ma_trend'],r['market_strength']) for r in f[0]['stocks']])
        rank=f[0]['emotion_relay']['rankings']['all'];self.assertEqual(len(rank['all']),20);self.assertEqual(set(rank['emotion']),set(f[1]))
        self.assertEqual(rank['trend'],f[0]['stock_board_ranking']['all']['trend'])

    def test_whole_market_generic_theme_is_not_enough_for_continuation(self):
        f=sample();f[0]['board_catalog'][0]['member_codes']=list(f[1])
        B.attach(f[0])
        m=run(f);self.assertFalse(m[list(f[1])[1]]['continuation'])

    def test_shared_csv_keeps_role_height_and_same_generation(self):
        f=sample();run(f);f[0]['ui_generation']='relay-fixed-generation'
        request=json.dumps(dict(rows=f[0]['stocks'],data=f[0],contexts=dict(view='emotion')),ensure_ascii=False)
        result=subprocess.run(['node','csv_export.js'],input=request,capture_output=True,text=True,encoding='utf-8',check=True)
        import csv,io
        r=next(csv.DictReader(io.StringIO(result.stdout.lstrip('\ufeff'))));self.assertEqual(r['昨日完成板位'],'3');self.assertEqual(r['当前板位'],'4');self.assertEqual(r['UI版本'],'relay-fixed-generation')
        self.assertIn('空间高标',r['接力角色']);self.assertNotIn('成功概率',r)

    def test_direction_export_reads_same_generation_relay_facts(self):
        f=sample();run(f)
        import csv,io
        with tempfile.TemporaryDirectory() as directory:
            page=Path(directory)/'dashboard.html';packet,token=ui_payload.prepare(f[0],'var DATA = /*__DATA__*/null',page)
            text=ui_payload.export_board_csv(token,[f[0]['board_catalog'][0]['id']],page).decode('utf-8-sig')
            row=next(csv.DictReader(io.StringIO(text)))
            self.assertEqual(row['当前在板数'],'3');self.assertEqual(row['UI版本'],token)
            self.assertEqual(row['接力规则'],E.VERSION);self.assertNotIn('情绪分',row)

class Acquisition(unittest.TestCase):
    def test_partial_duplicate_and_wrong_date_pool_never_validate(self):
        for value in (dict(rc=0,data=dict(tc=2,pool=[dict(c='600001',p=11000)])),dict(rc=0,data=dict(tc=2,pool=[dict(c='600001',p=11000)]*2))):
            with patch.object(D.D,'em_get',return_value=json.dumps(value)):
                with self.assertRaises(ValueError):D.fetch_pool('2026-10-12')

    def test_request_date_is_cross_checked_by_raw_price_not_qdate(self):
        day='2026-10-12';pool=dict(day=day,entries={'600001':dict(name='A',price=11.)},total=1,provider_market_date=20261015)
        for close,expected in ((11.,True),(12.,False)):
            raw=dict(bars=[dict(date=day,open=10.,close=close,high=close,low=10.,volume=100,price_basis='raw',price_basis_source='tencent_day')])
            with tempfile.TemporaryDirectory() as d,patch.object(config,'CACHE_DIR',Path(d)):
                D.write(D.root()/'pools'/(day+'.json'),pool);D.write(D.root()/'raw'/'600001.json',raw)
                result=D.load([day],fetch=False)
                self.assertEqual(result['pools'][day]['date_verified'],expected)

if __name__=='__main__':unittest.main()
