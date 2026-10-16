"""同源完整成员名单：代码、名称、声明总数、截断和重复均须校验。"""
import json
import unittest
from unittest.mock import patch
import datafeed as D


def raw(codes, total=None, name='电池', code='881281', limit=1000):
    obj=dict(block=dict(name=name,subcodeCount=len(codes) if total is None else total),
             items=[{'5':c} for c in codes])
    return f'quotebridge_v2_blockrank_{code}_199112_d{limit}('+json.dumps(obj)+')'


class CompleteMembersTest(unittest.TestCase):
    def test_complete_count_and_deduplicated_members(self):
        with patch.object(D,'http_get',return_value=raw(['600241','000009'])):
            self.assertEqual(D.fetch_ths_index_members('881281','电池'),['000009','600241'])

    def test_wrong_identity_rejected(self):
        for response in (raw(['600241'],name='锂电池概念'),raw(['600241'],code='881101')):
            with patch.object(D,'http_get',return_value=response),self.assertRaises(RuntimeError):
                D.fetch_ths_index_members('881281','电池')

    def test_duplicate_invalid_and_missing_rows_rejected(self):
        for response in (raw(['600241','600241']),raw(['not-a-stock']),raw(['600241'],total=2)):
            with patch.object(D,'http_get',return_value=response),self.assertRaises(RuntimeError):
                D.fetch_ths_index_members('881281','电池')

    def test_large_count_refetches_full_declared_size(self):
        codes=[str(100000+i) for i in range(1001)]
        with patch.object(D,'http_get',side_effect=[raw(codes[:1000],total=1001),raw(codes,limit=1001)]) as get:
            self.assertEqual(len(D.fetch_ths_index_members('881281','电池')),1001)
            self.assertIn('/d1001.js',get.call_args.args[0])

    def test_server_cap_cannot_masquerade_as_complete(self):
        codes=[str(100000+i) for i in range(1000)]
        with patch.object(D,'http_get',side_effect=[raw(codes,total=1200),raw(codes,total=1200,limit=1200)]),self.assertRaises(RuntimeError):
            D.fetch_ths_index_members('881281','电池')

    def test_moving_total_during_fetch_requires_recheck(self):
        codes=[str(100000+i) for i in range(1000)]
        with patch.object(D,'http_get',side_effect=[raw(codes,total=1001),raw(codes,total=1002,limit=1001)]),self.assertRaises(RuntimeError):
            D.fetch_ths_index_members('881281','电池')


if __name__=='__main__':unittest.main()
