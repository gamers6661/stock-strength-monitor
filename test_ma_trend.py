"""Business boundaries of strong-origin three-stage MA observation."""
import copy
import json
import subprocess
import unittest
from datetime import datetime,timedelta
from pathlib import Path
from unittest.mock import patch

import intraday
import ma_trend as T
from test_market_strength import fixture


def sample(kind='initial'):
    s,q,p,h,cal,now=fixture(1)
    code=next(iter(q));bars=h[code]
    def put(i,c,volume=100):
        op=bars[i-1]['close'];bars[i].update(open=op,close=c,high=max(op,c)+.2,low=min(op,c)-.2,volume=volume)
    if kind=='initial':put(len(bars)-1,105,250)
    elif kind=='retained':
        start=len(bars)-13;put(start,105,250)
        for i in range(start+1,len(bars)):put(i,bars[i-1]['close']+.35)
    elif kind=='ma10':
        start=len(bars)-12
        for j,c in enumerate([105,108,110,112,113,112.4,112.4,112.4,112.4,112.4,112.4,112.45]):put(start+j,c,250 if j==0 else 70 if j<5 else 40)
    elif kind=='ma20':
        start=len(bars)-22
        for j,c in enumerate([105,110,115,121]+[120.6]*15+[120.5,120.55,120.5]):put(start+j,c,250 if j==0 else 70 if j<4 else 40)
        bars[start+4]['low']=119.7
    last=bars[-1]['close'];price=last+.1
    q[code].update(last_close=last,price=price,open=last,high=price+.2,low=last-.2,
                   change_pct=100*(price/last-1),limit_up=last*1.1)
    if kind=='ma20':q[code].update(price=120.42,open=120.5,high=120.8,low=120.42,change_pct=100*(120.42/120.5-1))
    return s,q,p,h,cal,now


def run(f,previous=None,minutes=None):
    s,q,p,h,c,n=f
    T.attach(s,q,p,h,c,now=n,previous=previous,minute_data=minutes or {},fetch_minutes=False)
    T.validate(s)
    return s['stocks'][0]['ma_trend']


def rebound_minutes(f):
    code=next(iter(f[1]));q=f[1][code]
    ctx=intraday.align_price_basis(q,f[3][code],f[4],observation_day=f[5].date().isoformat())
    setup=T.daily(f[3][code],f[4]);n=setup['stage']
    line=setup['platform']['low'] if n==20 else ctx['thresholds'][n]
    low=line+.02;price=max(q['price'],low+.35*ctx['atr20'])
    q.update(price=price,high=max(q['high'],price+.1),low=low)
    bars=[];t=f[5].replace(hour=9,minute=31,second=0)
    while t<=f[5]:
        touch=t.strftime('%H:%M')=='09:55';value=low+.01 if touch else price
        bars.append(dict(at=str(t)[:16],open=value,close=value,high=value+.01,low=low if touch else value-.01,
                         price_basis='raw',price_basis_source='sina_1m_unadjusted',source='新浪1分钟OHLC'))
        t+=timedelta(minutes=1)
    return {code:bars}


class MAStages(unittest.TestCase):
    def test_supplied_price_context_reuses_same_quote_without_changing_results(self):
        f=sample();baseline=run(copy.deepcopy(f));s,q,p,h,cal,now=f;code=next(iter(q))
        context=intraday.align_price_basis(q[code],h[code],cal,observation_day=str(now.date()))
        supplied={code:copy.deepcopy(context)}
        with patch.object(T,'live',wraps=T.live) as live,patch.object(intraday,'align_price_basis',wraps=intraday.align_price_basis) as align:
            T.attach(s,q,p,h,cal,now=now,contexts=supplied,minute_data={},fetch_minutes=False)
        self.assertIs(live.call_args.args[-1],supplied[code])
        align.assert_not_called()
        self.assertEqual(s['stocks'][0]['ma_trend'],baseline)
        self.assertEqual(supplied,{code:context})

    def test_context_from_an_earlier_quote_is_recomputed(self):
        f=sample();s,q,p,h,cal,now=f;code=next(iter(q))
        context=intraday.align_price_basis(q[code],h[code],cal,observation_day=str(now.date()))
        context['quote_at']=str(now-timedelta(minutes=1))
        with patch.object(intraday,'align_price_basis',wraps=intraday.align_price_basis) as align:
            T.attach(s,q,p,h,cal,now=now,contexts={code:context},minute_data={},fetch_minutes=False)
        self.assertTrue(align.called)

    def test_above_ma5_without_strong_origin_is_not_selected(self):
        f=fixture(1);m=run(f);self.assertFalse(m['eligible']);self.assertIsNone(m['origin'])

    def test_small_initial_gain_with_real_impulse_is_selected(self):
        m=run(sample());self.assertTrue(m['eligible']);self.assertEqual(m['stage'],5)
        self.assertIn('放量上攻',m['origin']['kind']);self.assertLess(m['origin']['day_return_pct'],6)

    def test_volume_missing_does_not_pass_impulse(self):
        f=sample();f[3][next(iter(f[3]))][-1]['volume']=None
        m=run(f);self.assertFalse(m['eligible']);self.assertIsNone(m['origin'])

    def test_origin_older_than_five_days_remains_while_support_holds(self):
        f=sample('retained');m=run(f);self.assertTrue(m['eligible']);self.assertEqual(m['stage'],5)
        self.assertLess(m['origin']['date'],f[4][-5])

    def test_ma10_bottom_rebound_without_platform_top_breakout(self):
        f=sample('ma10');minutes=rebound_minutes(f);m=run(f,minutes=minutes);self.assertEqual(m['stage'],10);self.assertTrue(m['eligible'])
        self.assertIn('底部反弹',m['events']);self.assertLess(m['price'],m['platform']['high'])

    def test_ma20_horizontal_rebound_can_be_below_ma5(self):
        f=sample('ma20');minutes=rebound_minutes(f);m=run(f,minutes=minutes);self.assertEqual(m['stage'],20);self.assertTrue(m['eligible'])
        ctx=intraday.align_price_basis(f[1][next(iter(f[1]))],f[3][next(iter(f[3]))],f[4],observation_day=f[5].date().isoformat())
        self.assertLess(m['price'],ctx['thresholds'][5]);self.assertIn('底部反弹',m['events'])
        self.assertLess(m['price'],m['ma_value']);self.assertEqual(m['support_price'],m['platform']['low'])
        self.assertEqual(m['support_basis'],'MA20与平台双支撑')

    def test_small_low_volatility_impulse_is_not_strong(self):
        f=sample();b=f[3][next(iter(f[3]))][-1];b.update(close=102.,high=102.2)
        q=f[1][next(iter(f[1]))];q.update(price=102.1,last_close=102.,open=102.,high=102.3,low=101.9)
        m=run(f);self.assertFalse(m['eligible']);self.assertIsNone(m['origin'])

    def test_price_breakout_with_low_volume_is_not_confirmed(self):
        f=sample();f[3][next(iter(f[3]))][-1]['volume']=110
        m=run(f);self.assertFalse(m['eligible']);self.assertIsNone(m['origin'])

    def test_two_day_impulse_can_start_before_large_total_gain(self):
        f=sample();bars=f[3][next(iter(f[3]))]
        bars[-2].update(close=103.1,high=103.3,low=99.8)
        bars[-1].update(open=103.1,close=106.5,high=106.7,low=102.9)
        root=T.origin(bars,len(bars)-1)
        self.assertIn('放量上攻',root['kind']);self.assertLess(root['day_return_pct'],4.)
        self.assertGreaterEqual(root['two_day_return_pct'],6.)

    def test_intraday_price_breakout_waits_for_completed_volume(self):
        f=fixture(1);q=f[1][next(iter(f[1]))]
        q.update(price=104.,open=100.,high=104.1,low=100.,change_pct=4.)
        m=run(f);self.assertFalse(m['eligible']);self.assertTrue(m['startup_pending'])
        self.assertEqual(m['status'],'启动待确认')

    def test_ma20_previous_rise_must_reach_twenty_percent(self):
        f=sample('ma20');bars=f[3][next(iter(f[3]))]
        for b in bars[-22:]:
            for k in ('open','close','high','low'):b[k]=100+(b[k]-100)*.65
        setup=T.daily(bars,f[4]);self.assertIsNotNone(setup['origin']);self.assertNotEqual(setup['stage'],20)

    def test_ma20_previous_rise_must_also_reach_four_atr(self):
        f=sample('ma20');bars=f[3][next(iter(f[3]))]
        for b in bars[:-22]:b.update(high=104.,low=96.)
        bars[-22].update(close=112.,high=112.2)
        setup=T.daily(bars,f[4]);self.assertIsNotNone(setup['origin']);self.assertNotEqual(setup['stage'],20)

    def test_platform_floor_failure_does_not_exit_while_ma20_still_holds(self):
        f=sample('ma20');bars=f[3][next(iter(f[3]))]
        for b in bars[:-19]:b.update(open=100.,close=100.,high=100.5,low=99.5,volume=100.)
        for j,b in enumerate(bars[-19:]):
            close=[105.,110.,115.,121.][j] if j<4 else 120.6
            b.update(open=100. if j==0 else bars[-19+j-1]['close'],close=close,
                     high=max(close,100. if j==0 else bars[-19+j-1]['close'])+.2,
                     low=min(close,100. if j==0 else bars[-19+j-1]['close'])-.2,
                     volume=250. if j==0 else 70. if j<4 else 40.)
            if j>=4:b.update(high=123.,low=119.5)
        q=f[1][next(iter(f[1]))];q.update(last_close=120.6,price=119.4,open=120.6,high=123.,low=119.3)
        m=run(f);self.assertEqual(m['stage'],20);self.assertGreater(m['price'],m['ma_value'])
        self.assertGreater(m['price'],m['support_price']);self.assertTrue(m['eligible'])

    def test_new_wick_does_not_lower_locked_platform_floor(self):
        f=sample('ma20');bars=f[3][next(iter(f[3]))];before=T.daily(bars,f[4])
        day=f[5].date().isoformat();extra=dict(bars[-1],date=day,low=119.2,close=120.6)
        after=T.daily(bars+[extra],f[4]+[day]);self.assertEqual(after['stage'],20)
        self.assertEqual(after['platform']['low'],before['platform']['low'])
        self.assertEqual(after['platform']['formed_at'],before['platform']['formed_at'])

    def test_missing_last_session_still_checks_real_last_close_comparability(self):
        f=sample();f[3][next(iter(f[3]))].pop();m=run(f)
        self.assertFalse(m['eligible']);self.assertEqual(m['status'],'价格口径待核验')
        self.assertTrue(m['history_observation']['suspension_days'])

    def test_stale_quote_cannot_enter_current_observation(self):
        f=sample();f[1][next(iter(f[1]))]['quote_at']=str(f[5]-timedelta(minutes=11))
        m=run(f);self.assertFalse(m['eligible']);self.assertTrue(m['pending']);self.assertIn('过期',m['reason'])

    def test_yesterdays_daily_bounce_is_not_a_current_rebound(self):
        m=run(sample('ma10'));self.assertEqual(m['stage'],10)
        self.assertIsNone(m['rebound']);self.assertNotIn('底部反弹',m['events'])

    def test_old_intraday_bounce_is_not_restamped_as_current(self):
        f=sample('ma20');data=rebound_minutes(f);run(f,minutes=data);prior=copy.deepcopy(f[0]);code=next(iter(f[1]))
        now=f[5]+timedelta(minutes=25);q=f[1][code];q.update(price=120.9,high=121.,quote_at=str(now))
        t=f[5]+timedelta(minutes=1)
        while t<=now:
            data[code].append(dict(data[code][-1],at=str(t)[:16],open=120.9,close=120.9,high=121.,low=120.89))
            t+=timedelta(minutes=1)
        m=run((*f[:5],now),previous=prior,minutes=data)
        self.assertTrue(m['eligible']);self.assertIsNone(m['rebound']);self.assertNotIn('底部反弹',m['events'])
        self.assertEqual(m['last_rebound']['at'],prior['stocks'][0]['ma_trend']['rebound']['at'])

    def test_failed_ma20_persists_until_a_new_completed_close_supersedes_minutes(self):
        f=sample('ma20');data=rebound_minutes(f);code=next(iter(f[1]));floor=T.daily(f[3][code],f[4])['platform']['low']
        for b in data[code]:
            if '09:40'<=b['at'][11:16]<'10:00':b.update(open=floor-.1,close=floor-.1,high=floor-.09,low=floor-.11)
        f[1][code]['low']=floor-.11;m=run(f,minutes=data)
        self.assertEqual(m['status'],'已退出');prior=copy.deepcopy(f[0])
        later=f[5]+timedelta(minutes=1);f[1][code].update(quote_at=str(later),price=120.5)
        again=run((*f[:5],later),previous=prior,minutes=data)
        self.assertEqual(again['status'],'已退出');self.assertEqual(again['exit_at'],m['exit_at'])
        f[1][code]['quote_at']=str(later-timedelta(minutes=20))
        missing=run((*f[:5],later),previous=prior,minutes=data);self.assertTrue(missing['pending'])
        gap_prior=copy.deepcopy(f[0]);f[1][code]['quote_at']=str(later)
        restored=run((*f[:5],later),previous=gap_prior,minutes=data)
        self.assertEqual(restored['status'],'已退出');self.assertEqual(restored['exit_at'],m['exit_at'])
        bars=f[3][code];day=f[5].date().isoformat();bars.append(dict(bars[-1],date=day))
        next_day=f[5]+timedelta(days=1);f[1][code].update(quote_at=str(next_day),last_close=bars[-1]['close'],low=120.3)
        again=run((*f[:4],f[4]+[day],next_day),previous=prior)
        self.assertNotEqual(again['status'],'已退出');self.assertEqual(again['stage'],20)
        self.assertIsNone(again['exit_at'])

    def test_expired_browser_snapshot_does_not_show_current_candidates(self):
        from test_market_strength_integration import render
        f=sample();run(f)
        out=render(f[0],"sessionNow=function(){return '午盘'};MS_VIEW.radar.scope='trend';mtRender();")
        self.assertNotIn('data-strength-id=',out['els']['ma-radar-host']['innerHTML'])

    def test_later_platform_breakout_is_a_separate_progress_event(self):
        f=sample('ma10');run(f);previous=copy.deepcopy(f[0]);code=next(iter(f[1]))
        f[1][code].update(price=115.,high=115.1,low=112.5,quote_at=str(f[5]+timedelta(minutes=1)))
        f=(*f[:5],f[5]+timedelta(minutes=1));m=run(f,previous=previous)
        self.assertFalse(m['eligible']);self.assertTrue(m['advance']);self.assertIn('平台上沿突破',m['events'])
        self.assertEqual(m['status'],'平台突破·推进延续')

    def test_continuous_fall_to_ma20_not_horizontal_restart(self):
        f=sample('ma20');bars=f[3][next(iter(f[3]))]
        for j,b in enumerate(bars[-5:]):b.update(open=110-j*.5,close=109.8-j*.5,high=110.2-j*.5,low=109.6-j*.5)
        self.assertNotEqual(T.daily(bars,f[4])['stage'],20)

    def test_serious_ma5_break_downgrades_without_score_override(self):
        f=sample();code=next(iter(f[1]));ctx=intraday.align_price_basis(f[1][code],f[3][code],f[4],observation_day=f[5].date().isoformat())
        line=ctx['thresholds'][5];f[1][code].update(price=line-.6*ctx['atr20'],low=line-ctx['atr20'],high=106.)
        f[0]['stocks'][0]['market_strength']={'trend_score':99,'trend_strong':True}
        m=run(f);self.assertEqual(m['stage'],10);self.assertNotEqual(m['status'],'已退出')
        prior=copy.deepcopy(f[0]);again=run(f,previous=prior)
        self.assertEqual(again['stage'],10);self.assertIsNone(again['exit_at'])

    def test_missing_minutes_never_prove_timed_exit(self):
        f=sample();code=next(iter(f[1]));ctx=intraday.align_price_basis(f[1][code],f[3][code],f[4],observation_day=f[5].date().isoformat())
        line=ctx['thresholds'][5];f[1][code].update(price=line-.1*ctx['atr20'],low=line-.2*ctx['atr20'],high=106.)
        m=run(f);self.assertFalse(m['eligible']);self.assertTrue(m['pending']);self.assertIsNone(m['exit_at'])

    def test_history_gap_is_suspension_and_actual_bars_continue(self):
        f=sample();f[3][next(iter(f[3]))].pop(-8);m=run(f);self.assertFalse(m['pending'])
        self.assertEqual(len(m['history_observation']['suspension_days']),1)

    def test_auction_does_not_make_new_origin(self):
        f=sample();f[0]['session']='集合竞价';m=run(f);self.assertFalse(m['eligible']);self.assertIsNone(m['origin'])

    def test_lunch_uses_verified_preserved_quote_clock_not_supplier_new_time(self):
        f=sample();s,q,p,h,c,n=f;code=next(iter(q));saved=dict(q[code],quote_at=n.date().isoformat()+' 11:30:00')
        s['stocks'][0].update(saved);s['stocks'][0]['market_strength']={'quote_at':saved['quote_at'],'price_context':{'valid':True},'mode':'午休参考'}
        q[code]['quote_at']=n.date().isoformat()+' 12:20:00';s['session']='午间休市'
        m=run((s,q,p,h,c,n.replace(hour=12,minute=20)))
        self.assertTrue(m['eligible']);self.assertEqual(m['quote_at'],saved['quote_at'])

    def test_future_daily_bar_is_not_used(self):
        f=sample();before=run(copy.deepcopy(f));bars=f[3][next(iter(f[3]))]
        bars.append(dict(bars[-1],date=f[5].date().isoformat(),close=500,high=500,low=100,open=100))
        after=run(f);self.assertEqual(before['origin'],after['origin']);self.assertEqual(before['support_price'],after['support_price'])

    def test_verified_close_uses_todays_completed_impulse(self):
        f=fixture(1);s,q,p,h,c,n=f;code=next(iter(q));day=n.date().isoformat()
        h[code].append(dict(h[code][-1],date=day,open=100.,close=105.,high=105.2,low=99.8,volume=250.))
        c.append(day);q[code].update(price=105.,last_close=100.,open=100.,high=105.2,low=99.8,change_pct=5.,quote_at=day+' 15:00:00')
        s['session']='已收盘';s['stocks'][0]['market_strength']={'mode':'正式收盘'}
        f=(s,q,p,h,c,n.replace(hour=15,minute=30));m=run(f)
        self.assertEqual(m['origin']['date'],day);self.assertEqual(m['origin']['basis'],'完成日量价')
        self.assertTrue(m['eligible']);self.assertEqual(m['entry_at'],day+' 15:00:00')
        self.assertNotIn('minute_needed',m)

    def test_csv_contains_same_stage_support_and_full_evidence(self):
        f=sample();m=run(f);s=f[0];s['ui_generation']='verified-generation'
        code="const fs=require('fs'),vm=require('vm');const q=JSON.parse(fs.readFileSync(0,'utf8'));const c={};vm.createContext(c);vm.runInContext(fs.readFileSync('csv_export.js','utf8'),c);process.stdout.write(c.buildStockCSV(q.stocks,q,{}));"
        result=subprocess.run(['node','-e',code],input=json.dumps(s),text=True,capture_output=True,check=True)
        import csv,io
        row=next(csv.DictReader(io.StringIO(result.stdout.lstrip('\ufeff'))))
        self.assertEqual(row['均线阶段'],m['stage_label']);self.assertEqual(float(row['本阶段支撑触线价']),m['support_price'])
        self.assertEqual(json.loads(row['完整均线依据']),m)

    def test_page_displays_three_independent_stage_sections_and_backend_ids(self):
        from test_market_strength_integration import render
        f=sample();m=run(f);out=render(f[0],"MS_VIEW.radar.scope='trend';mtRender();");html=out['els']['ma-radar-host']['innerHTML']
        self.assertIn('data-strength-id="'+m['code']+'"',html)
        for n in (5,10,20):self.assertIn('data-ma-section="'+str(n)+'"',html)
        self.assertIn('MA5有效失守转MA10',html);self.assertIn(m['origin']['kind'],html)

    def test_stage_filter_does_not_select_wrong_stage(self):
        from test_market_strength_integration import render
        f=sample();run(f);out=render(f[0],"MS_VIEW.radar.scope='trend';MS_VIEW.radar.phase='10';mtRender();")
        self.assertNotIn('data-strength-id=',out['els']['ma-radar-host']['innerHTML'])


class MinuteSupport(unittest.TestCase):
    def inputs(self,breach='09:45',reclaim=None,gap=False):
        f=sample();q=f[1][next(iter(f[1]))];ctx=intraday.align_price_basis(q,f[3][next(iter(f[3]))],f[4],observation_day=f[5].date().isoformat())
        line=ctx['thresholds'][5];ctx['support']=line;day=f[5].date().isoformat();bars=[]
        t=datetime.fromisoformat(day+' 09:31')
        while t<=f[5]:
            hm=t.strftime('%H:%M');lost=hm>=breach and (not reclaim or hm<reclaim)
            value=line-.1 if lost else line+.2
            if not gap or hm!='09:50':bars.append(dict(at=str(t)[:16],open=value,close=value,high=value+.01,low=value-.01,
                price_basis='raw',price_basis_source='sina_1m_unadjusted',source='新浪1分钟OHLC'))
            t+=timedelta(minutes=1)
        return bars,ctx,q,str(f[5])

    def test_fifteen_trading_minutes_exit(self):
        result=T.minutes_status(*self.inputs());self.assertEqual(result['state'],'退出')

    def test_short_prick_then_recovery(self):
        result=T.minutes_status(*self.inputs('09:50','09:55'));self.assertEqual(result['state'],'快速收回')
        self.assertLessEqual(result['reclaim']['minutes'],15)

    def test_gap_cannot_establish_continuous_loss(self):
        result=T.minutes_status(*self.inputs(gap=True));self.assertEqual(result['state'],'待核验')

    def test_future_minutes_do_not_change_current_evidence(self):
        bars,ctx,q,at=self.inputs('09:50','09:55');before=T.minutes_status(bars,ctx,q,at)
        bars.append(dict(bars[-1],at=at[:10]+' 10:05',open=50,close=50,low=49,high=51))
        self.assertEqual(before,T.minutes_status(bars,ctx,q,at))


class DailyCache(unittest.TestCase):
    def test_reuses_completed_day_and_clears_on_data_or_day_change(self):
        f=sample();bars=f[3][next(iter(f[3]))];calendar=f[4]
        T._DAILY_CACHE.clear();T._DAILY_CACHE_DAY=None
        T._DAILY_STATS.update(hits=0,misses=0,clears=0)
        first=T.daily(bars,calendar);second=T.daily(bars,calendar)
        self.assertEqual(first,second)
        self.assertGreaterEqual(T._DAILY_STATS['hits'],1)
        changed=copy.deepcopy(bars);changed[-1]['close']+=.01
        T.daily(changed,calendar)
        self.assertGreaterEqual(T._DAILY_STATS['misses'],2)
        clears=T._DAILY_STATS['clears']
        T.daily(changed,calendar+['2099-01-01'])
        self.assertGreater(T._DAILY_STATS['clears'],clears)
        T._DAILY_CACHE.clear();T._DAILY_CACHE_DAY=None


if __name__=='__main__':unittest.main()
