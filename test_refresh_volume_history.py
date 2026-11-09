"""Optional same-time volume history must not pause prices or the main model."""
import copy
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import stock_selection_intraday as I

class VolumeHistoryRecoveryTests(unittest.TestCase):
    def data(self):
        model={'day':'2026-10-27','items':{'000001':{'score':87.0,'eligible':True,
            'quote':{'price':11.47,'at':'2026-10-27 15:00:00'},
            'intraday':{'available':True,'at':'2026-10-27 15:00:00'}}}}
        source={'stocks':[{'code':'000001','volume_shou':204.,
            'price_basis':'raw','price_basis_source':'tencent_realtime_quote'}]}
        days=['2026-10-20','2026-10-21','2026-10-22','2026-10-23','2026-10-26']
        folder=Mock();folder.exists.return_value=True;folder.as_posix.return_value='D:/test-reference.db'
        return model,source,days,folder
    def test_readonly_recovery_error_only_disables_optional_ratio(self):
        model,source,days,folder=self.data();core=copy.deepcopy(model['items']['000001'])
        with patch.object(I,'path',return_value=folder),patch.object(I.sqlite3,'connect',
                side_effect=sqlite3.OperationalError('attempt to write a readonly database')):
            result=I.attach(model,source,days)
        item=result['items']['000001']
        self.assertEqual(item['score'],core['score'])
        self.assertEqual(item['eligible'],core['eligible'])
        self.assertEqual(item['quote'],core['quote'])
        self.assertTrue(item['intraday']['available'])
        self.assertIsNone(item['intraday']['volume_ratio_same_time'])
        self.assertEqual(item['intraday']['same_time_volume_reason'],'历史累计量暂不可用，暂停量比判断')
        self.assertIn('OperationalError',result['same_time_volume_error'])
    def test_healthy_history_keeps_same_source_median_ratio(self):
        model,source,days,folder=self.data();con=Mock()
        con.execute.return_value=[(d,15*3600,'000001',100.+i) for i,d in enumerate(days)]
        with patch.object(I,'path',return_value=folder),patch.object(I.sqlite3,'connect',return_value=con):
            result=I.attach(model,source,days)
        self.assertEqual(result['items']['000001']['intraday']['volume_ratio_same_time'],2.)
        self.assertEqual(result['items']['000001']['intraday']['same_time_reference_days'],5)
        self.assertEqual(result['items']['000001']['score'],87.)
        self.assertNotIn('same_time_volume_error',result)
        con.close.assert_called_once()
if __name__=='__main__':unittest.main()
