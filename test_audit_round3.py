"""Regression probes for the post-performance full audit."""
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

import board_quote as Q
import board_trend as B
import config
import datafeed as df
import history_increment as H
import history_reference as R
import make_dashboard as M
import scan_cache as C
import scoring
import strength
import repair_kline_gaps
import replay_strength
import refresh_classification
import serve
import weekly_members
import history_maintenance
import threading
from test_scan_performance import bar
from test_trend_consolidation import fixture


class AuditTests(unittest.TestCase):
    def test_member_process_interruption_restores_catalog_before_next_writer(self):
        with TemporaryDirectory() as tmp, patch.object(config,'CACHE_DIR',Path(tmp)):
            target=Path(tmp)/'catalog.json'
            target.write_text('original complete catalog',encoding='utf-8')
            def interrupted(**kwargs):
                target.write_text('partial new catalog',encoding='utf-8')
                raise SystemExit('simulate process exit')
            with patch.object(refresh_classification,'FILES',(target,)), \
                 patch.object(df,'fetch_ths_concept_catalog',side_effect=interrupted):
                with self.assertRaises(SystemExit):
                    refresh_classification.main()
                with config.pipeline_guard():
                    self.assertEqual(target.read_text(encoding='utf-8'),'original complete catalog')

    def test_performance_log_failure_cannot_turn_published_scan_into_failure(self):
        with TemporaryDirectory() as tmp, patch.object(config,'CACHE_DIR',Path(tmp)), \
             patch.object(serve.scoring,'run',return_value={}), patch.object(serve,'publish_outputs'), \
             patch.object(config,'atomic_write_text',side_effect=OSError('metrics locked')):
            serve.scan_and_publish('quick')

    def test_bad_member_state_does_not_break_service_status(self):
        with TemporaryDirectory() as tmp, patch.object(weekly_members,'STATE',Path(tmp)/'state.json'):
            for state in ([],{'last_attempt':'bad-time'}):
                weekly_members.STATE.write_text(json.dumps(state),encoding='utf-8')
                self.assertFalse(weekly_members.status(datetime(2026,10,10,16).timestamp())['running'])

    def test_integrity_maintenance_avoids_daytime_and_busy_writer(self):
        lock=threading.Lock()
        state={'phase':'ready'}
        with TemporaryDirectory() as tmp,patch.object(config,'CACHE_DIR',Path(tmp)), \
             patch.object(history_maintenance,'current_inputs') as read:
            self.assertFalse(history_maintenance.run_if_due(lock,state,lambda:None,datetime(2026,10,9,14)))
            lock.acquire()
            try:
                self.assertFalse(history_maintenance.run_if_due(lock,state,lambda:None,datetime(2026,10,9,18)))
            finally:
                lock.release()
            read.assert_not_called()

    def test_integrity_maintenance_publishes_revisions_with_same_lock(self):
        lock=threading.Lock()
        state={'phase':'ready'}
        conn=sqlite3.connect(':memory:')
        def published():
            self.assertTrue(lock.locked())
            self.assertTrue(config._PIPELINE_LOCAL.active)
        try:
            with TemporaryDirectory() as tmp,patch.object(config,'CACHE_DIR',Path(tmp)), \
                 patch.object(history_maintenance,'current_inputs',return_value=({'a':{'amount_wan':1}},'2026-10-09')), \
                 patch.object(df,'db',return_value=conn),patch.object(H,'integrity_due',return_value=True), \
                 patch.object(H,'update',return_value={'changed_rows':1,'integrity_pending':0}) as update:
                self.assertTrue(history_maintenance.run_if_due(lock,state,published,datetime(2026,10,9,18)))
                self.assertEqual(update.call_args.kwargs['budget_seconds'],60)
                self.assertFalse(state['scan_active'])
                self.assertFalse(lock.locked())
            with self.assertRaises(sqlite3.ProgrammingError):
                conn.execute('SELECT 1')
        finally:
            conn.close()

    def test_board_calendar_connection_closes_on_missing_stock_table(self):
        conn = sqlite3.connect(':memory:')
        try:
            with patch.object(B.sqlite3, 'connect', return_value=conn):
                with self.assertRaises(sqlite3.OperationalError):
                    B.calendar_from_db('2026-10-09')
            with self.assertRaises(sqlite3.ProgrammingError):
                conn.execute('SELECT 1')
        finally:
            conn.close()

    def test_chart_connection_closes_after_normal_read(self):
        conn = sqlite3.connect(':memory:')
        try:
            with patch.object(df, 'db', return_value=conn), patch.object(df, 'load_kline', return_value=[]):
                M.attach_klines({'stocks':[{'code':'600001'}]})
            with self.assertRaises(sqlite3.ProgrammingError):
                conn.execute('SELECT 1')
        finally:
            conn.close()

    def test_scanner_connection_closes_on_downstream_failure(self):
        conn = sqlite3.connect(':memory:')
        try:
            with TemporaryDirectory() as tmp, patch.object(config, 'CACHE_DIR', Path(tmp)), \
                 patch.object(df, 'session_label', return_value='非交易日'), \
                 patch.object(df, 'build_pool', return_value={}), \
                 patch.object(df, 'realtime_quotes', return_value={}), \
                 patch.object(df, 'fetch_outer_resilient', return_value={}), \
                 patch.object(df, 'build_theme_map', return_value={}), \
                 patch.object(df, 'fetch_ths_concept_catalog', return_value={}), \
                 patch.object(scoring.classification, 'reconcile', return_value=({}, {})), \
                 patch.object(scoring.intraday.intraday_path, 'save_acquisition'), \
                 patch.object(df, 'db', return_value=conn), \
                 patch.object(scoring, 'build_board_board', side_effect=RuntimeError('probe')):
                with self.assertRaisesRegex(RuntimeError, 'probe'):
                    scoring.run(progress=False)
            with self.assertRaises(sqlite3.ProgrammingError):
                conn.execute('SELECT 1')
        finally:
            conn.close()

    def test_partial_jsonl_keeps_complete_records_and_consumes_tail_once(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp)/'rows.jsonl'
            path.write_text('{"n":1}\n', encoding='utf-8')
            self.assertEqual(C.read_json(path, lines=True), [{'n':1}])
            with path.open('a', encoding='utf-8') as stream:
                stream.write('{"n":')
            self.assertEqual(C.read_json(path, lines=True), [{'n':1}])
            with path.open('a', encoding='utf-8') as stream:
                stream.write('2}\n')
            self.assertEqual(C.read_json(path, lines=True), [{'n':1},{'n':2}])
            self.assertEqual(C.read_json(path, lines=True), [{'n':1},{'n':2}])

    def test_reference_rebuilds_after_source_price_revision(self):
        bars, days, asof, _ = fixture()
        with TemporaryDirectory() as tmp, patch.object(config, 'CACHE_DIR', Path(tmp)):
            R.ensure({'600001':bars}, asof, days=1)
            original = R.load(asof)['stocks']['600001']['close']
            revised = [dict(b, **{k:b[k]*.5 for k in ('open','high','low','close')}) for b in bars]
            result = R.ensure({'600001':revised}, asof, days=1)
            self.assertEqual(result['generated'], [asof])
            self.assertEqual(R.load(asof)['stocks']['600001']['close'], original*.5)

    def test_reference_rebuilds_after_rule_source_change(self):
        bars, days, asof, _ = fixture()
        with TemporaryDirectory() as tmp, patch.object(config, 'CACHE_DIR', Path(tmp)):
            R.ensure({'600001':bars}, asof, days=1)
            with patch.object(C, 'rules', return_value=['changed-rule-source']):
                self.assertEqual(R.ensure({'600001':bars}, asof, days=1)['generated'], [asof])

    def _increment(self, payload):
        conn = sqlite3.connect(':memory:')
        conn.execute('CREATE TABLE kline(code TEXT,date TEXT,open REAL,close REAL,high REAL,low REAL,volume REAL,amount REAL,price_basis TEXT,price_basis_source TEXT,PRIMARY KEY(code,date))')
        df.save_klines(conn,'kline','code',{'a':[bar('2026-10-09')]})
        conn.execute('CREATE TABLE kline_fetch_state(code TEXT PRIMARY KEY,checked REAL,next_retry REAL,failures INT,payload TEXT)')
        conn.execute('INSERT INTO kline_fetch_state VALUES(?,?,?,?,?)', ('a',0,0,0,payload))
        return conn

    def test_corrupt_one_acquisition_state_does_not_abort_all_symbols(self):
        conn = self._increment('{broken')
        try:
            with patch.dict(config.KLINE, {'days':2}), \
                 patch.object(df, 'fetch_klines_bulk', return_value=({'a':[bar('2026-10-09')]}, False)):
                self.assertEqual(H.update(conn,['a'],{'a':{'amount_wan':1}},'2026-10-09',progress=False)['failed'],0)
        finally:
            conn.close()

    def test_pending_integrity_repair_retries_when_date_is_already_current(self):
        conn = self._increment(json.dumps({'integrity_pending':True}))
        try:
            with patch.dict(config.KLINE, {'days':2}), \
                 patch.object(df, 'fetch_klines_bulk', return_value=({'a':[bar('2026-10-09')]}, False)) as fetch:
                H.update(conn,['a'],{'a':{'amount_wan':1}},'2026-10-09',progress=False)
                fetch.assert_called_once()
        finally:
            conn.close()

    def test_unknown_legacy_prefix_does_not_force_full_repair_of_verified_recent_window(self):
        from datetime import timedelta
        rows=[bar((datetime(2026,1,1)+timedelta(days=i)).date().isoformat()) for i in range(62)]
        rows[0]=dict(rows[0],price_basis=None,price_basis_source=None)
        self.assertFalse(H.requires_full(rows,rows[-20:]))
        self.assertIsNone(rows[0]['price_basis'])
        changed=[dict(b) for b in rows[-20:]]
        changed[-1]['close']=10.1
        self.assertTrue(H.requires_full(rows,changed))

    def test_periodic_audit_requests_entire_cached_history(self):
        conn=self._increment('{}')
        rows=[bar('2026-10-07'),bar('2026-10-08'),bar('2026-10-09')]
        df.save_klines(conn,'kline','code',{'a':rows})
        class Night(datetime):
            @classmethod
            def now(cls): return cls(2026,10,10,18)
        try:
            with patch.dict(config.KLINE,{'days':2}), patch.object(H,'datetime',Night), \
                 patch.object(df,'fetch_klines_bulk',return_value=({'a':rows},False)) as fetch:
                result=H.update(conn,['a'],{'a':{'amount_wan':1}},'2026-10-09',progress=False)
            self.assertEqual(fetch.call_args.kwargs['days'],23)
            self.assertEqual(result['failed'],0)
            self.assertFalse(H.integrity_due(conn,['a']))
        finally:
            conn.close()

    def test_incomplete_periodic_audit_is_not_blessed_or_retried_every_five_minutes(self):
        conn=self._increment('{}')
        rows=[bar('2026-10-07'),bar('2026-10-08'),bar('2026-10-09')]
        df.save_klines(conn,'kline','code',{'a':rows})
        class Night(datetime):
            @classmethod
            def now(cls): return cls(2026,10,10,18)
        try:
            with patch.dict(config.KLINE,{'days':2}), patch.object(H,'datetime',Night), \
                 patch.object(df,'fetch_klines_bulk',return_value=({'a':rows[-2:]},False)):
                result=H.update(conn,['a'],{'a':{'amount_wan':1}},'2026-10-09',progress=False)
            meta=json.loads(conn.execute('SELECT payload FROM kline_fetch_state').fetchone()[0])
            self.assertEqual(result['failed'],1)
            self.assertEqual(meta.get('full_checked',0),0)
            self.assertFalse(H.integrity_due(conn,['a'],now=time.time()+1900))
            self.assertTrue(H.integrity_due(conn,['a'],now=time.time()+8*86400))
            self.assertEqual(len(df.load_kline(conn,'kline','code','a')),3)
        finally:
            conn.close()

    def test_corrupt_state_outside_repair_quota_stays_visible_and_cannot_score(self):
        conn=self._increment('{broken')
        try:
            with patch.dict(config.KLINE,{'days':2,'repair_per_scan':0}):
                rows=scoring.load_klines(conn,['a'],{'a':{'amount_wan':1}},required_day='2026-10-09',progress=False)
            self.assertTrue(rows['a'][0]['history_integrity_pending'])
            self.assertEqual(strength.core_window_issue(rows['a'],['2026-10-09']),'integrity_pending')
        finally:
            conn.close()

    def test_offline_reader_preserves_price_basis_and_closes_connection(self):
        conn=sqlite3.connect(':memory:')
        conn.execute('CREATE TABLE kline(code TEXT,date TEXT,open REAL,close REAL,high REAL,low REAL,volume REAL,amount REAL,price_basis TEXT,price_basis_source TEXT)')
        conn.execute('INSERT INTO kline VALUES(?,?,?,?,?,?,?,?,?,?)',('600001','2026-10-09',10,10,11,9,100,1000,'qfq','tencent_qfqday'))
        try:
            with TemporaryDirectory() as tmp, patch.object(config,'CACHE_DIR',Path(tmp)), \
                 patch.object(replay_strength.sqlite3,'connect',return_value=conn):
                (Path(tmp)/'pool.json').write_text('{"600001":{}}',encoding='utf-8')
                pool,rows=replay_strength.local_data()
                self.assertEqual(rows['600001'][0]['price_basis_source'],'tencent_qfqday')
            with self.assertRaises(sqlite3.ProgrammingError):
                conn.execute('SELECT 1')
        finally:
            conn.close()

    def test_gap_repair_uses_writer_lock_and_shared_integrity_path(self):
        conn=sqlite3.connect(':memory:')
        def update(*args,**kwargs):
            self.assertTrue(config._PIPELINE_LOCAL.active)
            self.assertTrue(kwargs['force'])
            return {'failed':1,'changed_rows':0,'truncated':False}
        try:
            with TemporaryDirectory() as tmp, patch.object(config,'CACHE_DIR',Path(tmp)), \
                 patch.object(config,'SNAPSHOT_JSON',Path(tmp)/'snapshot.json'), \
                 patch.object(df,'db',return_value=conn), patch.object(df,'load_kline',return_value=[]), \
                 patch.object(H,'update',side_effect=update) as acquire:
                config.SNAPSHOT_JSON.write_text(json.dumps({'strength_model':{'asof':'2026-10-09'},'stocks':[],
                    'coverage_catalog':[{'code':'600001','reason':'stale'}]}),encoding='utf-8')
                result=repair_kline_gaps.run()
                self.assertEqual(result['saved_rows'],0)
                acquire.assert_called_once()
            with self.assertRaises(sqlite3.ProgrammingError):
                conn.execute('SELECT 1')
        finally:
            conn.close()

    def test_board_batch_deadline_discards_late_quote_without_cache_write(self):
        raw = 'callback('+json.dumps({'bk_881281':dict(name='电池',date='20261009',pre='129', data='0930,130,1;1006,132,1')})+')'
        def slow(*args, **kwargs):
            time.sleep(.16)
            return raw
        with TemporaryDirectory() as tmp:
            path = Path(tmp)/'q.json'
            prior = Q.parse(raw.replace('1006,132','1005,131'))['881281']
            path.write_text(json.dumps({'quotes':{'881281':prior}}),encoding='utf-8')
            with patch.object(Q, 'TOTAL_BUDGET_SECONDS', .03, create=True), \
                 patch.object(Q.datafeed, 'http_get', side_effect=slow), \
                 patch.object(Q.datafeed, 'session_label', return_value='早盘'):
                started=time.monotonic()
                result=Q.fetch(['881281'],path)
                self.assertLess(time.monotonic()-started,.10)
                self.assertEqual(result['881281']['price'],131)
                self.assertTrue(result['881281']['fetch_error'])
                time.sleep(.18)
                self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['quotes']['881281']['price'],131)

    def test_bad_index_cache_record_cannot_block_other_codes(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'quotes.json'
            for record in ([], {'quotes':{'881281':{'quote_at':'ZZZ'}}}):
                path.write_text(json.dumps(record),encoding='utf-8')
                with patch.object(Q.datafeed,'http_get',side_effect=OSError('offline')):
                    result=Q.fetch(['881281'],path)
                self.assertTrue(result['881281']['fetch_error'])
                self.assertNotIn('price',result['881281'])


if __name__ == '__main__':
    unittest.main()
