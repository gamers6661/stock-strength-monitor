"""Speed changes must preserve frozen details, lists and export evidence."""
from concurrent.futures import Future
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from unittest.mock import patch

import board_trend
import config
import serve
import ui_payload
import scan_cache
from test_market_strength import fixture,run
from test_market_strength_integration import render


class RefreshSpeedTests(unittest.TestCase):
    def test_slow_cycle_retries_after_pause_without_waiting_another_slot(self):
        self.assertEqual(serve.next_refresh_run(120,149,120),164)
        self.assertEqual(serve.next_refresh_run(120,489,120),504)
        self.assertEqual(serve.next_refresh_run(240,180,120),240)

    def test_cache_hit_is_isolated_without_copying_twice(self):
        original={'rows':[{'score':80,'reasons':['strong']}]}
        with TemporaryDirectory() as tmp,patch.object(config,'CACHE_DIR',Path(tmp)):
            first=scan_cache.cached('ownership','one',['input'],lambda:original)
            first['rows'][0]['reasons'].append('caller')
            self.assertEqual(original['rows'][0]['reasons'],['strong'])
            second=scan_cache.cached('ownership','one',['input'],lambda:self.fail('cache miss'))
            self.assertEqual(second['rows'][0]['reasons'],['strong'])
            second['rows'][0]['score']=0
            third=scan_cache.cached('ownership','one',['input'],lambda:self.fail('cache miss'))
            self.assertEqual(third['rows'][0]['score'],80)
            scan_cache.flush()
            with scan_cache._lock:
                scan_cache._connections.pop(str(Path(tmp)/'scan_features.db')).close()

    def test_light_lists_keep_rankings_and_full_details_keep_evidence(self):
        f=fixture(8);run(f);full=f[0]
        full['market_strength_morning_input']={'quotes':f[1]}
        full['board_catalog'][0]['index_chart']={'bars':[{'close':12,'date':'2026-10-13'}]}
        original=deepcopy(full)
        with TemporaryDirectory() as tmp:
            page=Path(tmp)/'dashboard.html'
            packet,token=ui_payload.prepare(full,'var DATA = /*__DATA__*/null;',page)
            brief=ui_payload.unpack(packet)
            for action in ("msRender('stocks');","msStockAxis('emotion');","msUpdate('stocks','scope','all');"):
                self.assertEqual(render(brief,action)['ids'],render(original,action)['ids'])
            board=full['board_catalog'][0]
            self.assertEqual(ui_payload.detail(token,'board',board['id'],page),board)
            restored=ui_payload.full(token,page)
            self.assertEqual(restored['market_strength_morning_input'],original['market_strength_morning_input'])
            self.assertEqual(restored['board_catalog'][0]['index_chart'],board['index_chart'])
            self.assertEqual(brief['board_catalog'][0]['member_codes'],board['member_codes'])
            for row in full['stocks']:
                self.assertEqual(ui_payload.detail(token,'stock',row['code'],page)['market_strength'],json.loads(json.dumps(row['market_strength'])))
        self.assertEqual(full,original)

    def test_prior_text_details_and_new_compressed_details_decode_identically(self):
        value={'code':'600000','price':None,'basis':{'parameters':{'5':8},'score':80.12}}
        self.assertEqual(ui_payload.decode_detail(ui_payload.dumps(value)),value)
        self.assertEqual(ui_payload.decode_detail(ui_payload.encode_detail(value)),value)

    def test_prefetch_keeps_actual_quotes_and_does_not_fetch_twice(self):
        future=Future();future.set_result({})
        snapshot={'stocks':[],'board_catalog':[],'strength_model':{'asof':'2026-10-13'}}
        with patch.object(board_trend,'identities',return_value={}), \
             patch.object(board_trend,'calendar_from_db',return_value=[]), \
             patch('board_quote.fetch') as fetch:
            board_trend.attach(snapshot,['2026-10-13'],fetch=False,quote_fetch=True,quote_future=future)
        fetch.assert_not_called()

    def test_service_starts_prefetch_before_scoring_and_joins_it(self):
        quotes={'881001':{'quote_at':'2026-10-14 10:00:01'}}
        def score(**kwargs):
            self.assertEqual(kwargs['board_quote_future'].result(timeout=2),quotes)
            return {'scan_performance':{}}
        with TemporaryDirectory() as tmp,patch.object(config,'CACHE_DIR',Path(tmp)), \
             patch.dict(serve.INIT,{'phase':'ready'}), \
             patch.object(serve.scoring.df,'session_label',return_value='午间休市'), \
             patch.object(serve.board_trend,'identities',return_value={'industry:x':'881001'}), \
             patch.object(serve.board_quote,'fetch',return_value=quotes) as fetch, \
             patch.object(serve.scoring,'run',side_effect=score), \
             patch.object(serve,'publish_outputs'),patch('scan_cache.flush'):
            serve.scan_and_publish('quick')
        fetch.assert_called_once_with({'881001'})

    def test_scoring_resource_wrapper_forwards_quote_future(self):
        future=Future();future.set_result({})
        with TemporaryDirectory() as tmp,patch.object(config,'CACHE_DIR',Path(tmp)), \
             patch.object(serve.scoring,'_run',return_value={}) as inner:
            serve.scoring.run(board_quote_future=future)
        self.assertIs(inner.call_args.args[-1],future)


if __name__=='__main__':
    unittest.main()
