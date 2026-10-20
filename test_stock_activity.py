"""V2.1: event evidence, independent identity lifecycle and actual UI contracts."""
import copy
import csv
import io
import json
import subprocess
import unittest
import tempfile
import gzip
from unittest.mock import patch
from datetime import timedelta
from pathlib import Path

import stock_activity as A
import stock_activity_engine as E
import ui_payload
from test_market_strength import fixture


def sample(gain=1.2,peers=0.,prices=None,peer_prices=None):
    s,q,p,h,cal,now=fixture(12)
    codes=sorted(q)
    prices=prices or [100,100,100]+[100+gain]*10
    peer_prices=peer_prices or [100+peers]*len(prices)
    s['board_catalog'].append(dict(id='industry:test',name='测试行业',type='industry',catalog_listed=True,member_codes=codes))
    s['board_catalog'][0]['catalog_listed']=True
    for bars in h.values():
        for b in bars:b.update(volume=1000000.,amount=100000000.)
    frames=[]
    base=now.replace(hour=9,minute=30)
    for i,price in enumerate(prices):
        at=base+timedelta(minutes=2*i)
        quotes={}
        for c in codes:
            value=price if c==codes[0] else peer_prices[i]
            quotes[c]=dict(q[c],code=c,board_type='sh_main',industry=['测试行业'],price=value,
                high=max(101.,value),low=min(99.,value),change_pct=value-100,quote_at=str(at),
                volume_shou=10000.,amount_wan=100*value)
        frames.append((str(at),A.valid_frame(quotes,at,'早盘')))
    s.update(quote_capture_at=str(at),stocks=list(quotes.values()))
    return s,h,cal,frames,codes


def calculate(f,previous=None):
    if previous and '_state' in previous:previous=previous['_state']
    return A.build(f[0],f[1],f[2],frames=f[3],previous=previous)


def board_core(end=18):
    return sample(prices=[100]*3+[101.2]*(end-3),peer_prices=[100]*10+[100.8]*(end-10))

def render(s, action):
    source = r"""
const fs=require('fs'),vm=require('vm'),els={};
const input=INPUT;
const ctx={DATA:input,Date:class extends Date{constructor(v){super(v||input.quote_capture_at);}},parseDT:v=>new Date(v),STATE:{boardFilterId:null,q:''},RENDERED:{},closeDrawer(){},goPane(){},
document:{activeElement:null,addEventListener(){},querySelector(){return {style:{}}},getElementById(id){return els[id]||(els[id]={innerHTML:'',textContent:'',style:{}})}},
esc:v=>String(v),jsq:v=>String(v),fmt:(v,n)=>v==null?'—':Number(v).toFixed(n||2),pctHtml:v=>String(v),
boardById:id=>ctx.DATA.board_catalog.find(b=>b.id===id),openDrawer:(...args)=>ctx.drawer=args,setTimeout(){},defaultFilters:()=>({})};
vm.createContext(ctx);
for(const f of ['radar_ui.js','stock_rank_ui.js','ma_trend_ui.js','stock_activity_ui.js'])vm.runInContext(fs.readFileSync(f,'utf8'),ctx);
ctx.downloadMSCSV=(text)=>ctx.csv=text;
vm.runInContext(ACTION,ctx);
console.log(JSON.stringify({els,ids:ctx.msRows('stocks').map(r=>r.code),csv:ctx.csv,drawer:ctx.drawer,view:ctx.MS_VIEW.stocks}));
"""
    source=source.replace('INPUT',json.dumps(s,ensure_ascii=False)).replace('ACTION',json.dumps(action))
    p=subprocess.run(['node','-'],input=source,capture_output=True,text=True,encoding='utf8')
    if p.returncode:
        raise AssertionError(p.stderr)
    return json.loads(p.stdout)



class StockActivity(unittest.TestCase):
    def test_trigger_is_immediate_but_no_fake_complete_score(self):
        m=calculate(sample(prices=[100,100,100,101.2]))['items']['600000']
        self.assertEqual(m['list_name'],'startup')
        self.assertEqual(m['event']['status'],'triggered')
        self.assertIsNone(m['factors']['Q']);self.assertIsNone(m['score'])
        self.assertEqual(m['event']['trigger_interval'],['2026-10-13 09:30:00','2026-10-13 09:36:00'])

    def test_holding_and_timing_evidence_are_independent(self):
        f=sample(prices=[100]*3+[101.2]*3)
        m=calculate(f)['items']['600000'];marks=m['event']['evidence']
        self.assertEqual(marks['holding']['status'],'confirmed')
        self.assertNotIn('timing',marks)
        self.assertEqual(m['confirmation'],'承接已确认')
        self.assertIsNone(m['score'])

    def test_independent_attack_does_not_need_diffusion(self):
        m=calculate(sample())['items']['600000']
        self.assertEqual(m['role'],'独立进攻')
        self.assertEqual(m['list_name'],'startup')
        self.assertIsNotNone(m['score']);self.assertNotIn('diffusion',m['event']['evidence'])
        self.assertEqual(m['evidence']['history_event_days'],[])

    def test_two_distinct_independent_attacks_can_make_core(self):
        prices=[100]*3+[101.2]*17+[102.5]*12
        m=calculate(sample(prices=prices))['items']['600000']
        self.assertEqual(m['identity']['kind'],'独立型核心')
        self.assertEqual(m['list_name'],'core')
        self.assertEqual(len(m['events']),2)
        self.assertTrue(m['event']['evidence']['repeat'])

    def test_independent_repeat_confirmation_can_span_trading_days(self):
        first=calculate(sample())
        f=sample()
        f[0]['quote_capture_at']=f[0]['quote_capture_at'].replace('2026-10-13','2026-10-14')
        for row in f[0]['stocks']:
            row['quote_at']=row['quote_at'].replace('2026-10-13','2026-10-14')
            if row['code']=='600000':row.update(last_close=101.2,change_pct=0.)
        for i,(at,frame) in enumerate(f[3]):
            at=at.replace('2026-10-13','2026-10-14')
            for c,p in frame.items():
                p.update(at=at,received_at=at)
                if c=='600000':p.update(last_close=101.2,change=100*(p['price']/101.2-1))
            f[3][i]=(at,frame)
        f[2].append('2026-10-13')
        for c,bars in f[1].items():
            close=101.2 if c=='600000' else 100.
            bars.append(dict(bars[-1],date='2026-10-13',open=close,close=close,high=close+.5,low=close-.5,amount=close*1000000))
        m=calculate(f,first)['items']['600000']
        self.assertEqual(m['list_name'],'core')
        self.assertEqual(m['identity']['kind'],'独立型核心')

    def test_one_continuous_rally_does_not_create_repeated_independent_events(self):
        prices=[100+i*.3 for i in range(35)]
        m=calculate(sample(prices=prices))['items']['600000']
        self.assertEqual(len(m['events']),1)
        self.assertNotEqual(m['list_name'],'core')

    def test_board_leader_needs_later_diffusion_and_holding(self):
        m=calculate(board_core())['items']['600000']
        self.assertEqual(m['list_name'],'core')
        self.assertEqual(m['identity']['kind'],'板块先行核心')
        self.assertTrue(m['event']['evidence']['diffusion'])
        self.assertFalse(m['event']['evidence']['diffusion']['detail']['causality'])

    def test_follower_not_core_even_if_it_rises_more(self):
        f=sample(prices=[100]*13+[103.]*8,peer_prices=[100]*6+[100.8]*15)
        m=calculate(f)['items']['600000']
        self.assertEqual(m['role'],'跟随进攻')
        self.assertFalse(m['eligible'])
        self.assertIsNone(m['score'])

    def test_overlapping_intervals_do_not_invent_order(self):
        f=sample(prices=[100]*3+[101.2]*9,peer_prices=[100]*3+[100.8]*9)
        m=calculate(f)['items']['600000']
        self.assertEqual(m['role'],'时序不明')
        self.assertNotEqual(m['list_name'],'core')
        self.assertNotIn('timing',m['event']['evidence'])

    def test_falling_less_is_not_a_price_attack(self):
        f=sample(prices=[100]*3+[99.8]*10,peer_prices=[100]*3+[98.]*10)
        m=calculate(f)['items']['600000']
        self.assertIsNone(m['event']);self.assertFalse(m['eligible'])

    def test_fast_fade_fails_before_holding_confirmation(self):
        m=calculate(sample(prices=[100,100,100,101.2,100.1,100.05]))['items']['600000']
        self.assertEqual(m['event']['status'],'failed')
        self.assertNotIn('holding',m['event']['evidence'])
        self.assertFalse(m['eligible'])

    def test_identity_survives_event_completion_and_quiet_consolidation(self):
        first=calculate(board_core())
        later=calculate(board_core(32),first)
        a=first['items']['600000'];b=later['items']['600000']
        self.assertEqual(b['event']['status'],'completed')
        self.assertEqual(b['identity']['created_at'],a['identity']['created_at'])
        self.assertEqual(b['list_name'],'core')
        self.assertEqual(b['current_state'],'强势整理')

    def test_new_unconfirmed_attack_does_not_remove_existing_core_score(self):
        first=calculate(board_core())
        f=sample(prices=[100]*3+[101.2]*17+[102.5],peer_prices=[100]*10+[100.8]*11)
        m=calculate(f,first)['items']['600000']
        self.assertEqual(m['list_name'],'core')
        self.assertEqual(m['event']['status'],'triggered')
        self.assertIsNotNone(m['score'])
        self.assertNotEqual(m['event']['id'],m['evidence']['scoring_event_id'])

    def test_identity_exits_only_after_continuous_structure_failure(self):
        first=calculate(board_core())
        prices=[100]*3+[101.2]*15+[98.]*4
        f=sample(prices=prices,peer_prices=[100]*10+[100.8]*12)
        current=calculate(f,first)['items']['600000']
        self.assertEqual(current['identity']['status'],'invalid')
        self.assertEqual(current['current_state'],'失效')
        self.assertEqual(current['identity']['support_price'],first['items']['600000']['identity']['support_price'])

    def test_old_identity_cannot_persist_without_current_or_historical_advantage(self):
        first=calculate(board_core())
        f=sample(prices=[100]*8)
        f[0]['quote_capture_at']=f[0]['quote_capture_at'].replace('2026-10-13','2026-10-14')
        for row in f[0]['stocks']:row['quote_at']=row['quote_at'].replace('2026-10-13','2026-10-14')
        f[3][:]=[(at.replace('2026-10-13','2026-10-14'),{c:dict(p,at=p['at'].replace('2026-10-13','2026-10-14'),received_at=at.replace('2026-10-13','2026-10-14')) for c,p in frame.items()}) for at,frame in f[3]]
        f[2].append('2026-10-13')
        for bars in f[1].values():bars.append(dict(bars[-1],date='2026-10-13'))
        m=calculate(f,first)['items']['600000']
        self.assertEqual(m['identity']['status'],'invalid')
        self.assertTrue(any('超额均不再支持' in e['reason'] for e in m['journal']))

    def test_missing_sample_resets_window_not_identity(self):
        f=sample(prices=[100,100,100,101.2])
        f[3][2][1].pop('600000')
        self.assertIsNone(calculate(f)['items']['600000']['event'])
        first=calculate(board_core())
        f=board_core(20)
        f[3][-2][1].clear()
        m=calculate(f,first)['items']['600000']
        self.assertEqual(m['identity']['status'],'active')
        self.assertEqual(m['identity']['created_at'],first['items']['600000']['identity']['created_at'])

    def test_whole_feed_outage_preserves_historical_identity_and_stops_ranking(self):
        first=calculate(board_core())
        f=board_core(20)
        for row in f[0]['stocks']:row['quote_at']='2026-10-12 10:00:00'
        f[3].clear()
        m=calculate(f,first)['items']['600000']
        self.assertEqual(m['state'],'pending');self.assertFalse(m['eligible'])
        self.assertEqual(m['identity']['status'],'active')

    def test_recovery_does_not_repeat_ids_or_events(self):
        f=board_core();first=calculate(f);again=calculate(f,first)
        a=first['items']['600000'];b=again['items']['600000']
        self.assertEqual(a['events'],b['events'])
        self.assertEqual(a['identity'],b['identity'])
        self.assertEqual(a['score'],b['score'])

    def test_future_frame_or_saved_state_is_not_used_in_replay(self):
        f=sample();before=calculate(f)
        f[3].append(('2099-01-01 10:00:00',f[3][0][1]))
        self.assertEqual(before,calculate(f))
        future=copy.deepcopy(before['_state']);future['processed_at']='2099-01-01 10:00:00'
        self.assertEqual(before,calculate(f,future))

    def test_reconstructed_evidence_does_not_backdate_actual_confirmation(self):
        f=board_core()
        late=A.build(f[0],f[1],f[2],frames=f[3],detected_at='2026-10-13 11:00:00')
        event=late['items']['600000']['event']
        self.assertTrue(event['reconstructed'])
        self.assertEqual(event['evidence']['holding']['confirmed_at'],'2026-10-13 11:00:00')
        self.assertLess(event['evidence']['holding']['observed_at'],'2026-10-13 11:00:00')
        self.assertEqual(calculate(f,late),calculate(f))

    def test_price_basis_unknown_is_pending_not_zero_score(self):
        f=sample();f[0]['stocks'][0].pop('last_close_semantics')
        m=calculate(f)['items']['600000']
        self.assertEqual(m['state'],'pending');self.assertIsNone(m['score'])

    def test_R_is_uniformly_disabled_and_no_individual_weight_filling(self):
        model=calculate(board_core())
        for m in model['items'].values():self.assertIsNone(m['factors']['R'])
        m=model['items']['600000'];f=m['factors']
        self.assertAlmostEqual(m['score'],(30*f['L']+20*f['H']+20*f['E']+20*f['Q'])/90,places=1)
        self.assertFalse(model['rules']['R_enabled'])

    def test_today_limit_up_cannot_buy_core_or_replace_daily_baseline(self):
        f=sample(prices=[100,100,100,110.]);m=calculate(f)['items']['600000']
        self.assertEqual(m['list_name'],'startup');self.assertEqual(m['identity']['status'],'none')
        self.assertEqual(m['evidence']['historical_excess'],0)
        self.assertEqual(m['evidence']['today_excess_contribution'],2.)
        self.assertIsNone(m['score'])

    def test_daily_reference_cannot_hide_current_clear_weakness(self):
        f=sample(prices=[90.]*10)
        for b,close in zip(f[1]['600000'][-6:],[90.,92.,94.,96.,98.,100.]):
            b.update(open=close,close=close,high=close+.5,low=close-.5)
        m=calculate(f)['items']['600000']
        self.assertTrue(m['evidence']['daily_reference'])
        self.assertEqual(m['list_name'],'watch')
        self.assertEqual(m['current_state'],'转弱')

    def test_no_mutation_or_selective_minute_model_dependency(self):
        f=board_core();saved=copy.deepcopy(f);before=calculate(f)
        self.assertEqual(f,saved)
        f[0]['stocks'][0]['emotion_relay']={'score':100}
        f[0]['stocks'][0]['ma_trend']={'minute_evidence':[1,2,3]}
        self.assertEqual(before,calculate(f))

    def test_self_excluded_industry_reference(self):
        values={str(i):float(i) for i in range(9)}
        ref=A.Reference(values,{c:'i' for c in values},{'i':list(values)},9)
        self.assertEqual(ref.get('8')['industry'],3.5)

    def test_lunch_is_not_a_gap_and_duplicate_sources_do_not_confirm(self):
        self.assertEqual(E.elapsed('2026-10-13 11:28:00','2026-10-13 13:02:00'),240)
        f=sample(prices=[100,100,100,101.2,101.2,101.2])
        for i in (4,5):
            f[3][i][1]['600000']['at']=f[3][3][1]['600000']['at']
        for row in f[0]['stocks']:
            if row['code']=='600000':row['quote_at']=f[3][3][1]['600000']['at']
        m=calculate(f)['items']['600000']
        self.assertIsNone(m['factors']['Q'])

    def test_page_failure_is_isolated(self):
        f=sample();saved=copy.deepcopy(f[0])
        with patch.object(A,'prepare',side_effect=ValueError('broken')),self.assertLogs(level='ERROR'):
            result=A.prepare_page(f[0])
        self.assertEqual(result['counts']['pending'],12)
        self.assertEqual(f[0],saved)

    def test_actual_UI_filters_detail_CSV_same_model_values(self):
        f=board_core();s=f[0];s['stock_activity']=calculate(f);s['ui_generation']='frozen-ui'
        s['stock_activity'].pop('_state');s['stock_activity']['result_version']='v21-result'
        r=render(s,"msRender('stocks');saShow('600000');saCSV();")
        self.assertIn('按板块 / 题材选股',r['els']['ms-stock-host']['innerHTML'])
        self.assertEqual(r['ids'],['600000'])
        exported=list(csv.DictReader(io.StringIO(r['csv'].lstrip('\ufeff'))))
        self.assertEqual(float(exported[0]['综合强度']),s['stock_activity']['items']['600000']['score'])
        self.assertEqual(exported[0]['强度结果版本'],'v21-result')
        self.assertIn('独立确认证据',r['drawer'][2])
        s['board_catalog'].append(dict(id='theme:empty',type='theme',name='另一题材',catalog_listed=True,member_codes=f[4][1:]))
        r=render(s,"MS_VIEW.stocks.themeIds=['theme:empty'];msRender('stocks');")
        self.assertEqual(r['ids'],[])
        r=render(s,"MS_VIEW.stocks.activityScope='all';MS_VIEW.stocks.themeIds=['theme:empty'];MS_VIEW.stocks.industryIds=['industry:test'];msRender('stocks');")
        self.assertEqual(set(r['ids']),set(f[4][1:]))
        self.assertEqual(ui_payload.summary(s,'frozen-ui')['stock_activity'],s['stock_activity'])

    def test_unrelated_renderers_are_unchanged(self):
        from test_market_strength import run
        f=sample();run((f[0],{r['code']:r for r in f[0]['stocks']},{c:dict(board_type='sh_main') for c in f[4]},f[1],f[2],A.stamp(f[0]['quote_capture_at'])))
        before=render(f[0],"msRender('industry');msRender('theme');")
        f[0]['stock_activity']=calculate(f)
        after=render(f[0],"msRender('industry');msRender('theme');")
        self.assertEqual(before['els'],after['els'])

    def test_independent_confirmation_never_claims_temporal_lead(self):
        m=calculate(sample())['items']['600000']
        self.assertTrue(E.confirmed(m['event'],'independent'))
        self.assertFalse(E.confirmed(m['event'],'timing'))
        self.assertIn('独立角色',m['confirmation'])
        self.assertNotIn('领先',m['confirmation'])

    def test_gap_pauses_pending_event_and_rebuilds_before_confirmation(self):
        first=calculate(sample(prices=[100,100,100,101.2]))
        f=sample(prices=[100]*3+[101.2]*3)
        f[3][4][1].pop('600000')
        m=calculate(f,first)['items']['600000']
        self.assertEqual(m['event']['id'],first['items']['600000']['event']['id'])
        self.assertEqual(m['event']['status'],'triggered')
        self.assertIsNone(m['factors']['Q'])
        self.assertEqual(m['list_name'],'pending')
        self.assertEqual(m['data_quality']['status'],'recovering')
        later=sample(prices=[100]*3+[101.2]*7)
        later[3][4][1].pop('600000')
        recovered=calculate(later,first)['items']['600000']
        self.assertEqual(recovered['event']['id'],m['event']['id'])
        self.assertEqual(recovered['event']['status'],'confirmed')
        self.assertEqual(recovered['data_quality']['status'],'available')
        self.assertNotIn('timing',recovered['event']['evidence'])

    def test_data_outage_freezes_last_structural_state(self):
        first=calculate(board_core())
        f=board_core(20)
        for row in f[0]['stocks']:row['quote_at']='2026-10-12 10:00:00'
        f[3].clear()
        m=calculate(f,first)['items']['600000']
        self.assertEqual(m['current_state'],first['items']['600000']['current_state'])
        self.assertEqual(m['identity']['status'],'active')
        self.assertFalse(m['eligible'])
        self.assertEqual(m['confidence_parts']['sampling'],0)

    def test_same_receipt_batch_does_not_make_stale_sources_comparable(self):
        f=sample()
        for at,frame in f[3]:
            frame['600000']['at']=str(A.stamp(frame['600000']['at'])-timedelta(seconds=120))
        f[0]['stocks'][0]['quote_at']=f[3][-1][1]['600000']['at']
        m=calculate(f)['items']['600000']
        self.assertIsNone(m['event'])
        self.assertEqual(m['list_name'],'pending')

    def test_known_version_migration_preserves_identity_ids_anchors_and_times(self):
        f=sample(prices=[100]*3+[101.2]*17+[102.5]*12)
        first=calculate(f);old=copy.deepcopy(first['_state'])
        old.update(version='个股主动强度V2.1-20261019.1',score_version='LHEQ-R关闭-20261019.1')
        for event in old['items']['600000']['events']:
            event['evidence']['timing']=event['evidence'].pop('independent')
        m=calculate(f,old)['items']['600000']
        expected=first['items']['600000']
        self.assertEqual(m['identity']['created_at'],expected['identity']['created_at'])
        self.assertEqual(m['identity']['support_price'],expected['identity']['support_price'])
        self.assertEqual([e['id'] for e in m['events']],[e['id'] for e in expected['events']])
        self.assertEqual(m['event']['evidence']['independent']['confirmed_at'],expected['event']['evidence']['independent']['confirmed_at'])
        self.assertNotIn('timing',m['event']['evidence'])
        self.assertEqual(m['list_name'],'pending')

    def test_old_independent_events_cannot_confirm_a_new_pending_attack(self):
        model=calculate(sample(prices=[100]*3+[101.2]*17+[102.5]*12))
        state=copy.deepcopy(model['_state']['items']['600000'])
        state['identity']['status']='invalid'
        old=state['events'][-1]
        new=dict(old,id='genuinely-new-event',status='triggered',evidence={},role='时序不明')
        state['events'].append(new)
        p=state['last_point'];details=dict(event_days={p['at'][:10]},historical_excess=10)
        E.identity_update(state,p,details,2.,2.,True)
        self.assertEqual(state['identity']['status'],'invalid')

    def test_new_startup_is_visible_after_an_old_identity_has_exited(self):
        first=calculate(sample(prices=[100]*3+[101.2]*17+[102.5]*12))
        saved=first['_state'];saved['items']['600000']['identity']['status']='invalid'
        f=sample(prices=[100]*3+[101.2]*17+[102.5]*22+[104.])
        m=calculate(f,saved)['items']['600000']
        self.assertEqual(m['list_name'],'startup')
        self.assertEqual(m['identity']['status'],'invalid')
        self.assertIsNone(m['score'])

    def test_unchanged_feed_cannot_keep_live_core_ranking_indefinitely(self):
        f=board_core();first=calculate(f)
        f[0]['quote_capture_at']=str(A.stamp(f[0]['quote_capture_at'])+timedelta(minutes=4))
        f[3].clear()
        m=calculate(f,first)['items']['600000']
        self.assertEqual(m['identity']['status'],'active')
        self.assertEqual(m['list_name'],'pending')
        self.assertEqual(m['current_state'],first['items']['600000']['current_state'])

    def test_UI_missing_data_message_is_not_followed_by_conflicting_empty_reason(self):
        f=sample();s=f[0];s['stock_activity']=calculate(f)
        s['stock_activity']['counts']=dict(core=0,startup=0,reference=0,watch=0,pending=12)
        s['stock_activity']['pool_count']=12
        r=render(s,"msRender('stocks');")
        text=r['els']['ms-stock-host']['innerHTML']
        self.assertIn('当前数据不足以完成判断',text)
        self.assertNotIn('本榜不以高涨幅补足名额',text)

    def test_restart_across_lunch_preserves_event_and_confirmations(self):
        f=sample(prices=[100]*3+[101.2]*4)
        times=['11:24:00','11:26:00','11:28:00','11:30:00','13:00:00','13:02:00','13:04:00']
        for i,(_,frame) in enumerate(f[3]):
            at='2026-10-13 '+times[i]
            for p in frame.values():p.update(at=at,received_at=at)
            f[3][i]=(at,frame)
        f[0]['quote_capture_at']=f[3][-1][0]
        for row in f[0]['stocks']:row['quote_at']=f[3][-1][0]
        first=copy.deepcopy(f);first[3][:]=first[3][:5]
        first[0]['quote_capture_at']=first[3][-1][0]
        for row in first[0]['stocks']:row['quote_at']=first[3][-1][0]
        before=calculate(first)
        after=calculate(f,before)
        self.assertEqual(after,calculate(f))
        a=before['items']['600000'];b=after['items']['600000']
        self.assertEqual(a['event']['id'],b['event']['id'])
        self.assertEqual(b['event']['evidence']['holding']['observed_at'],'2026-10-13 13:04:00')
        self.assertNotIn('observation',[j['kind'] for j in b['journal']])

    def test_projection_error_keeps_persisted_identity_without_ranking_it(self):
        f=board_core();model=calculate(f)
        with patch.object(A,'prepare',side_effect=ValueError('broken')),patch.object(A,'load_state',return_value=model['_state']),self.assertLogs(level='ERROR'):
            failed=A.prepare_page(f[0])
        before=model['items']['600000'];m=failed['items']['600000']
        self.assertEqual(m['identity'],before['identity'])
        self.assertEqual(m['event']['id'],before['event']['id'])
        self.assertEqual(m['current_state'],before['current_state'])
        self.assertEqual(m['list_name'],'pending')
        self.assertIsNone(m['score'])


if __name__=='__main__':unittest.main()
