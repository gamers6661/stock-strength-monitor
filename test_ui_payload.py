"""Transport boundaries must preserve facts, versions and export selection."""
import copy
import gzip
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import shutil
from unittest.mock import patch

import config
import ui_payload


class PayloadTests(unittest.TestCase):
    def test_numeric_parameter_keys_match_persisted_json_and_browser_objects(self):
        data={'parameters':{5:.1,10:.2,20:.3},'other':{None:1,True:2,1.5:3}}
        expected=json.loads(ui_payload.dumps(data))
        self.assertEqual(ui_payload.unpack(ui_payload.pack(data)),expected)
        # Older generations may contain numeric keys in their shared dictionary.
        self.assertEqual(ui_payload.unpack({'format':ui_payload.VERSION,'keys':[5],
            'strings':[],'shapes':[[0]],'root':['^0',.1]}),{'5':.1})

    def test_live_in_memory_parameters_and_frozen_details_have_the_same_summary(self):
        with TemporaryDirectory() as tmp:
            page=Path(tmp)/'dashboard.html'
            full={'stocks':[],'runtime_contract':{},'strength_model':{'parameters':{5:.1,10:.2}}}
            packet,token=ui_payload.prepare(full,'var DATA=/*__DATA__*/null;',page)
            self.assertEqual(ui_payload.unpack(packet),ui_payload.summary(ui_payload.full(token,page),token))

    def test_lossless_dictionary_pack_handles_marker_collisions(self):
        data = {'<name>': '种植业与林业', 'b': ['^0', '~0', -1, True, None, {}, []],
                'nested': {'string': '\x01literal', 'float': 1.2345, 'short': '中'}}
        self.assertEqual(ui_payload.unpack(ui_payload.pack(data)), data)
        self.assertNotIn('</script>', config.script_json(ui_payload.pack({'s': '</script>'})))

    def test_generations_pin_details_and_expire_without_falling_forward(self):
        with TemporaryDirectory() as tmp:
            page = Path(tmp) / 'dashboard.html'
            full = {'stocks': [{'code': '600241', 'name': '时代万恒', 'price': 10, 'k': [1, 2, 3],
                                'theme_relations': [{'name': '电池'}], 'intraday_path': {'state': '保留', 'recent': [1]}}],
                    'board_catalog': [{'id': 'industry:电池', 'members': [{'code': '600241', 'name': '时代万恒', 'change_pct': 2}],
                                       'member_codes': ['600241']}], 'runtime_contract': {}}
            original = copy.deepcopy(full)
            packet, token = ui_payload.prepare(full, 'var DATA=/*__DATA__*/null;', page)
            brief = ui_payload.unpack(packet)
            self.assertEqual(brief['stocks'][0]['price'], 10)
            self.assertEqual(brief['stocks'][0]['intraday_path'], {'state': '保留'})
            self.assertEqual(brief['board_catalog'][0]['member_codes'], ['600241'])
            self.assertEqual(ui_payload.detail(token, 'stock', '600241', page), original['stocks'][0])
            self.assertEqual(gzip.decompress(ui_payload.blob(token, 'summary.gz', page)),
                             ui_payload.blob(token, 'summary', page))
            ui_payload.activate(token, page)
            full['stocks'][0]['price'] = 11
            _, newer = ui_payload.prepare(full, 'var DATA=/*__DATA__*/null;', page)
            ui_payload.activate(newer, page)
            self.assertEqual(ui_payload.detail(token, 'stock', '600241', page)['price'], 10)
            self.assertEqual(ui_payload.detail(newer, 'stock', '600241', page)['price'], 11)
            full['stocks'][0]['price'] = 12
            _, third = ui_payload.prepare(full, 'var DATA=/*__DATA__*/null;', page)
            ui_payload.activate(third, page)
            with self.assertRaises(LookupError):
                ui_payload.detail(token, 'stock', '600241', page)
            with self.assertRaises(ValueError):
                ui_payload.detail('../outside', 'stock', '600241', page)

    def test_export_rejects_duplicate_or_noncode_selections(self):
        with self.assertRaises(ValueError):
            ui_payload.export_csv('0' * 24, ['600241', '600241'], {})
        with self.assertRaises(ValueError):
            ui_payload.export_csv('../outside', ['600241'], {})

    def test_export_uses_frozen_formatter_and_requested_order(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('ui_payload.py', 'ui_client.js', 'csv_export.js', 'csv_runner.js', 'stock_list_fields.json'):
                shutil.copy2(config.ROOT / name, root / name)
            data = {'stocks': [{'code': '600241', 'name': '时代万恒'}, {'code': '603867', 'name': '新华股份'}],
                    'generated_at': '2026-10-09 15:00:00', 'runtime_contract': {}}
            with patch.object(config, 'ROOT', root):
                _, token = ui_payload.prepare(data, '/*__DATA__*/null', root / 'dashboard.html')
                # Changes after publication cannot change this generation's CSV format.
                (root / 'csv_export.js').write_text('throw new Error("new formatter");', encoding='utf-8')
                result = ui_payload.export_csv(token, ['603867', '600241'], {}).decode('utf-8-sig').splitlines()
                self.assertTrue(result[1].startswith('"603867","新华股份"'))
                self.assertTrue(result[2].startswith('"600241","时代万恒"'))
                # Existing 228 columns retain their meaning; V1 only appends 11 radar columns.
                import csv
                parsed=list(csv.reader(result))
                self.assertEqual(len(parsed[0]),239)
                self.assertEqual(parsed[0][228:230],['雷达规则版本','雷达数据版本'])
                self.assertEqual(parsed[1][229],token)
                empty=list(csv.reader(ui_payload.export_csv(token,[],{}).decode('utf-8-sig').splitlines()))
                self.assertEqual(len(empty),1)
                self.assertEqual(empty[0],parsed[0])


    def test_current_scope_uses_backend_focus_not_event_confirmation(self):
        from test_market_strength import fixture,run
        from test_market_strength_integration import render
        f=fixture();q=f[1];code=next(iter(q));q[code].update(price=110.,open=100.,high=110.,low=100.,change_pct=10.)
        run(f);result=render(f[0],"msUpdate('stocks','scope','focus');")
        self.assertEqual(result['ids'],f[0]['market_strength']['stocks']['focus'])
        self.assertIn(code,result['ids'])

if __name__ == '__main__':
    unittest.main()
