"""每周一次、交易期避让和失败保留/不密集重试的行为验证。"""
from datetime import datetime,timedelta
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import weekly_members as W


class WeeklyMembersTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.now=datetime(2026,10,9,16,0)
        self.lock=threading.Lock()
        for attribute,file in [('STATE','state.json')]:
            p=patch.object(W,attribute,self.root/file);p.start();self.addCleanup(p.stop)
        for attribute,file in [('THS_MEMBER_CACHE','concept.json'),('THS_INDUSTRY_MEMBER_CACHE','industry.json')]:
            path=self.root/file;path.write_text('verified old members',encoding='utf-8')
            os.utime(path,(self.now.timestamp(),self.now.timestamp()))
            p=patch.object(W.config,attribute,path);p.start();self.addCleanup(p.stop)

    def test_existing_cache_waits_seven_days_without_network(self):
        calls=[]
        self.assertFalse(W.run_if_due(self.lock,self.now+timedelta(days=6),lambda:calls.append(1)))
        self.assertEqual(calls,[])
        self.assertTrue(W.run_if_due(self.lock,self.now+timedelta(days=7),lambda:0))

    def test_daily_restart_and_scan_do_not_repeat_weekly_update(self):
        due=self.now+timedelta(days=7)
        calls=[]
        def update():calls.append(1);return 0
        self.assertTrue(W.run_if_due(self.lock,due,update))
        for day in range(7):self.assertFalse(W.run_if_due(self.lock,due+timedelta(days=day),update))
        self.assertEqual(calls,[1])
        self.assertTrue(W.run_if_due(self.lock,due+timedelta(days=7),update))

    def test_failed_attempt_does_not_retry_each_scan_or_rewrite_members(self):
        due=self.now+timedelta(days=7)
        old=W.config.THS_MEMBER_CACHE.read_text(encoding='utf-8')
        self.assertTrue(W.run_if_due(self.lock,due,lambda:1))
        self.assertEqual(W.status(due.timestamp())['last_result'],'failed')
        self.assertFalse(W.run_if_due(self.lock,due+timedelta(minutes=5),lambda:0))
        self.assertEqual(W.config.THS_MEMBER_CACHE.read_text(encoding='utf-8'),old)

    def test_auction_lunch_market_and_close_capture_are_avoided(self):
        for hour,minute in [(8,59),(9,15),(11,30),(12,30),(13,0),(15,0),(15,14)]:
            due=(self.now+timedelta(days=14)).replace(hour=hour,minute=minute)
            self.assertFalse(W.run_if_due(self.lock,due,lambda:0))
        due=(self.now+timedelta(days=14)).replace(hour=15,minute=15)
        self.assertTrue(W.run_if_due(self.lock,due,lambda:0))

    def test_busy_scan_is_not_interrupted(self):
        self.lock.acquire()
        try:self.assertFalse(W.run_if_due(self.lock,self.now+timedelta(days=7),lambda:0))
        finally:self.lock.release()
        self.assertFalse(W.STATE.exists())

    def test_exception_releases_lock_and_records_attempt(self):
        def fail():raise OSError('source unavailable')
        due=self.now+timedelta(days=7)
        self.assertTrue(W.run_if_due(self.lock,due,fail))
        self.assertFalse(self.lock.locked())
        self.assertEqual(W.status(due.timestamp())['last_result'],'failed')

    def test_first_refresh_without_cache_is_scheduled_after_close(self):
        W.config.THS_MEMBER_CACHE.unlink();W.config.THS_INDUSTRY_MEMBER_CACHE.unlink()
        noon=self.now.replace(hour=12)
        s=W.status(noon.timestamp())
        self.assertTrue(s['due'])
        self.assertEqual(s['next_update_at'],'2026-10-09 15:15:00')
        self.assertFalse(W.run_if_due(self.lock,noon,lambda:0))


if __name__=='__main__':unittest.main()
