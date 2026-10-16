import copy,json,unittest
from datetime import datetime,timedelta
from unittest.mock import patch
import relay_data as D,relay_history as H,relay_regulation as R,relay_cycles as C,emotion_relay as E


def fixture():
    days=['2026-09-%02d'%d for d in range(1,16)]
    codes=['600001','000002','600003'];rows={c:dict(name=c,industry=['共同主营行业']) for c in codes};paths={}
    for c in codes:
        paths[c]=[dict(date=d,sealed=False,height=0,exact=True,halted=False,reason=None) for d in days]
    for i in range(3,13):paths[codes[0]][i].update(sealed=True,height=i-2)
    for i in (13,14):paths[codes[0]][i].update(sealed=None,height=10,halted=True)
    for i in range(11,15):paths[codes[1]][i].update(sealed=True,height=i-10)
    models={c:dict(code=c,valid=True,eligible=True,roles=[],risks=[],continuation=[],prior_sealed=True,prior_height=p[-1]['height'],height=p[-1]['height']+1,height_exact=True,sealed=True,mode='盘中暂态',suspended_current=False) for c,p in paths.items()}
    models[codes[0]].update(valid=False,sealed=None)
    board=dict(id='theme:small',name='具体题材',type='theme',member_codes=codes)
    reg=dict(notices=[dict(id='notice',title='严重异常波动',kind='serious',codes=[codes[0]],published_at=days[10]+' 20:00:00',available_day=days[11],url='https://issuer.test/notice')],scope_codes=codes,covered_codes=codes,indices={})
    evidence=dict(verified_halts=[dict(code=codes[0],start=days[13],resume=None,reason='停牌核查',source='https://issuer.test/halt',published_at=days[12]+' 19:00:00')])
    return rows,models,paths,[board],evidence,reg,days,'2026-09-16'


class Cycles(unittest.TestCase):
    def test_pause_preserves_cycle_highest_and_does_not_become_a_break(self):
        f=fixture();meta=C.attach(*f);m=f[1]['600001']
        self.assertEqual(meta['cycle_highest'],10);self.assertTrue(m['suspended_current']);self.assertIsNone(m['feedback_pct'])
        self.assertEqual(m['height'],10);self.assertNotIn('break',[n['kind'] for n in meta['nodes']])
        self.assertEqual([n['kind'] for n in meta['nodes']],['regulation','suspension'])

    def test_regulation_cohort_keeps_third_and_fourth_board_original_first_board(self):
        f=fixture();C.attach(*f);m=f[1]['000002'];self.assertEqual(m['height'],5)
        self.assertEqual(len(m['continuation']),1);n=m['continuation'][0]
        self.assertEqual(n['date'],f[6][11]);self.assertEqual(n['first_board_date'],f[6][11]);self.assertEqual(n['leader_height'],8)
        self.assertEqual(n['label'],'监管接续候选')

    def test_current_verified_trading_cannot_be_overridden_by_open_old_halt(self):
        f=fixture();f[1]['600001']['valid']=True;C.attach(*f)
        self.assertFalse(f[1]['600001']['suspended_current'])
        self.assertIn('停牌记录与有效成交报价冲突',f[1]['600001']['risks'])

    def test_first_board_one_day_before_or_after_node_is_not_that_cohort(self):
        for shift in (-1,1):
            f=fixture();f[5]['notices'][0]['available_day']=f[6][11+shift];C.attach(*f)
            self.assertFalse(f[1]['000002']['continuation'])

    def test_broken_old_cohort_is_not_revived_by_new_wave(self):
        f=fixture();f[2]['000002'][12].update(sealed=False,height=0);f[2]['000002'][13].update(height=1)
        C.attach(*f);self.assertFalse([n for n in f[1]['000002']['continuation'] if n['kind']=='regulation']);self.assertTrue(f[1]['000002']['node_history'])
        f=fixture();f[1]['000002'].update(mode='正式收盘',sealed=False,price=10.)
        C.attach(*f);self.assertFalse(f[1]['000002']['continuation'])
        self.assertEqual(f[1]['000002']['history'][-1]['date'],f[-1]);self.assertFalse(f[1]['000002']['history'][-1]['sealed'])

    def test_future_height_does_not_authorize_an_earlier_node(self):
        f=fixture();f[5]['notices'][0]['available_day']=f[6][5]
        meta=C.attach(*f);self.assertFalse([n for n in meta['nodes'] if n['kind']=='regulation'])

    def test_only_first_serious_notice_per_wave_creates_node(self):
        f=fixture();n=dict(f[5]['notices'][0],id='repeat',published_at=f[6][11]+' 20:00:00',available_day=f[6][12]);f[5]['notices'].append(n)
        self.assertEqual(len([n for n in C.attach(*f)['nodes'] if n['kind']=='regulation']),1)

    def test_generic_huge_theme_does_not_authorize_relationship(self):
        f=fixture()
        for c,r in f[0].items():r['industry']=[c+'不同主营行业']
        f[3][0]['member_codes'] +=['X'+str(i) for i in range(310)];C.attach(*f)
        self.assertFalse(f[1]['000002']['continuation'])

    def test_companion_needs_start_proximity_and_repeated_overlap(self):
        f=fixture();p=f[2]['600003']
        for i in range(2,7):p[i].update(sealed=True,height=i-1)
        C.attach(*f);r=f[1]['600003']['companions'][0]
        self.assertEqual(r['start_gap'],-1);self.assertEqual(len(r['overlap_days']),4)
        f=fixture();f[2]['600003'][3].update(sealed=True,height=1);C.attach(*f)
        self.assertFalse(f[1]['600003'].get('companions'))

    def test_old_cycle_does_not_remain_current_core(self):
        f=fixture();f[2]['600001'][10].update(sealed=False,height=0)
        for i in range(11,15):f[2]['600001'][i].update(sealed=False,height=0,halted=False)
        self.assertEqual(C.attach(*f)['cycle_highest'],0)

    def test_true_highest_break_creates_distinct_same_day_first_board_batch(self):
        f=fixture();f[2]['600001'][11].update(sealed=False,height=0)
        for i in range(12,15):f[2]['600001'][i].update(sealed=False,height=0,halted=False)
        f[5]['notices']=[];C.attach(*f)
        self.assertEqual(f[1]['000002']['continuation'][0]['label'],'断板补涨候选')


class HistoryAndDisclosures(unittest.TestCase):
    def test_lagging_index_daily_can_use_verified_same_index_closing_quote(self):
        value=[dict(code='zs_000002',status=0,hq=[['2026-10-14','12','12','0','0%','11','13']])]
        parts=['']*35
        for i,v in {0:'1',1:'Ａ股指数',2:'000002',3:'12.5',4:'12',5:'12.1',30:'20261015153000',33:'12.8',34:'12'}.items():parts[i]=v
        quote='v_sh000002="'+'~'.join(parts)+'";'
        with patch.object(R,'datetime') as clock,patch.object(R.datafeed,'http_get',side_effect=[json.dumps(value),quote]):
            clock.now.return_value=datetime(2026,10,15,16)
            record=R.fetch_index('sh000002','2026-10-15','2026-10-14')
        self.assertEqual(record['bars'][-1]['close'],12.5);self.assertEqual(record['closing_quote_at'],'2026-10-15 15:30:00')
        self.assertEqual(record['completed_through'],'2026-10-15')

    def test_index_fallback_rejects_stock_identity_wrong_day_or_previous_close(self):
        value=[dict(code='zs_000002',status=0,hq=[['2026-10-14','12','12','0','0%','11','13']])]
        for changed in (1,4,30):
            parts=['']*35
            for i,v in {0:'1',1:'Ａ股指数',2:'000002',3:'12.5',4:'12',5:'12.1',30:'20261015153000',33:'12.8',34:'12'}.items():parts[i]=v
            parts[changed]={1:'万科Ａ',4:'11.99',30:'20261016153000'}[changed]
            with patch.object(R,'datetime') as clock,patch.object(R.datafeed,'http_get',side_effect=[json.dumps(value),'v_sh000002="'+'~'.join(parts)+'";']):
                clock.now.return_value=datetime(2026,10,15,16)
                with self.assertRaises(ValueError):R.fetch_index('sh000002','2026-10-15','2026-10-14')

    def test_post_close_timestamp_needs_verified_native_ohlc_and_keeps_source_clock(self):
        from test_emotion_relay import sample,run
        f=sample();s,q,p,h,cal,now,e=f;now=now.replace(hour=15,minute=20);s['session']='已收盘';s['close_daily_verified_at']=str(now)
        for c,quote in q.items():
            for b in h[c]:b.update(price_basis='qfq',price_basis_source='tencent_qfqday')
            quote['quote_at']=str(now.replace(minute=16));bar=dict(h[c][-1],date=now.date().isoformat(),open=quote['open'],close=quote['price'],high=quote['high'],low=quote['low'],price_basis='qfq',price_basis_source='tencent_qfqday');h[c].append(bar)
        c=next(iter(q));proof=H.close_proof(s,q[c],h[c],cal,now);self.assertIsNotNone(proof)
        models=run((s,q,p,h,cal,now,e));self.assertTrue(models[c]['valid']);self.assertEqual(models[c]['mode'],'正式收盘')
        self.assertEqual(models[c]['quote_at'],q[c]['quote_at']);self.assertIn('收盘日线已核验',models[c]['events'])
        self.assertEqual(s['stocks'][0]['market_strength']['mode'],'连续竞价');self.assertEqual(s['emotion_relay']['history_asof'],now.date().isoformat())
        for change in ('price','basis','semantics','future','missing'):
            quote=copy.deepcopy(q[c]);bars=copy.deepcopy(h[c])
            if change=='price':bars[-1]['high']+=.01
            elif change=='basis':quote['price_basis_source']='unknown'
            elif change=='semantics':quote['last_close_semantics']='unknown'
            elif change=='future':quote['quote_at']=str(now+timedelta(minutes=5))
            else:bars.pop()
            self.assertIsNone(H.close_proof(s,quote,bars,cal,now),change)
        missing=cal[-10];bars=[b for b in h[c] if b['date']!=missing]
        with patch.object(R,'load',return_value=dict(suspension_intervals=[])):
            proof=H.close_proof(s,q[c],bars,cal,now,code=c)
            self.assertIsNotNone(proof);self.assertEqual(proof['inferred_suspension_days'],[missing])
        halt=dict(code=c,start=missing,resume=cal[cal.index(missing)+1],reason='公司停牌公告',source='https://issuer.test/halt')
        with patch.object(R,'load',return_value=dict(suspension_intervals=[halt])):
            proof=H.close_proof(s,q[c],bars,cal,now,code=c)
        self.assertIsNotNone(proof);self.assertEqual(proof['inferred_suspension_days'],[missing])

    def test_full_formal_close_keeps_paused_core_and_updates_its_market_window(self):
        from test_emotion_relay import sample,run
        f=sample();s,q,p,h,cal,now,e=f;c=next(iter(q));now=now.replace(hour=15,minute=1);s['session']='已收盘'
        for row in s['stocks']:row['market_strength']['mode']='正式收盘'
        for quote in q.values():quote['quote_at']=str(now.replace(minute=0))
        q[c]['amount_wan']=q[c]['volume_shou']=0
        halt=dict(code=c,start=cal[-1],resume=None,reason='停牌核查',source='https://issuer.test',published_at=cal[-2]+' 20:00:00')
        e['regulation']=dict(notices=[],indices={},scope_codes=[c],covered_codes=[c],suspension_intervals=[halt])
        other=list(q)[-1];q[other]['amount_wan']=q[other]['volume_shou']=0
        e['regulation']['suspension_intervals'].append(dict(halt,code=other,start=now.date().isoformat()))
        original=E.chain
        def replay(code,*args):
            path=original(code,*args)
            if code==c:
                for i,v in enumerate(path[-6:-1]):v.update(sealed=True,height=i+1,exact=True,halted=False)
                path[-1].update(sealed=None,height=5,exact=True,halted=True)
            return path
        with patch.object(E,'chain',side_effect=replay):models=run((s,q,p,h,cal,now,e))
        m=models[c];self.assertTrue(m['suspended_current']);self.assertEqual(m['height'],5)
        self.assertEqual(m['history'][-1]['date'],now.date().isoformat())
        self.assertEqual(m['regulation']['reference']['windows'][0]['asof'],now.date().isoformat())
        self.assertEqual(s['emotion_relay']['history_asof'],now.date().isoformat());self.assertEqual(len(s['emotion_relay']['timeline']),20)
        self.assertEqual(s['emotion_relay']['timeline'][-1]['suspended'],2)

    def test_dated_issuer_interval_repairs_old_halt_and_excludes_resume_day(self):
        notes=[dict(codes=['600001'],title='停牌公告',published_at='2026-09-07 19:00:00',url='a',text='公司股票自2026年9月7日（星期一）开市起停牌。'),dict(codes=['600001'],title='复牌公告',published_at='2026-09-18 17:00:00',url='b',text='公司股票将于2026年9月21日（星期一）上午开市起复牌。')]
        intervals=R.intervals(notes);self.assertEqual(intervals[0]['resume'],'2026-09-21')
        e=dict(verified_halts=intervals);self.assertTrue(H.halt_on(e,'600001','2026-09-09'));self.assertFalse(H.halt_on(e,'600001','2026-09-21'))

    def test_historical_table_with_future_replaced_interval_is_not_accepted(self):
        e=dict(halts={'2026-09-09':dict(source='table',rows=[dict(SECURITY_CODE='600001',SUSPEND_EXPIRE='连续停牌',SUSPEND_START_TIME='2026-10-13 09:30:00')])})
        self.assertIsNone(H.halt_on(e,'600001','2026-09-09'))

    def test_after_close_publication_moves_to_next_actual_trade_date(self):
        cal=['2026-09-24','2026-09-28','2026-09-29']
        self.assertEqual(R.available_day('2026-09-24 20:00:00',cal,'2026-09-29'),'2026-09-28')
        self.assertEqual(R.available_day('2026-09-28 08:00:00',cal,'2026-09-29'),'2026-09-28')
        self.assertEqual(R.available_day('2026-09-28 15:00:01',cal,'2026-09-29'),'2026-09-29')

    def test_five_board_chain_spans_verified_pause_without_increment(self):
        days=['d1','d2','d3','d4','d5','d6'];facts=[(False,None,False),(True,None,False),(True,None,False),(None,'pause',True),(None,'pause',True),(True,None,False)]
        with patch.object(H,'classify',side_effect=facts):path=E.chain('600001',days,days,[],dict(reference={}))
        self.assertEqual([p['height'] for p in path],[0,1,2,2,2,3]);self.assertTrue(path[-1]['exact'])
        facts[3]=(None,'missing',False)
        with patch.object(H,'classify',side_effect=facts):path=E.chain('600001',days,days,[],dict(reference={}))
        self.assertFalse(path[-1]['exact'])

    def test_reference_price_handles_ex_rights_and_ohlc_disagreement_disables(self):
        days=['2026-09-%02d'%i for i in range(1,8)];bars=[dict(date=d,open=10.,high=10.,low=10.,close=10.,volume=100) for d in days]
        bars[-1].update(open=8.,high=8.8,low=8.,close=8.8)
        refs=[dict(b,reference_close=10.) for b in bars];refs[-1]['reference_close']=8.
        e=dict(raw={'600001':dict(bars=bars)},reference={'600001':dict(bars=refs)})
        H.index(e);self.assertTrue(H.classify('600001',days[-1],days,e)[0])
        refs[-1]['high']=8.81;H.index(e);self.assertIsNone(H.classify('600001',days[-1],days,e)[0])

    def test_interval_compounding_minus_correct_classification_index(self):
        days=[(datetime(2026,7,1)+timedelta(days=i)).date().isoformat() for i in range(40)]
        bars=[dict(date=d,open=10.,close=10.,high=10.,low=10.,volume=100) for d in days];refs=[dict(b,reference_close=10.) for b in bars]
        for b in refs[-3:]:b.update(reference_close=9.)
        e=dict(raw={'000002':dict(bars=bars)},reference={'000002':dict(bars=refs)})
        H.index(e);indices={'sz399107':dict(bars=[dict(date=d,close=100.) for d in days])}
        result=R.deviation('000002',days,e,indices)
        self.assertEqual(result['benchmark'],'sz399107');self.assertEqual(result['windows'][0]['deviation_pp'],round(((10/9)**3-1)*100,2))
        self.assertIn('重置',result['basis']);self.assertIsNone(R.deviation('600001',days,e,indices)['windows'][0]['deviation_pp'])

    def test_notice_metadata_future_publication_is_not_included(self):
        now=datetime(2026,10,15,14);cal=['2026-10-14']
        item=dict(art_code='future',title='股票严重异常波动',display_time='2026-10-15 19:00:00:100',codes=[dict(stock_code='600001')])
        saved=dict(begin='2026-01-01',fetched_at=str(now),items=[item])
        with patch.object(D,'read',side_effect=lambda p:saved if 'stocks' in str(p) else None):
            result=R.load(['600001'],cal,now,fetch=False)
        self.assertEqual(result['notices'],[])


if __name__=='__main__':unittest.main()
