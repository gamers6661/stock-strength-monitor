"""停牌观察与新报价风险名称的回归检查。"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import config
import datafeed
import scoring


class TradingStatusTests(unittest.TestCase):
    def test_pool_keeps_no_trade_code_for_future_recovery_checks(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            quotes = {
                "600293": {"code": "600293", "name": "三峡新材", "price": 0,
                           "amount_wan": 0, "volume_shou": 0},
                "600001": {"code": "600001", "name": "测试股票", "price": 10,
                           "amount_wan": 100, "volume_shou": 100},
            }
            with patch.object(config, "POOL_CACHE", root / "pool.json"), \
                 patch.object(config, "POOL_META_CACHE", root / "pool_meta.json"), \
                 patch.object(datafeed, "_gen_candidate_codes", return_value=list(quotes)), \
                 patch.object(datafeed, "realtime_quotes", return_value=quotes), \
                 patch.object(datafeed, "load_list_dates", return_value={}), \
                 patch.object(datafeed, "in_trading_session", return_value=True):
                pool = datafeed.build_pool(force=True)
            self.assertIn("600293", pool)
            self.assertEqual(pool.keys(), json.loads((root / "pool.json").read_text(encoding="utf-8")).keys())

    def test_fresh_st_name_overrides_cached_plain_name(self):
        pool = {
            "600363": {"name": "联创光电", "board_type": "sh_main"},
            "600001": {"name": "测试股票", "board_type": "sh_main"},
        }
        quotes = {
            "600363": {"name": "ST联光", "price": 13.0},
            "600001": {"name": "测试股票", "price": 10.0},
        }
        merged, excluded = scoring._merge_current_pool_quotes(pool, quotes)
        self.assertEqual({"600363": "ST联光"}, excluded)
        self.assertEqual(["600001"], list(merged))
        self.assertEqual("sh_main", merged["600001"]["board_type"])


if __name__ == "__main__":
    unittest.main()
