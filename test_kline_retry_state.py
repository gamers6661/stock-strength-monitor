"""Same-request peer controls, pending/confirmed separation and recovery."""
import copy,json,sqlite3,unittest
from unittest.mock import patch
import config,datafeed as D,history_increment as H,make_dashboard as M
from test_scan_performance import Morning,bar


class RetryState(unittest.TestCase):
    def batch(self,values):
        def fetch(c,**kwargs):
            v=values[c]
            if isinstance(v,Exception):raise v
            return v
        with patch.object(D,'fetch_kline',side_effect=fetch),patch.object(D,'_source_mark'):
            return D.fetch_klines_bulk(list(values),workers=1,progress=False)[0]
    def test_healthy_peer_must_be_from_same_actual_request_batch(self):
        result=self.batch({'000001':[],'000002':[bar('2026-10-09')]})
        s=result.fetch_states['000001'];self.assertEqual(s['kind'],'isolated_empty');self.assertEqual(s['empty_responses'],2)
        self.assertEqual(s['peer_success_count'],1);self.assertEqual(s['peer_codes'],['000002'])
        self.assertNotIn('000001',result)
    def test_all_empty_or_single_stock_has_no_healthy_control(self):
        for inputs in ({'000001':[]},{'000001':[],'000002':[]}):
            r=self.batch(inputs)
            self.assertTrue(all(s['kind']=='source_unverified' and s['peer_success_count']==0 for s in r.fetch_states.values()))
    def test_timeout_is_not_relabelled_as_empty_even_with_successful_peer(self):
        r=self.batch({'000001':TimeoutError('network'),'000002':[bar('2026-10-09')]})
        self.assertEqual(r.fetch_states['000001']['kind'],'request_error')
        self.assertNotIn('empty_responses',r.fetch_states['000001'])
    def state(self):return dict(kind='isolated_empty',empty_responses=2,peer_success_count=1,peer_codes=['000002'],checked_at='2026-10-12T10:00:00')
    def test_suspicion_does_not_set_verified_suspension_or_alter_models(self):
        row=dict(emotion_relay=dict(valid=False),ma_trend=dict(stage=10));before=copy.deepcopy(row)
        s=M.chart_acquisition_state(row,[],self.state(),'2026-10-12','2026-10-09')
        self.assertEqual(s['label'],'疑似停牌');self.assertEqual(row,before);self.assertNotIn('suspended_current',row['emotion_relay'])
    def test_existing_chart_note_renders_label_with_its_actual_peer_evidence(self):
        from test_emotion_ui import render
        from test_emotion_relay import sample,run
        f=sample();run(f)
        state=M.chart_acquisition_state({},[],self.state(),'2026-10-12','2026-10-09')
        r=render(f[0],"document.getElementById('note').innerHTML=msChartAcquisitionNote({chart_data_state:"+json.dumps(state,ensure_ascii=False)+"});")
        html=r['els']['note']['innerHTML'];self.assertIn('疑似停牌',html);self.assertIn('data-tip=',html)
        self.assertIn('同批同源有1只股票',html);self.assertIn('尚未确认停牌',html)
    def test_current_trading_or_missing_peer_control_prevents_suspicion(self):
        active=dict(emotion_relay=dict(valid=True))
        self.assertEqual(M.chart_acquisition_state(active,[],self.state(),'2026-10-12','2026-10-09')['kind'],'data_pending')
        state=self.state();state['peer_success_count']=0
        self.assertEqual(M.chart_acquisition_state({},[],state,'2026-10-12','2026-10-09')['kind'],'data_pending')
        active=dict(intraday_quote_at='2026-10-12 10:00:00',price_basis='raw',price_basis_source='tencent_realtime_quote',volume_shou=100)
        self.assertEqual(M.chart_acquisition_state(active,[],self.state(),'2026-10-12','2026-10-09')['kind'],'data_pending')
    def test_old_observation_or_recovered_complete_candles_clears_message(self):
        self.assertIsNone(M.chart_acquisition_state({},[],self.state(),'2026-10-13','2026-10-12'))
        bars=[bar('2026-10-'+str(d).zfill(2)) for d in (1,2,3,8,9)]
        self.assertIsNone(M.chart_acquisition_state({},bars,self.state(),'2026-10-12','2026-10-09'))
    def test_verified_halt_retains_existing_label_and_resumption_draws_history(self):
        row=dict(emotion_relay=dict(valid=False,suspended_current=True))
        self.assertIsNone(M.chart_acquisition_state(row,[],self.state(),'2026-10-12','2026-10-09'))
        bars=[bar('2026-10-'+str(d).zfill(2)) for d in (1,2,3,8,9)]
        resumed=dict(emotion_relay=dict(valid=False,quote_at='2026-10-12 10:00:00',history=[dict(date='2026-10-09',halted=True)]))
        self.assertTrue(M.attach_completed_candles(resumed,bars,'2026-10-09',day='2026-10-12'))
    def test_increment_persists_isolated_empty_and_clears_it_on_recovery(self):
        conn=sqlite3.connect(':memory:');self.addCleanup(conn.close)
        conn.execute('CREATE TABLE kline(code TEXT,date TEXT,open REAL,close REAL,high REAL,low REAL,volume REAL,amount REAL,price_basis TEXT,price_basis_source TEXT,PRIMARY KEY(code,date))')
        codes=['000001','000002'];old=bar('2026-10-08');rows=[old,bar('2026-10-09')]
        D.save_klines(conn,'kline','code',{c:[old] for c in codes})
        got=D.KlineBatchResult();got['000002']=rows;got.fetch_states['000001']=self.state()
        with patch.dict(config.KLINE,dict(days=2,repair_per_scan=2)),patch.object(H,'datetime',Morning):
            with patch.object(D,'fetch_klines_bulk',return_value=(got,False)):
                H.update(conn,codes,{},'2026-10-09',force=True,progress=False)
            state=json.loads(conn.execute('SELECT payload FROM kline_fetch_state WHERE code=?',('000001',)).fetchone()[0])
            self.assertEqual(state['data_fetch']['kind'],'isolated_empty')
            self.assertEqual(D.load_kline(conn,'kline','code','000001'),[old])
            with patch.object(D,'fetch_klines_bulk',return_value=({c:rows for c in codes},False)):
                H.update(conn,codes,{},'2026-10-09',force=True,progress=False)
        state=json.loads(conn.execute('SELECT payload FROM kline_fetch_state WHERE code=?',('000001',)).fetchone()[0])
        self.assertNotIn('data_fetch',state);self.assertEqual(D.load_kline(conn,'kline','code','000001')[-1]['date'],'2026-10-09')


if __name__=='__main__':unittest.main()
