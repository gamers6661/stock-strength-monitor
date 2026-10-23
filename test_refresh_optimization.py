"""Focused checks for lock recovery, reuse boundaries and frozen list/detail transport."""
import copy
from contextlib import closing
import json
import tempfile
import threading
import gzip
import urllib.request
import urllib.error
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import config
import history_maintenance
import make_dashboard
import serve
import stock_selection as S
import ui_payload
import weekly_members
import stock_selection_rollout as rollout
from test_stock_selection import sample


class RefreshOptimization(unittest.TestCase):
    def test_daytime_maintenance_never_requests_pipeline_lock(self):
        now = datetime(2026, 10, 21, 10, 0)
        with patch.object(history_maintenance, '_run_if_due') as history,              patch.object(weekly_members, '_run_if_due') as members:
            self.assertFalse(history_maintenance.run_if_due(None, {'phase': 'ready'}, None, now))
            self.assertFalse(weekly_members.run_if_due(None, now))
        history.assert_not_called()
        members.assert_not_called()

    def test_lock_contention_keeps_success_and_retries_in_fifteen_seconds(self):
        with patch.object(serve.time, 'sleep', side_effect=[None, StopIteration]) as sleep,              patch.object(serve.time, 'monotonic', return_value=0),              patch.object(serve, 'is_trading_time', return_value=True),              patch.object(serve, 'pick_mode', return_value='quick'),              patch.object(serve, '_SCAN_LOCK', threading.Lock()),              patch.object(serve, 'scan_and_publish', side_effect=config.PipelineBusy('busy')),              patch.dict(serve.INIT, last_scan_ok=True, last_scan='success', last_scan_error=None):
            with self.assertRaises(StopIteration):
                serve.refresh_loop(120, always=True)
            self.assertTrue(serve.INIT['last_scan_ok'])
            self.assertEqual(serve.INIT['last_scan'], 'success')
            self.assertIsNone(serve.INIT['last_scan_error'])
            self.assertTrue(serve.INIT['refresh_waiting_for_lock'])
        self.assertEqual(sleep.call_args_list[1].args[0], 15)

    def test_manual_lock_conflict_retries_without_losing_success(self):
        lock = threading.Lock()
        lock.acquire()
        with patch.object(serve, '_SCAN_LOCK', lock),              patch.object(serve, 'scan_and_publish', side_effect=[config.PipelineBusy('busy'), None]) as scan,              patch.object(serve, 'boundary_capture_done', return_value=True),              patch.object(serve.time, 'sleep') as sleep,              patch.dict(serve.INIT, last_scan_ok=True, last_scan_error=None),              patch.dict(serve.REFRESH):
            serve._refresh_worker('quick')
            self.assertEqual(scan.call_count, 2)
            self.assertTrue(serve.INIT['last_scan_ok'])
            self.assertTrue(serve.REFRESH['ok'])
            self.assertFalse(serve.INIT['refresh_waiting_for_lock'])
            self.assertFalse(lock.locked())
        sleep.assert_called_once_with(15)

    def test_stale_startup_skips_rebuilding_old_snapshot(self):
        with patch.object(serve, 'reusable_publication', return_value=False),              patch.object(serve, 'snapshot_refresh_due', return_value=True),              patch.object(serve, 'publish_outputs') as publish,              patch.object(serve, 'scan_and_publish') as scan,              patch.object(serve, 'pick_mode', return_value='quick'),              patch.dict(serve.INIT):
            serve.publish_reused_snapshot({}, datetime(2026, 10, 21, 10))
        publish.assert_not_called()
        scan.assert_called_once_with(mode='quick')

    def test_compatible_startup_serves_existing_package(self):
        with patch.object(serve, 'reusable_publication', return_value=True),              patch.object(serve, 'snapshot_refresh_due', return_value=False),              patch.object(serve, 'publish_outputs') as publish:
            serve.publish_reused_snapshot({}, datetime(2026, 10, 21, 10))
        publish.assert_called_once_with({}, reuse_page=True)

    def test_reuse_rejects_source_and_runtime_contract_changes(self):
        saved = dict(publication_sources='same', generated_at='clock',
                     runtime_contract={'code_stock_selection_hash': S.IMPLEMENTATION_HASH})
        with tempfile.TemporaryDirectory() as tmp, patch.object(config, 'ROOT', Path(tmp)),              patch.object(ui_payload, 'active_generation', return_value='token'),              patch.object(ui_payload, 'blob', side_effect=lambda *a: json.dumps(saved)),              patch.object(make_dashboard, 'publication_source_hash', return_value='same'):
            (Path(tmp)/'dashboard.html').write_text('page')
            self.assertTrue(serve.reusable_publication({'generated_at': 'clock'}))
            saved['publication_sources'] = 'old'
            self.assertFalse(serve.reusable_publication({'generated_at': 'clock'}))
            saved['publication_sources'] = 'same'
            saved['runtime_contract']['code_stock_selection_hash'] = 'old'
            self.assertFalse(serve.reusable_publication({'generated_at': 'clock'}))

    def test_completed_metrics_invalidate_on_history_amount_or_rules_change(self):
        snap, history, calendar, amounts, now, codes = sample()
        code = codes[0]
        bars = history[code]
        records = amounts[code]
        S._DAILY_METRICS.clear()
        with patch.object(S, 'base_metrics', wraps=S.base_metrics) as calculate:
            first = S.daily_metrics(code, bars, records)
            first['returns']['5'] = -999
            self.assertNotEqual(S.daily_metrics(code, bars, records)['returns']['5'], -999)
            self.assertEqual(calculate.call_count, 1)
            bars[-1]['volume'] *= 1.01
            S.daily_metrics(code, bars, records)
            records[bars[-1]['date']]['amount'] += 1
            S.daily_metrics(code, bars, records)
            with patch.dict(S.R, amount_min=S.R['amount_min']+1):
                S.daily_metrics(code, bars, records)
            self.assertEqual(calculate.call_count, 4)

    def test_page_projection_uses_current_shared_snapshot_and_its_clock(self):
        snap, history, calendar, amounts, now, codes = sample()
        snap.update(session='早盘', quote_capture_at=str(now), strength_model={'asof': calendar[-1]})
        with patch.object(S, 'read', side_effect=AssertionError('must not reuse independent latest')), \
             patch.object(S, 'refresh_projection', return_value={'shared': True}) as compute:
            self.assertEqual(S.page_model(snap), {'shared': True})
        self.assertIs(compute.call_args.args[0], snap)
        self.assertEqual(compute.call_args.kwargs, {'now': now, 'shared': True})

    def test_published_http_uses_etag_and_gzip(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(config, 'CACHE_DIR', Path(tmp)):
            target = Path(tmp)/'stock_selection_v3'/'latest.json'
            target.parent.mkdir()
            content = b'{"result_version":"one","items":{}}'
            target.write_bytes(content)
            publication = patch.object(ui_payload, 'active_generation', return_value='a'*24)
            payload = patch.object(ui_payload, 'blob', return_value=gzip.compress(content))
            publication.start(); payload.start()
            self.addCleanup(publication.stop); self.addCleanup(payload.stop)
            server = serve.Server(('127.0.0.1', 0), serve.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = 'http://127.0.0.1:'+str(server.server_port)+'/__stock_selection'
                with urllib.request.urlopen(urllib.request.Request(url, headers={'Accept-Encoding': 'gzip'})) as response:
                    self.assertEqual(response.headers['Content-Encoding'], 'gzip')
                    self.assertEqual(gzip.decompress(response.read()), content)
                    etag = response.headers['ETag']
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(urllib.request.Request(url, headers={'If-None-Match': etag}))
                self.assertEqual(caught.exception.code, 304)
                self.assertEqual(caught.exception.read(), b'')
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_quote_revision_invalidates_at_session_boundary_and_expiry(self):
        snap, history, calendar, amounts, now, codes = sample()
        snap['session'] = '早盘'
        initial = S.quote_revision(snap, now)
        self.assertNotEqual(initial, S.quote_revision(snap, now + timedelta(seconds=config.INTRADAY['max_quote_age_seconds'] + 1)))
        midday = now.replace(hour=12, minute=0)
        self.assertNotEqual(S.quote_revision(snap, midday), S.quote_revision(snap, midday.replace(hour=13)))

    def test_live_rollout_keeps_candidate_without_retired_computation(self):
        candidate = dict(version='current', items={'600000': {'score': 80}}, _state={'day': 'today'})
        with patch.object(rollout, 'load', side_effect=[{'stage': 'live'}, {'source_at': 'old comparison'}]),              patch('stock_activity.build') as legacy, patch.object(rollout, 'save') as save:
            actual = rollout.project(candidate, None, None, None, None, None, None, None)
        self.assertIs(actual, candidate)
        self.assertEqual(actual['items']['600000']['score'], 80)
        self.assertFalse(actual['rollout']['comparison_active'])
        self.assertEqual(actual['rollout']['comparison_source_at'], 'old comparison')
        legacy.assert_not_called()
        save.assert_not_called()

    def test_full_root_reconstructs_original_order_and_keeps_old_format_readable(self):
        full = {'marker': {'unknown': None}, 'stocks': [{'code': '600002', 'value': 2}, {'code': '600001', 'value': 1}],
                'coverage_catalog': [], 'board_catalog': [{'id': 'theme:x', 'members': []}]}
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp)/'page.html'
            _, token = ui_payload.prepare(full, 'var DATA=/*__DATA__*/null;', page, project_charts=False)
            self.assertEqual(ui_payload.full(token, page), full)
            self.assertEqual(json.loads(ui_payload.blob(token, 'full', page)), full)
            with closing(ui_payload.connect(token, page)) as con:
                self.assertIsNone(con.execute("SELECT value FROM meta WHERE id='full.gz'").fetchone())
        # Previous immutable generations remain supported without rewriting them.
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp)/'page.html'
            token = 'a'*24
            target = ui_payload.store_root(page)
            target.mkdir(parents=True)
            import sqlite3
            con = sqlite3.connect(target/(token+'.db'))
            con.execute('CREATE TABLE meta(id TEXT PRIMARY KEY,value BLOB)')
            con.execute('INSERT INTO meta VALUES(?,?)', ('full.gz', gzip.compress(json.dumps(full).encode())))
            con.commit()
            con.close()
            self.assertEqual(ui_payload.full(token, page), full)

    def test_brief_and_frozen_full_model_share_result_version(self):
        f = sample()
        model = S.build(f[0], f[1], f[2], amount_records=f[3], now=f[4])
        model.pop('_state')
        full = dict(f[0], stock_selection=model)
        original = copy.deepcopy(full)
        with tempfile.TemporaryDirectory() as tmp:
            packet, token = ui_payload.prepare(full, 'var DATA=/*__DATA__*/null;', Path(tmp)/'dashboard.html', project_charts=False)
            brief = ui_payload.unpack(packet)['stock_selection']
            frozen = ui_payload.decode_detail(ui_payload.blob(token, 'stock_selection.gz', Path(tmp)/'dashboard.html'))
            self.assertTrue(brief['details_deferred'])
            self.assertEqual(brief['result_version'], frozen['result_version'])
            self.assertEqual(brief['order'], model['order'])
            for code in model['items']:
                self.assertNotIn('evidence', brief['items'][code])
                for key in ('rank', 'score', 'dimensions', 'eligible', 'list_name', 'quote', 'pattern'):
                    self.assertEqual(brief['items'][code][key], model['items'][code][key])
                self.assertEqual(frozen['items'][code], json.loads(json.dumps(model['items'][code])))
        self.assertEqual(full, original)


if __name__ == '__main__':
    unittest.main()
