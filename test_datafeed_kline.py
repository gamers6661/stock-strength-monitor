"""腾讯除权除息日K线不能被非数值成交额字段整行丢弃。"""
import json
import unittest
from unittest.mock import patch

import datafeed
import config


class TencentKlineTest(unittest.TestCase):
    def test_dividend_metadata_keeps_price_volume_bar(self):
        payload = {"data": {"sz000009": {"qfqday": [
            ["2026-08-26", "7.10", "7.20", "7.25", "7.08", "1000", "7200"],
            ["2026-08-27", "7.20", "7.25", "7.25", "7.11", "146922",
             {"fh_sh": "0.3", "cqr": "2026-08-27"}],
        ]}}}
        with patch.object(datafeed, "http_get", return_value=json.dumps(payload)):
            rows = datafeed.fetch_kline("000009", days=2)
        self.assertEqual([row["date"] for row in rows], ["2026-08-26", "2026-08-27"])
        self.assertEqual(rows[0]["amount"], 7200)
        self.assertEqual(rows[1]["amount"], 0)
        self.assertEqual(rows[1]["close"], 7.25)


class EmptyKlineRetryTest(unittest.TestCase):
    def setUp(self):
        self.settings=patch.dict(config.KLINE,dict(hosts=['https://example.invalid/kline'],empty_retries=1,request_budget=1,request_timeout=.1))
        self.cooldown=patch.dict(datafeed._KLINE_HOST_COOLDOWN,{},clear=True)
        self.settings.start();self.cooldown.start();self.addCleanup(self.settings.stop);self.addCleanup(self.cooldown.stop)
    def reply(self,rows):return json.dumps(dict(code=0,data={'sz000001':dict(qfqday=rows)}))
    def test_empty_stock_is_requested_once_more_then_recovery_returns_real_bars(self):
        empty=self.reply([]);good=self.reply([['2026-10-14','10','11','11','9','100']])
        with patch.object(datafeed,'http_get',side_effect=[empty,good]) as get:
            bars=datafeed.fetch_kline('000001',days=5)
        self.assertEqual(get.call_count,2);self.assertEqual(bars[-1]['close'],11)
        self.assertEqual(get.call_args_list[0].args,get.call_args_list[1].args)
        self.assertTrue(all(c.kwargs['retry']==0 for c in get.call_args_list))
    def test_two_genuine_empty_responses_stop_without_infinite_retries(self):
        with patch.object(datafeed,'http_get',return_value=self.reply([])) as get:
            self.assertEqual(datafeed.fetch_kline('000001'),[])
        self.assertEqual(get.call_count,2);self.assertEqual(datafeed._KLINE_HOST_COOLDOWN,{})
    def test_empty_retry_cannot_extend_original_request_budget(self):
        clock=[0.]
        def get(*args,**kwargs):clock[0]=5.;return self.reply([])
        with patch.object(datafeed.time,'monotonic',side_effect=lambda:clock[0]),patch.object(datafeed,'http_get',side_effect=get) as fetch:
            with self.assertRaises(TimeoutError):datafeed.fetch_kline('000001')
        self.assertEqual(fetch.call_count,1)
    def test_malformed_data_is_an_error_not_two_empty_suspension_evidence(self):
        for payload in [dict(code=-1,data={}),dict(code=0,data={'sz000001':dict(qfqday=[['broken']])})]:
            datafeed._KLINE_HOST_COOLDOWN.clear()
            with patch.object(datafeed,'http_get',return_value=json.dumps(payload)) as get:
                with self.assertRaises(ValueError):datafeed.fetch_kline('000001')
            self.assertEqual(get.call_count,1)


if __name__ == "__main__":
    unittest.main()
