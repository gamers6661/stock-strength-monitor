"""Bounded after-hours integrity work; never competes with current market scans."""
from contextlib import closing
from datetime import datetime
import json
import time

import config
import datafeed
import history_increment
import scan_cache
import ui_payload


def current_inputs():
    token=ui_payload.active_generation()
    if not token:
        return {},None
    brief=ui_payload.unpack(json.loads(ui_payload.blob(token,'summary')))
    rows=brief.get('stocks',[])+brief.get('coverage_catalog',[])
    return {r['code']:r for r in rows},(brief.get('strength_model') or {}).get('asof')


@config.single_writer
def run_if_due(scan_lock, state, publish, now=None):
    now=now or datetime.now()
    if now.hour<18 or state.get('phase')!='ready' or not scan_lock.acquire(blocking=False):
        return False
    started=time.monotonic()
    active=False
    try:
        quotes,asof=current_inputs()
        if not quotes or not asof:
            return False
        with closing(datafeed.db()) as conn:
            if not history_increment.integrity_due(conn,quotes):
                return False
            active=True
            state.update(scan_active=True,scan_started_at=now.isoformat(timespec='seconds'),scan_mode='history-integrity')
            scan_cache.PROGRESS.update(active=True,started=time.time(),stage='盘后历史核验',mode='history-integrity')
            result=history_increment.update(conn,list(quotes),quotes,required_day=asof,progress=False,budget_seconds=60)
        # A discovered revision must be carried into all judgments, not merely written to SQLite.
        if result['changed_rows'] or result.get('integrity_pending'):
            publish()
            state.update(last_scan_ok=True,last_scan=datetime.now().isoformat(timespec='seconds'),last_scan_error=None)
        state['history_maintenance']=dict(ok=True,finished_at=datetime.now().isoformat(timespec='seconds'),
                                          seconds=round(time.monotonic()-started,3),acquisition=result)
        return True
    except Exception as exc:
        state['history_maintenance']=dict(ok=False,error=str(exc),finished_at=datetime.now().isoformat(timespec='seconds'))
        raise
    finally:
        if active:
            state.update(scan_active=False,scan_started_at=None,scan_mode=None)
            scan_cache.PROGRESS.update(active=False,stage=None)
        scan_lock.release()


def loop(scan_lock,state,publish):
    while True:
        try:
            run_if_due(scan_lock,state,publish)
        except Exception as exc:
            print(f'[HISTORY] 盘后历史核验未完成：{exc}')
        time.sleep(300)
