import copy,json,tempfile,unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
import completed_reference as C,config,scoring,serve,market_strength as M,ma_trend as T,emotion_relay as E

def prior():
    s=dict(session='已收盘',quote_capture_at='2026-10-15 17:27:24',generated_at='2026-10-15 17:33:27',
        stocks=[dict(code='000530',price=10,change_pct=10)],strength_model=dict(asof='2026-10-15'))
    for name,mod in [('market_strength',M),('ma_trend',T),('emotion_relay',E)]:s[name]=dict(implementation_hash=mod.IMPLEMENTATION_HASH)
    return s

class Preopen(unittest.TestCase):
    def test_startup_refresh_uses_source_age_instead_of_publication_time(self):
        now=datetime(2026,10,16,10,30)
        s=dict(generated_at='2026-10-16 10:30:00',quote_capture_at='2026-10-16 10:30:00',
               intraday_model=dict(latest_valid_quote_at='2026-10-16 10:09:29'))
        self.assertTrue(serve.snapshot_refresh_due(s,now))
        s['intraday_model']['latest_valid_quote_at']='2026-10-16 10:29:59'
        self.assertFalse(serve.snapshot_refresh_due(s,now))
        self.assertFalse(serve.snapshot_refresh_due(s,datetime(2026,10,16,9,10)))

    def test_reused_stale_page_is_published_before_immediate_scan(self):
        now=datetime(2026,10,16,10,30);s=dict(quote_capture_at='2026-10-16 10:09:29')
        order=[];state={}
        with patch.object(serve,'INIT',state),patch.object(serve,'publish_outputs',side_effect=lambda s:order.append('publish')), \
             patch.object(serve,'scan_and_publish',side_effect=lambda **kw:order.append('scan')):
            serve.publish_reused_snapshot(s,now)
        self.assertEqual(order,['publish','scan']);self.assertEqual(state['phase'],'ready')
        self.assertFalse(state['scan_active'])
        self.assertIsNone(state['last_scan_note'])

    def test_nine_ten_reuses_completed_prices_without_fetching_today(self):
        old=prior();original=copy.deepcopy(old)
        with patch('datafeed.realtime_quotes') as quote:
            s=C.build(old,datetime(2026,10,16,9,10))
        quote.assert_not_called();self.assertEqual(old,original)
        self.assertEqual(s['stocks'],old['stocks']);self.assertEqual(s['quote_capture_at'],old['quote_capture_at'])
        self.assertEqual(s['session'],'盘前');self.assertEqual(s['reference_view']['asof'],'2026-10-15')
        self.assertFalse(s['reference_view']['model_replayed'])

    def test_scoring_preopen_publishes_reference_instead_of_data_not_ready(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'snapshot.json';p.write_text(json.dumps(prior()),encoding='utf-8')
            with patch.object(config,'SNAPSHOT_JSON',p),patch.object(scoring.df,'session_label',return_value='盘前'),patch.object(scoring,'datetime') as clock,patch.object(scoring.df,'build_pool') as pool:
                clock.now.return_value=datetime(2026,10,16,9,10)
                s=scoring.run(progress=False)
            pool.assert_not_called();self.assertEqual(s['reference_view']['kind'],'preopen')
            self.assertEqual(json.loads(p.read_text(encoding='utf-8'))['session'],'盘前')

    def test_initial_not_ready_keeps_usable_page_without_error_status(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'snapshot.json';p.write_text(json.dumps(prior()),encoding='utf-8')
            state={}
            with patch.object(config,'SNAPSHOT_JSON',p),patch.object(serve,'INIT',state),patch.object(serve,'scan_and_publish',side_effect=scoring.DataNotReady('竞价报价尚未发布')),patch.object(serve,'publish_outputs') as publish:
                serve.init_worker()
            publish.assert_called_once();self.assertEqual(state['phase'],'ready');self.assertIsNone(state['error'])
            self.assertIsNone(state['last_scan_error']);self.assertIn('尚未发布',state['last_scan_note'])

    def test_no_history_is_waiting_not_made_up_prices(self):
        with self.assertRaises(scoring.DataNotReady):C.build({},datetime(2026,10,16,9,10))

    def test_only_verified_same_version_completed_models_can_be_kept_for_auction(self):
        s=prior();s['market_strength']['close_verification']={'date':'2026-10-15'}
        s['emotion_relay']['mode']='正式收盘'
        self.assertTrue(C.usable(s));s['emotion_relay']['implementation_hash']='old'
        self.assertFalse(C.usable(s))

if __name__=='__main__':unittest.main()
