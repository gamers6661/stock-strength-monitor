"""真实边界：迟启动收盘、读写竞争、半行留存与发布失败。"""
from datetime import datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import subprocess
import sys
import http.client
import unittest
from unittest.mock import patch

import config
import daily
import intraday_path
import make_dashboard
import scoring
import serve
import intraday


class AuditIntegrityTests(unittest.TestCase):
    def test_http_rejects_foreign_origin_and_host_without_refreshing(self):
        server=serve.Server(('127.0.0.1',0),serve.Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        port=server.server_port
        def request(method,path,headers=None):
            connection=http.client.HTTPConnection('127.0.0.1',port,timeout=5)
            try:
                connection.request(method,path,headers=headers or {})
                response=connection.getresponse();response.read();return response.status
            finally:connection.close()
        try:
            with patch.object(serve,'start_refresh',return_value={'status':'started'}) as refresh:
                self.assertEqual(request('GET','/__ping'),200)
                self.assertEqual(request('GET','/__ping',{'Host':'foreign.example:'+str(port)}),403)
                self.assertEqual(request('POST','/__refresh',{'Origin':'https://foreign.example'}),403)
                self.assertEqual(request('POST','/__refresh',{'Sec-Fetch-Site':'cross-site'}),403)
                refresh.assert_not_called()
                self.assertEqual(request('POST','/__refresh',{'Origin':'http://127.0.0.1:'+str(port)}),200)
                refresh.assert_called_once()
        finally:server.shutdown();server.server_close();thread.join(5)

    def test_prior_day_history_survives_partial_last_line(self):
        with TemporaryDirectory() as tmp,patch.object(intraday,'HISTORY_DIR',Path(tmp)):
            record={'rows':[['600001','2026-10-08 15:00:00',10]+[None]*9+[True]]}
            (Path(tmp)/'2026-10-08.jsonl').write_text(json.dumps(record)+'\n{"rows":',encoding='utf-8')
            self.assertEqual(intraday._latest_record_before('2026-10-09'),record)

    def test_pipeline_lock_blocks_other_process_and_releases_after_failure(self):
        with TemporaryDirectory() as tmp,patch.object(config,'CACHE_DIR',Path(tmp)):
            script=('from pathlib import Path; import config; config.CACHE_DIR=Path('+repr(tmp)+'); '
                    '\ntry:\n with config.pipeline_guard(): print("acquired")'
                    '\nexcept config.PipelineBusy: print("busy")')
            def child():
                run=subprocess.run([sys.executable,'-c',script],capture_output=True,text=True,timeout=15,
                                   creationflags=0x08000000 if config.os.name=='nt' else 0)
                self.assertEqual(run.returncode,0,run.stderr)
                return run.stdout.strip()
            with self.assertRaisesRegex(RuntimeError,'failed'):
                with config.pipeline_guard():
                    with config.pipeline_guard():self.assertEqual(child(),'busy')
                    raise RuntimeError('failed')
            self.assertEqual(child(),'acquired')

    def test_old_rules_keep_price_but_cannot_supply_current_attack(self):
        with TemporaryDirectory() as tmp:
            day='2026-10-09';row=[None]*41
            row[0]='600001';row[1]=day+' 10:05:00';row[2]=10;row[4]=90;row[12]=True
            row[28]=True;row[29]=9.8;row[31]=True;row[33]=95;row[34]='A';row[36]=True
            record=dict(day=day,scan_at=day+' 10:05:01',rows=[row],rule_version='旧规则',
                        price_basis_version=intraday.PRICE_BASIS_VERSION)
            (Path(tmp)/(day+'.jsonl')).write_text(json.dumps(record)+'\n',encoding='utf-8')
            point=intraday_path.load(tmp,day)['points']['600001'][0]
            self.assertEqual(point['price'],10)
            self.assertEqual(point['ma10'],9.8)
            self.assertIsNone(point['attack_score'])
            self.assertFalse(point['attack'])

    def test_late_manual_refresh_still_updates_missing_formal_close(self):
        with patch.object(serve,'SNAPSHOT_META',{'snapshot_daily_asof':'2026-10-08'}):
            self.assertEqual(serve.pick_mode(datetime(2026,10,9,17,0)),'close')

    def test_failed_page_publish_cannot_report_success(self):
        with TemporaryDirectory() as tmp, patch.object(config,'ROOT',Path(tmp)), \
             patch.object(daily.sys,'argv',['daily.py','--quiet']), \
             patch.object(scoring,'run',return_value={'generated_at':'2026-10-09 15:05:00'}), \
             patch.object(make_dashboard,'build',side_effect=OSError('publish failed')):
            self.assertEqual(daily.main(),1)

    def test_atomic_writes_from_two_threads_use_independent_temp_files(self):
        with TemporaryDirectory() as tmp:
            target=Path(tmp)/'state.json';ready=threading.Event();second_done=threading.Event();errors=[]
            original=config.os.replace
            def synchronized_replace(src,dst):
                if threading.current_thread().name=='first':
                    ready.set();second_done.wait(5)
                return original(src,dst)
            def write(value):
                try:config.atomic_write_text(target,json.dumps({'value':value}))
                except Exception as exc:errors.append(type(exc).__name__)
                finally:
                    if value==2:second_done.set()
            with patch.object(config.os,'replace',side_effect=synchronized_replace):
                a=threading.Thread(target=write,args=(1,),name='first');a.start()
                self.assertTrue(ready.wait(5))
                b=threading.Thread(target=write,args=(2,),name='second');b.start();b.join(5);a.join(5)
            self.assertEqual(errors,[])
            self.assertIn(json.loads(target.read_text())['value'],(1,2))

    def test_partial_history_line_is_read_when_completed(self):
        with TemporaryDirectory() as tmp:
            day='2026-10-09';target=Path(tmp)/(day+'.jsonl')
            row=['600001',day+' 10:05:00',10.0]+[None]*10;row[12]=True
            record=json.dumps(dict(day=day,scan_at=day+' 10:05:01',rows=[row])).encode()+b'\n'
            target.write_bytes(record[:len(record)//2])
            self.assertEqual(intraday_path.load(tmp,day)['points'],{})
            with target.open('ab') as stream:stream.write(record[len(record)//2:])
            self.assertEqual(len(intraday_path.load(tmp,day)['points'].get('600001',[])),1)

    def test_inline_snapshot_cannot_close_its_script(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);snapshot=root/'snapshot.json';template=root/'template.html';output=root/'page.html'
            snapshot.write_text(json.dumps({'stocks':[],'note':'</script><div id="audit-marker">'}),encoding='utf-8')
            template.write_text('<script>var DATA = /*__DATA__*/null;</script>',encoding='utf-8')
            import board_trend
            with patch.object(config,'SNAPSHOT_JSON',snapshot),patch.object(make_dashboard,'TPL',template), \
                 patch.object(make_dashboard,'OUT',output),patch.object(make_dashboard,'attach_klines'), \
                 patch.object(board_trend,'attach'):
                make_dashboard.build()
            page=output.read_text(encoding='utf-8')
            self.assertEqual(page.lower().count('</script>'),1)
            restored,_=json.JSONDecoder().raw_decode(page.split('var DATA = ',1)[1])
            self.assertEqual(restored['note'],'</script><div id="audit-marker">')


if __name__=='__main__':unittest.main()
