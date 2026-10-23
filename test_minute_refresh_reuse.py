import unittest,tempfile,time,threading
from pathlib import Path
from datetime import datetime
from concurrent.futures import Future
from unittest.mock import patch
import close_monitor as C
import config
from test_close_monitor import minute_bars


class MinuteReuseTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory()
  self.dir=Path(self.temp.name)
  self.day="2026-10-21"
  self.code="000001"
  self.quote={self.code:self.day+" 10:00:00"}
  self.bars=minute_bars(datetime.fromisoformat(self.day+" 09:31"),30)
  self.p=patch.object(C,"MINUTE_DIR",self.dir);self.p.start()
  C._MINUTE_PENDING.clear()
 def tearDown(self):
  if C._MINUTE_POOL is not None:
   C._MINUTE_POOL.shutdown(wait=True,cancel_futures=True);C._MINUTE_POOL=None
  C._MINUTE_PENDING.clear();self.p.stop();self.temp.cleanup()
 def test_prefetch_reuses_inflight_request(self):
  gate=threading.Event()
  def fetch(*args):gate.wait(.2);return self.bars
  with patch.object(C,"_minute_bars",side_effect=fetch) as fetcher:
   C.prefetch_minutes([self.code],self.day,self.quote)
   gate.set()
   out=C._get_minutes([self.code],self.day,self.quote)
   self.assertEqual(out[self.code],self.bars)
   self.assertEqual(fetcher.call_count,1)
 def test_timeout_retains_running_result_for_next_consumer(self):
  started=threading.Event();gate=threading.Event()
  def fetch(*args):started.set();gate.wait(.3);return self.bars
  with patch.object(C,"_minute_bars",side_effect=fetch) as fetcher,patch.dict(config.MA_TREND,minute_fetch_seconds=.01):
   C.prefetch_minutes([self.code],self.day,self.quote);self.assertTrue(started.wait(1))
   stats={};C._get_minutes([self.code],self.day,self.quote,stats)
   self.assertEqual(stats["timeout"],1)
   gate.set()
   future=C._MINUTE_PENDING[(str(self.dir),self.day,self.code)]
   future.result(timeout=1)
   result=C._get_minutes([self.code],self.day,self.quote)
   self.assertEqual(result[self.code],self.bars);self.assertEqual(fetcher.call_count,1)
 def test_prior_round_late_result_is_revalidated_for_later_quote(self):
  future=Future();future.set_result((self.bars,self.day+" 10:00:05"))
  C._MINUTE_PENDING[(str(self.dir),self.day,self.code)]=future
  later=minute_bars(datetime.fromisoformat(self.day+" 09:31"),35)
  with patch.object(C,"_minute_bars",return_value=later) as fetcher:
   result=C._get_minutes([self.code],self.day,{self.code:self.day+" 10:05:00"})
  self.assertEqual(fetcher.call_count,1);self.assertEqual(result[self.code],later)
 def test_prefetched_result_is_saved_when_no_new_request_needed(self):
  f=Future();f.set_result((self.bars,self.day+" 10:00:10"))
  C._MINUTE_PENDING[(str(self.dir),self.day,self.code)]=f
  with patch.object(C,"_minute_bars") as fetcher:
   result=C._get_minutes([self.code],self.day,self.quote)
  fetcher.assert_not_called()
  self.assertEqual(C._load_minute_cache(self.day)["stocks"],result)
 def test_cache_from_other_day_is_not_used(self):
  f=Future();f.set_result((self.bars,self.day+" 10:00:10"))
  C._MINUTE_PENDING[(str(self.dir),"2026-10-20",self.code)]=f
  with patch.object(C,"_minute_bars",return_value=self.bars) as fetcher:
   C._get_minutes([self.code],self.day,self.quote)
  self.assertEqual(fetcher.call_count,1)
  self.assertNotIn((str(self.dir),"2026-10-20",self.code),C._MINUTE_PENDING)

 def test_speculative_queue_does_not_block_current_codes(self):
  unused=Future()
  C._MINUTE_PENDING[(str(self.dir),self.day,"000002")]=unused
  with patch.object(C,"_minute_bars",return_value=self.bars):
   C._get_minutes([self.code],self.day,self.quote)
  self.assertTrue(unused.cancelled())
