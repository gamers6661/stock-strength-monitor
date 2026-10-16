"""Independent styles, real THS intersection and honest quote-change evidence."""
import copy
import unittest
from datetime import datetime,timedelta
import direction_changes as D
import market_strength as M
import board_stock_rank as B
from test_market_strength import fixture,run
from test_market_strength_integration import render


class PageRoles(unittest.TestCase):
    def setUp(self):
        self.f=fixture(8)
        for q in self.f[1].values():q.update(price=110,high=110,low=100,open=100,change_pct=10)
        run(self.f);self.s=self.f[0]
        codes=list(self.f[1]);self.codes=codes
        for i,c in enumerate(codes):
            m=self.s['stocks'][i]['market_strength']
            m.update(trend_score=80-i if i<5 else 40,emotion_score=90-i if i>=3 else 30,
                trend_strong=i<5,emotion_strong=i>=3,focus=True,dominant_period=5)
            self.s['stocks'][i]['ma_trend']=dict(stage=5 if i<5 else None,eligible=i<5,pending=False,status='守线观察',stage_label='MA5初期推进' if i<5 else '暂无合格阶段',valid_until='2099-01-01 00:00:00')
        models={r['code']:r['market_strength'] for r in self.s['stocks']}
        self.s['market_strength']['stocks']=M.lists(models)
        self.s['board_catalog'].extend([
            dict(id='industry:a',name='行业甲',type='industry',member_codes=codes[:4]),
            dict(id='industry:b',name='行业乙',type='industry',member_codes=codes[4:]),
            dict(id='theme:a',name='题材甲',type='theme',member_codes=codes[2:6]),
            dict(id='theme:b',name='题材乙',type='theme',member_codes=codes[6:])])
        for b in self.s['board_catalog']:b['catalog_listed']=True
        B.attach(self.s)

    def test_complete_member_default_and_independent_qualification(self):
        t=render(self.s,"msRender('stocks');")['els']['ms-stock-host']['innerHTML']
        e=render(self.s,"MS_VIEW.stocks.scope='emotion';msRender('stocks');")['els']['ms-stock-host']['innerHTML']
        self.assertIn(self.codes[0],t);self.assertIn('data-strength-id="'+self.codes[7]+'"',t)
        self.assertIn('data-strength-id="'+self.codes[7]+'"',e);self.assertNotIn('data-strength-id="'+self.codes[0]+'"',e)
        for c in self.codes[3:5]:
            self.assertIn('data-strength-id="'+c+'"',t);self.assertIn('data-strength-id="'+c+'"',e)
        all_rows=render(self.s,"msStockAll(true);")['els']['ms-stock-host']['innerHTML']
        self.assertEqual(all_rows.count('data-strength-id='),8)

    def test_merged_same_type_union_cross_type_intersection(self):
        action="MS_VIEW.stocks.scope='focus';MS_VIEW.stocks.industryIds=['industry:a','industry:b'];MS_VIEW.stocks.themeIds=['theme:a'];MS_VIEW.stocks.rankBoardId='theme:a';msRender('stocks');"
        r=render(self.s,action)
        self.assertEqual(set(r['ids']),set(self.codes[2:6]))
        html=r['els']['ms-stock-host']['innerHTML']
        self.assertIn('匹配方向：',html);self.assertIn('题材甲',html)
        r=render(self.s,"MS_VIEW.stocks.industryIds=['industry:a'];MS_VIEW.stocks.themeIds=['theme:a'];msRender('stocks');")
        self.assertEqual(set(r['ids']),set(self.codes[2:4]))

    def test_merged_both_and_all_members_do_not_mix_eligibility(self):
        r=render(self.s,"MS_VIEW.stocks.scope='both';msRender('stocks');")
        self.assertEqual(set(r['ids']),set(self.codes[3:5]))
        r=render(self.s,"MS_VIEW.stocks.scope='emotion';MS_VIEW.stocks.themeIds=['theme:a'];msRender('stocks');")
        self.assertEqual(set(r['ids']),set(self.codes[3:6]))
        r=render(self.s,"MS_VIEW.stocks.scope='emotion';MS_VIEW.stocks.themeIds=['theme:a'];msStockAll(true);")
        self.assertEqual(set(r['ids']),set(self.codes[2:6]))

    def test_unknown_member_selection_does_not_fall_back_to_universe(self):
        r=render(self.s,"MS_VIEW.stocks.themeIds=['theme:unknown'];msRender('stocks');")
        self.assertEqual(r['ids'],[])

    def test_switching_axes_keeps_all_filters_and_csv_order(self):
        action="MS_VIEW.stocks.themeIds=['theme:a'];MS_VIEW.stocks.scope='both';MS_VIEW.stocks.phase='';MS_VIEW.stocks.q='600';msStockAxis('emotion');msCSV('stocks');"
        r=render(self.s,action)
        self.assertEqual(r['view']['themeIds'],['theme:a']);self.assertEqual(r['view']['scope'],'both')
        self.assertEqual(r['view']['q'],'600');self.assertEqual(r['exported'],r['ids'])
        self.assertEqual(set(r['ids']),set(self.codes[3:5]))

    def test_direction_deep_link_opens_stock_page_and_expected_axis(self):
        r=render(self.s,"msOpenStocks('industry:a','emotion');")
        self.assertEqual(r['pane'],'stocks');self.assertEqual(r['view']['axis'],'emotion')
        self.assertEqual(set(r['ids']),set(self.codes[:4]));self.assertEqual(r['view']['scope'],'all')
        r=render(self.s,"pickBoardMembers('industry:a');")
        self.assertEqual(r['pane'],'stocks');self.assertEqual(r['view']['scope'],'all')
        self.assertEqual(set(r['ids']),set(self.codes[:4]))
        r=render(self.s,"MS_VIEW.stocks.themeIds=['theme:a'];msClearDirections();")
        self.assertEqual(set(r['ids']),set(self.codes))

    def test_overview_has_direction_sections_not_stock_leaderboards(self):
        s=copy.deepcopy(self.s);s['board_catalog']=s['board_catalog'][:1]
        html=render(s,'renderOverview();')['els']['ms-overview-host']['innerHTML']
        for word in ('市场温度','正在转强','趋势集中方向','情绪集中方向','行业','题材'):self.assertIn(word,html)
        self.assertNotIn('趋势领先',html);self.assertNotIn('情绪领先',html)
        self.assertNotIn('data-strength-id=',html)


class DirectionChanges(unittest.TestCase):
    def test_after_close_supplier_clock_does_not_erase_verified_closing_batch(self):
        f=fixture(8);s,q,p,h,c,now=f
        at=now.replace(hour=15,minute=1)
        s['session']='已收盘';s['quote_capture_at']=str(at)
        for quote in q.values():quote.update(quote_at=str(at),ts=str(at),price=110.,high=110.,low=100.,change_pct=10.)
        M.attach(s,q,p,h,c,now=at)
        before=copy.deepcopy(s);self.assertTrue(before['market_strength']['counts']['focus'])
        later=at.replace(minute=47)
        s['close_daily_verified_at']=str(later);s['quote_capture_at']=str(later)
        for quote in q.values():quote['quote_at']=str(later);quote['ts']=str(later)
        M.attach(s,q,p,h,c,now=later,previous=before)
        self.assertEqual(s['market_strength']['counts'],before['market_strength']['counts'])
        self.assertEqual(s['direction_changes']['source_at'],str(at))
        self.assertTrue(all(r['market_strength']['quote_at']==str(at) for r in s['stocks']))
        # A previous day's batch cannot repair today's invalid quotes.
        bad=copy.deepcopy(before);bad['market_strength_close_input']['day']='2000-01-01'
        M.attach(s,q,p,h,c,now=later,previous=bad)
        self.assertEqual(s['market_strength']['counts']['focus'],0)

    def test_reference_keeps_original_comparison_without_new_observation(self):
        previous={'market_strength':{'implementation_hash':M.IMPLEMENTATION_HASH},'direction_observations':[{'at':'2026-10-13 10:00:00'}],
                  'direction_changes':{'source_at':'2026-10-13 10:00:00','items':[{'id':'test'}]}}
        snap={}
        D.attach(snap,previous,{}, {},[],{}, {},datetime(2026,10,14,8),reference=True,parameters=M.P,implementation_hash=M.IMPLEMENTATION_HASH)
        self.assertEqual(snap['direction_changes'],previous['direction_changes'])
        self.assertEqual(snap['direction_observations'],previous['direction_observations'])

    def test_large_drop_is_visible_even_without_old_intraday_flags(self):
        from test_owner_strength_rebuild import prices
        f=fixture();c=next(iter(f[1]));prices(f,c,[100+i*1.2 for i in range(20)],112.975)
        # Quote has a real large drop, independent of saved flags.
        f[1][c]['change_pct']=-8;f[0]['stocks'][0]['intraday_risk_flags']=[]
        m=run(f)[c]
        self.assertIn('大幅下跌',m['risks']);self.assertIn('明显回落',m['labels']);self.assertNotIn('趋势推进',m['labels'])
    def sample(self,at,gain,score,previous=None,members=None):
        codes=['600%03d'%i for i in range(8)]
        stocks={c:dict(quote_at=str(at),trend_score=score,emotion_score=score,trend_strong=score>=65,
            emotion_strong=score>=65,phase=None,events=[],risks=[],trend_parts_by_period={},history_trend=[]) for c in codes}
        board=dict(id='theme:a',name='题材甲',type='theme',member_codes=members or codes)
        models={'theme:a':dict(expected_codes=codes,trend_score=score,emotion_score=score)}
        quotes={c:dict(quote_at=str(at),price=100+gain,change_pct=gain) for c in codes}
        rows={c:dict(code=c,market_strength=m) for c,m in stocks.items()}
        snap=dict(stocks=list(rows.values()),coverage_catalog=[],market_strength={'implementation_hash':M.IMPLEMENTATION_HASH})
        D.attach(snap,previous,stocks,models,[board],rows,quotes,at,reference=False,parameters=M.P,implementation_hash=M.IMPLEMENTATION_HASH)
        return snap,models

    def test_first_sample_has_no_invented_change(self):
        s,_=self.sample(datetime(2026,10,13,10),3,70)
        self.assertIsNone(s['direction_changes']['from_at']);self.assertEqual(s['direction_changes']['items'],[])

    def test_new_strength_requires_price_and_breadth_evidence(self):
        a,_=self.sample(datetime(2026,10,13,9,45),1,60)
        b,models=self.sample(datetime(2026,10,13,10),3,70,a)
        self.assertEqual(len(b['direction_changes']['items']),2)
        for r in b['direction_changes']['items']:
            self.assertEqual(r['kind'],'新进入强势');self.assertEqual(r['return_delta_pp'],2);self.assertEqual(r['share_delta_pp'],100)
        self.assertEqual(models['theme:a']['direction_change']['common_count'],8)
        b,_=self.sample(datetime(2026,10,13,10),1,70,a)
        self.assertEqual(b['direction_changes']['items'],[])

    def test_same_quote_does_not_advance_clock_or_accumulate_samples(self):
        a,_=self.sample(datetime(2026,10,13,9,45),1,60)
        b,_=self.sample(datetime(2026,10,13,9,45),2,70,a)
        self.assertEqual(len(b['direction_observations']),1)
        self.assertIsNone(b['direction_changes']['from_at'])

    def test_cross_day_membership_version_and_old_baseline_are_rejected(self):
        now=datetime(2026,10,13,10)
        for old_time in (now-timedelta(days=1),now-timedelta(minutes=40)):
            a,_=self.sample(old_time,1,60);b,_=self.sample(now,3,70,a)
            self.assertEqual(b['direction_changes']['items'],[])
        a,_=self.sample(now-timedelta(minutes=15),1,60)
        b,_=self.sample(now,3,70,a,members=['600000'])
        self.assertEqual(b['direction_changes']['items'],[])
        a['direction_observations'][0]['version']='old';b,_=self.sample(now,3,70,a)
        self.assertEqual(b['direction_changes']['items'],[])

    def test_missing_majority_does_not_claim_turning(self):
        a,_=self.sample(datetime(2026,10,13,9,45),1,60)
        a['direction_observations'][0]['stocks']={'600000':a['direction_observations'][0]['stocks']['600000']}
        b,_=self.sample(datetime(2026,10,13,10),3,70,a)
        self.assertEqual(b['direction_changes']['items'],[])


if __name__=='__main__':unittest.main()
