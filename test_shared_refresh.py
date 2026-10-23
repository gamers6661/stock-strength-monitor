"""Shared-round publication, passive sampling and stale-response checks."""
import copy
import io
import json
import subprocess
import tempfile
import threading
import unittest
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import config
import serve
import stock_activity as A
import stock_activity_sampler as sampler
import stock_selection as S
from test_stock_selection import sample


class SharedRefresh(unittest.TestCase):
    def test_five_minute_publication_preserves_path_gap_rule(self):
        self.assertEqual(config.RUNTIME['refresh_seconds'], 300)
        self.assertLessEqual(sampler.INTERVAL, S.R['live_gap_seconds'])

    def test_projection_cannot_replace_current_quote_with_independent_sample(self):
        snap, history, calendar, amounts, now, codes = sample()
        snap.update(session='早盘', quote_capture_at=str(now))
        def read(name, default=None):
            if name == 'state.json': return {'day': str(now.date()), 'items': {}}
            if name == 'rollout.json': return {'stage': 'live'}
            return {}
        with tempfile.TemporaryDirectory() as tmp, patch.object(config, 'CACHE_DIR', Path(tmp)), \
             patch.object(S, 'read', side_effect=read), patch.object(S, 'inputs', return_value=(history, calendar)), \
             patch.object(S.amounts, 'load', return_value=amounts), \
             patch.object(A, 'live_view', side_effect=AssertionError('independent overlay')), \
             patch.object(A, 'archive_frames', return_value=[]), \
             patch('stock_selection_intraday.attach', side_effect=lambda model, *args: model):
            model = S.refresh_projection(snap, now=now, shared=True)
        self.assertEqual(model['source_round_at'], str(now))
        self.assertEqual(model['refresh_policy'], 'shared-round-5m-v1')
        for row in snap['stocks']:
            self.assertEqual(model['items'][row['code']]['quote']['price'], row['price'])
            self.assertEqual(model['items'][row['code']]['quote_at'], row['quote_at'])

    def test_passive_capture_records_quotes_without_projection(self):
        snap, history, calendar, amounts, now, codes = sample()
        class Clock(datetime):
            @classmethod
            def now(cls): return now
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); pool = root/'pool.json'; pool.write_text(json.dumps(codes))
            saved = root/'snapshot.json'; saved.write_text('{}')
            with patch.object(config, 'CACHE_DIR', root), patch.object(config, 'POOL_CACHE', pool), \
                 patch.object(config, 'SNAPSHOT_JSON', saved), patch.object(sampler, 'datetime', Clock), \
                 patch.object(sampler.datafeed, 'tencent_quotes', return_value={r['code']: r for r in snap['stocks']}), \
                 patch.object(S, 'refresh_projection', side_effect=AssertionError('passive sample cannot publish')):
                result = sampler.capture_once(publish=False)
                self.assertNotIn('projection_error', result)
                self.assertTrue((root/'stock_activity_samples/latest.json').exists())
                self.assertTrue(list((root/'stock_activity_samples/acquisitions').glob('*.gz')))

    def test_regular_tick_does_not_repeat_recent_shared_manual_or_boundary_round(self):
        with patch.object(serve.time, 'monotonic', return_value=300), \
             patch.object(serve.time, 'sleep', side_effect=[None, StopIteration]) as sleep, \
             patch.object(serve, 'scan_and_publish') as scan, \
             patch.dict(serve.INIT, last_round_started_monotonic=250):
            with self.assertRaises(StopIteration): serve.refresh_loop(300, always=True)
        scan.assert_not_called()
        self.assertEqual(sleep.call_args_list[-1].args[0], 250)

    def test_browser_uses_only_published_model_and_csv_refuses_cross_generation(self):
        script = r"""
const fs=require('fs'),vm=require('vm');let timers=[],ctx={DATA:{ui_generation:'one',stock_selection:{result_version:'frozen',details_deferred:true}},window:{setInterval:(...a)=>timers.push(a)},MS_VIEW:{stocks:{}},STATE:{},msOpenStocks(){},msRows(){},msRender(){},renderStocks(){},msCSV(){},toast:m=>ctx.message=m};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('stock_selection_ui.js','utf8'),ctx);
ctx.SS_LIVE={result_version:'unpublished'};
if(ctx.ssModel().result_version!=='frozen'||timers.length)throw Error('independent result or timer');
let resolve;ctx.ssRows=()=>[];ctx.ssFullModel=()=>new Promise(r=>resolve=r);ctx.ssCSVModel=()=>{throw Error('mixed-generation CSV')};
let task=ctx.ssCSV();ctx.DATA.ui_generation='two';resolve({result_version:'old'});
Promise.resolve(task).then(()=>{if(!ctx.message.includes('数据已更新'))throw Error('old async CSV accepted');console.log('shared model and async CSV passed')}).catch(e=>{console.error(e);process.exitCode=1});
"""
        result=subprocess.run(['node','-e',script],cwd=config.ROOT,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)


if __name__ == '__main__': unittest.main()
