"""成员分类每7天更新一次；在非交易时段使用服务扫描锁，失败不密集重试。"""
from datetime import datetime
import json
import time
import math

import config

STATE = config.CACHE_DIR / 'member_weekly_state.json'
_RUNNING = False


def status(now=None):
    now = time.time() if now is None else now
    try:
        state = json.loads(STATE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        state = {}
    if not isinstance(state,dict):
        state={}
    last = state.get('last_attempt')
    valid_attempt = (not isinstance(last,bool) and isinstance(last,(int,float))
                     and math.isfinite(last) and 0<last<=now)
    if not valid_attempt:
        # 旧缓存迁移只读真实文件时间，不伪造一次成功更新。
        stamps = [p.stat().st_mtime for p in (config.THS_MEMBER_CACHE,
                  config.THS_INDUSTRY_MEMBER_CACHE) if p.exists() and p.stat().st_mtime <= now]
        last = max(stamps, default=0)
    next_at = last + config.MEMBER_REFRESH_DAYS*86400 if last else now
    planned = datetime.fromtimestamp(max(next_at, now))
    if planned.weekday() < 5 and planned.hour*60+planned.minute < 15*60+15:
        planned = planned.replace(hour=15,minute=15,second=0,microsecond=0)
    running=bool(state.get('running') and _RUNNING)
    interrupted=bool(state.get('running') and not _RUNNING)
    return dict(interval_days=config.MEMBER_REFRESH_DAYS, due=now>=next_at,
                next_update_at=planned.isoformat(sep=' ', timespec='seconds'),
                last_attempt_at=datetime.fromtimestamp(state['last_attempt']).isoformat(sep=' ',timespec='seconds') if valid_attempt else None,
                last_result='interrupted' if interrupted else state.get('last_result'),
                error='上次成员更新未正常结束，当前保留已发布名单；下次写入前恢复缓存' if interrupted else state.get('error'),
                running=running,last_success_at=state.get('last_success_at'))


def outside_market(now):
    # 整个交易窗口都避开，含竞价、午间及收市定点采集。
    return now.weekday() >= 5 or now.hour*60+now.minute >= 15*60+15


@config.single_writer
def run_if_due(scan_lock, now=None, updater=None):
    global _RUNNING
    now = now or datetime.now()
    if not outside_market(now) or not status(now.timestamp())['due']:
        return False
    if not scan_lock.acquire(blocking=False):
        return False
    try:
        # 获锁后再次核对，避免并发检查造成同周重复更新。
        if not status(now.timestamp())['due']:
            return False
        previous = status(now.timestamp())
        state = dict(last_attempt=now.timestamp(), running=True, last_result='running',
                     last_success_at=previous['last_success_at'], error=None)
        _RUNNING=True
        config.atomic_write_text(STATE,json.dumps(state,ensure_ascii=False))
        try:
            if updater is None:
                import refresh_classification
                updater = refresh_classification.main
            result = updater()
            state.update(running=False,last_result='ok' if result==0 else 'failed',
                         error=None if result==0 else '同花顺成员更新未完整完成；保留更新前的名单，下周再检查')
            if result==0:
                state['last_success_at']=datetime.now().isoformat(sep=' ',timespec='seconds')
        except Exception as exc:
            state.update(running=False,last_result='failed',error=str(exc))
        finally:
            config.atomic_write_text(STATE,json.dumps(state,ensure_ascii=False))
        return True
    finally:
        _RUNNING=False
        scan_lock.release()


def loop(scan_lock):
    while True:
        try:
            run_if_due(scan_lock)
        except Exception as exc:
            print(f'[MEMBERS] 周更检查失败：{exc}')
        time.sleep(300)
