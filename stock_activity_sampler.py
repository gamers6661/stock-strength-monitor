"""个股页全池轻量采样及独立投影发布；不触发全站评分与分类更新。"""
import json
import logging
import os
import time
from contextlib import contextmanager
from datetime import datetime

import config
import datafeed
import intraday_path

INTERVAL = 120


def directory():
    return config.CACHE_DIR / 'stock_activity_samples'


def sampling_time(now):
    minute = now.hour * 60 + now.minute
    return now.weekday() < 5 and (570 <= minute <= 690 or 780 <= minute < 900)


@contextmanager
def owner():
    directory().mkdir(parents=True, exist_ok=True)
    with (directory() / 'sampler.lock').open('a+b') as stream:
        if stream.seek(0, os.SEEK_END) == 0:
            stream.write(b'0'); stream.flush()
        stream.seek(0)
        acquired = False
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except OSError:
            pass
        try:
            yield acquired
        finally:
            if acquired:
                stream.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def capture_once():
    """8个400只串行批次；单批不重试，不触发备用源和逐股补采。"""
    started = time.monotonic()
    at=datetime.now()
    if not sampling_time(at):
        return dict(captured_at=str(at),skipped=True,reason='非连续采样时段；收盘只回放本地终值，不请求行情')
    pool = json.loads(config.POOL_CACHE.read_text(encoding='utf8'))
    codes = sorted(c for c in pool if len(c) == 6 and c.isdigit())
    if not codes:
        raise ValueError('本地股票池为空')
    quotes = datafeed.tencent_quotes(codes)
    at = datetime.now()
    import intraday
    valid = 0
    for q in quotes.values():
        source = intraday.parse_quote_timestamp(q.get('quote_at') or q.get('ts'))
        q['quote_at'] = source.isoformat(sep=' ',timespec='seconds') if source else None
        if (source and source.date() == at.date()
                and -config.INTRADAY['max_quote_future_seconds'] <= (at-source).total_seconds() <= config.INTRADAY['max_quote_age_seconds']
                and (q.get('price') or 0) > 0 and (q.get('amount_wan') or 0) > 0):
            valid += 1
    status = dict(captured_at=str(at), expected=len(codes), received=len(quotes), valid=valid,
                  seconds=round(time.monotonic()-started,3), pid=os.getpid())
    if valid < len(codes)*.8:
        status['error'] = '采样有效覆盖不足80%，不写入可比路径'
    else:
        intraday_path.save_acquisition(directory(), quotes, at, datafeed.session_label(at))
        config.atomic_write_text(directory()/'latest.json',json.dumps(dict(captured_at=str(at),session=datafeed.session_label(at),quotes=quotes),ensure_ascii=False,separators=(',',':')))
        # 个股页独立发布，不等待全站重算；失败不丢弃已经落盘的原始报价。
        if config.SNAPSHOT_JSON.exists():
            try:
                import stock_activity
                projection_started = time.monotonic()
                model = stock_activity.refresh_projection()
                status['result_version'] = model.get('result_version')
                status['published_source_at'] = model.get('source_at')
                status['projection_seconds'] = round(time.monotonic()-projection_started,3)
                published = datetime.now()
                status['published_at'] = str(published)
                source = stock_activity.stamp(model.get('source_at'))
                status['quote_age_at_publication_seconds'] = round((published-source).total_seconds(),3) if source else None
            except Exception:
                logging.exception('个股V2.1独立发布失败，保留最后结果并等待下一次采样')
                status['projection_error'] = '本页计算失败；原始采样已保存'
    status['total_seconds'] = round(time.monotonic()-started,3)
    config.atomic_write_text(directory()/'status.json',json.dumps(status,ensure_ascii=False))
    return status


def loop(until_close=False):
    """单独计时，不等待全站扫描锁；跨进程只允许一个采样者。"""
    while True:
        with owner() as acquired:
            if acquired:
                due = time.monotonic()
                finalized_day=None
                while True:
                    now = datetime.now()
                    if until_close and now.weekday()>=5:return
                    if now.weekday()<5 and now.hour>=15 and finalized_day!=str(now.date()):
                        try:
                            import stock_activity
                            model=stock_activity.refresh_projection()
                            if model.get('close_finalized') and model.get('day')==str(now.date()):
                                finalized_day=str(now.date())
                                if until_close:return
                        except Exception:
                            logging.exception('收盘本地回放未完成，保留最后结果；不再请求行情')
                    if sampling_time(now) and time.monotonic() >= due:
                        try:
                            status = capture_once()
                            logging.info('个股强度独立采样 %s',status)
                        except Exception:
                            logging.exception('个股强度独立采样失败；保留已有真实记录')
                        due = max(due+INTERVAL,time.monotonic()+1)
                    time.sleep(1 if sampling_time(now) else 20)
            elif until_close and datetime.now().hour*60+datetime.now().minute >= 900:
                return
        time.sleep(5)


if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO)
    loop(until_close='--until-close' in sys.argv)
