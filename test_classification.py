"""个股 F10 归属优先，成员图只作交叉核对或缺失标记。"""
import unittest

import classification


class ClassificationTest(unittest.TestCase):
    def test_f10_order_controls_stock_labels_and_audits_disagreement(self):
        mapping = {'601138': {'themes': ['同花顺出海50', '英伟达概念'],
                              'industry': ['电子']}}
        profiles = {'601138': {'concepts': ['共封装光学(CPO)', '英伟达概念',
                                            '同花顺出海50'],
                               'industry': ['电子', '消费电子'],
                               'fetched_at': '2026-09-24'}}
        result, stat = classification.reconcile(
            mapping, profiles, {'names': ['共封装光学(CPO)', '英伟达概念', '同花顺出海50']}, mapping)
        row = result['601138']
        self.assertEqual(row['themes'], ['共封装光学(CPO)', '英伟达概念'])
        self.assertEqual(row['industry'], ['消费电子', '电子'])
        self.assertEqual(row['f10_only_themes'], ['共封装光学(CPO)'])
        self.assertEqual(row['theme_basis'], '同花顺个股F10')
        self.assertEqual(stat['f10_confirmed'], 1)

    def test_missing_f10_is_explicitly_pending(self):
        result, stat = classification.reconcile(
            {'000001': {'themes': ['银行'], 'industry': ['银行']}}, {}, {}, ['000001'])
        self.assertEqual(result['000001']['themes'], ['银行'])
        self.assertIn('待F10核对', result['000001']['theme_basis'])
        self.assertEqual(stat['member_pending'], 1)


if __name__ == '__main__':
    unittest.main()
