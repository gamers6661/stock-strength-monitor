"""真实成员分页不可用时保留证据，并明确未完整取得。"""
import unittest
from unittest.mock import patch
import json
from pathlib import Path
import tempfile
import datafeed

def page(index,total,*codes):
    return '<span class="page_info">%s/%s</span>'%(index,total)+''.join(
        '<a href="http://stockpage.10jqka.com.cn/%s/">成员</a>'%c for c in codes)

class BoardMembersTest(unittest.TestCase):
    def test_all_pages_read_and_deduplicated(self):
        with patch.object(datafeed,'http_get',side_effect=[page(1,2,'000001','000001'),page(2,2,'000002')]) as get:
            self.assertEqual(datafeed.fetch_ths_detail_members('881101',section='thshy'),['000001','000002'])
            self.assertIn('/thshy/detail/code/881101/page/2/',get.call_args.args[0])

    def test_empty_later_page_cannot_masquerade_as_complete(self):
        with patch.object(datafeed,'http_get',side_effect=[page(1,2,'000001'),'请登录']):
            with self.assertRaisesRegex(RuntimeError,'第2页无有效代码'):
                datafeed.fetch_ths_detail_members('881101')

    def test_partial_fetch_retains_verified_codes_with_failure_reason(self):
        with patch.object(datafeed,'http_get',side_effect=[page(1,2,'000001'),OSError('401')]):
            r=datafeed.fetch_ths_detail_members('881101',allow_partial=True)
        self.assertEqual(r['codes'],['000001'])
        self.assertFalse(r['complete'])
        self.assertIn('第2页',r['error'])

    def test_wrong_page_and_repeated_response_rejected(self):
        for second in (page(1,2,'000001'),page(2,2,'000001')):
            with patch.object(datafeed,'http_get',side_effect=[page(1,2,'000001'),second]):
                with self.assertRaises(RuntimeError):
                    datafeed.fetch_ths_detail_members('881101')

    def test_page_cap_does_not_claim_full_coverage(self):
        with patch.object(datafeed,'http_get',return_value=page(1,61,'000001')):
            with self.assertRaisesRegex(RuntimeError,'超出读取范围'):
                datafeed.fetch_ths_detail_members('881101')

    def test_failed_industry_preserves_old_verified_members_and_marks_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'members.json'
            p.write_text(json.dumps({'map':{'000001':['种植业与林业']},
                'stat':{'member_source':'ths-industry-detail-v1'}}),encoding='utf-8')
            with patch.object(datafeed.config,'THS_INDUSTRY_MEMBER_CACHE',p), \
                 patch.object(datafeed,'fetch_ths_industry_catalog',return_value={'detail':{'881101':'种植业与林业'}}), \
                 patch.object(datafeed,'fetch_ths_index_members',side_effect=OSError('source unavailable')), \
                 patch.object(datafeed,'fetch_ths_detail_members',return_value={'codes':['000002'],'complete':False,'error':'第2页401'}), \
                 patch.object(datafeed,'_source_mark'):
                r=datafeed.build_ths_industry_members(force=True,progress=False)
            self.assertEqual(set(r['map']),{'000001','000002'})
            self.assertEqual(r['stat']['failed'],['种植业与林业'])
            self.assertEqual(r['stat']['partial'],['种植业与林业'])
            self.assertIn('401',r['stat']['errors']['种植业与林业'])

if __name__=='__main__':
    unittest.main()
