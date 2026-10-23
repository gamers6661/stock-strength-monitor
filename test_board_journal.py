"""Board journal evidence boundaries; all generated files stay in a D-drive sandbox."""
import copy
from contextlib import closing
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import board_journal as J
import ui_payload


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(dir='D:/Temp/stock-monitor', prefix='journal-test-'))
        self.patcher = patch.object(J, 'ROOT', self.root)
        self.patcher.start()
        self.now = patch.object(J, 'clock', return_value=datetime(2026, 10, 22, 10, 30))
        self.now.start()

    def tearDown(self):
        self.now.stop()
        self.patcher.stop()
        import ctypes
        from ctypes import wintypes
        target = self.root.resolve()
        assert target.is_relative_to(Path('D:/Temp/stock-monitor').resolve())
        class Operation(ctypes.Structure):
            _fields_ = [('hwnd', wintypes.HWND), ('wFunc', wintypes.UINT),
                        ('pFrom', wintypes.LPCWSTR), ('pTo', wintypes.LPCWSTR),
                        ('fFlags', wintypes.WORD), ('aborted', wintypes.BOOL),
                        ('mappings', ctypes.c_void_p), ('title', wintypes.LPCWSTR)]
        op = Operation(None, 3, str(target) + '\0\0', None, 0x454, False, None, None)
        result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        if result or op.aborted:
            raise RuntimeError('Test fixture recycle failed: ' + str(result))

    def snap(self, day='2026-10-22', at='10:30:00'):
        rows = []
        for n in range(6):
            code = '60000' + str(n)
            rows.append(dict(code=code, name='样本公司' + str(n), theme_basis='同花顺个股F10',
                market_strength=dict(trend_score=80-n, emotion_score=70, emotion_parts={'R0':2}),
                emotion_relay=dict(valid=True, sealed=n==0, height=2, height_exact=True,
                    prior_exact=True, prior_sealed=n==0, prior_height=1, feedback_pct=2,
                    amount_wan=10000+n, quote_at=day+' '+at)))
        return dict(quote_capture_at=day+' '+at, session='早盘', stocks=rows, coverage_catalog=[],
                    board_catalog=[dict(id='theme:测试题材', name='测试题材', type='theme', member_codes=[r['code'] for r in rows])],
                    board_dynamics={'by_id':{'theme:测试题材':dict(lane='watch', status='转强待确认', reasons=['采样观察'], tags=[])}})

    def test_samsung_substrate_catalyst_routes_to_pcb_not_motor(self):
        event=json.loads(Path('research/board_journal_catalyst_20261022/catalyst_example.json').read_text(encoding='utf-8'))
        for name in ['电机','电机Ⅱ']:
            self.assertEqual(J.news_for(name,[],{},[event],'2026-10-22 23:59:59'),[])
        rows=J.news_for('PCB概念',[],{},[event],'2026-10-22 23:59:59')
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['match_kind'],'industry_chain')
        self.assertEqual(rows[0]['catalyst']['kind'],'capacity')
        self.assertIn('2028',rows[0]['catalyst']['timing'])
        self.assertIn('供货',rows[0]['catalyst']['timing'])
        self.assertIsNone(J.catalyst_for(event,'member'))

    def test_catalyst_uses_body_and_keeps_real_event_with_market_headline(self):
        event=dict(title='测试题材上涨',excerpt='公司今日签署长期供货协议，计划明年交付。',source='测试来源')
        result=J.catalyst_for(event,'theme_title')
        self.assertEqual(result['kind'],'order')
        self.assertIn('明年',result['timing'])
        event=dict(title='终止扩产投资项目',excerpt='公司终止扩产投资项目。',source='测试来源')
        self.assertEqual(J.catalyst_for(event,'theme_title')['kind'],'risk')

    def test_theme_name_in_market_recap_is_not_a_new_event(self):
        event={'title':'兵装重组概念短线拉升，湖南天雁涨停','text':'兵装重组概念短线拉升，湖南天雁涨停，长城军工跟涨。'}
        self.assertIsNone(J.catalyst_for(event,'theme_title'))
        event['text']+='公司公告拟收购装备资产，交易方案已披露。'
        self.assertEqual(J.catalyst_for(event,'theme_title')['kind'],'restructure')

    def test_digest_never_borrows_unrelated_catalyst(self):
        event=dict(id='digest',title='今日特别要闻',text='两国总统将签署和平协议。电机板块今日上涨。',
                   excerpt='两国总统将签署和平协议。',source='新浪财经快讯',url='https://finance.sina.cn/digest',
                   published_at='2026-10-22 10:00:00',first_seen_at='2026-10-22 10:01:00',category='财经')
        result=J.news_for('电机',[],{},[event],'2026-10-22 12:00:00')[0]
        self.assertIsNone(result['catalyst'])
        self.assertNotIn('和平协议',result['excerpt'])
        event['text']+='电机企业签署供货协议。'
        result=J.news_for('电机',[],{},[event],'2026-10-22 12:00:00')[0]
        self.assertEqual(result['catalyst']['kind'],'order')
        self.assertTrue(all('和平协议' not in p for p in result['catalyst']['points']))

    def test_policy_cooperation_and_document_dedup(self):
        events=[]
        for i in range(10):
            e=dict(id=str(i),title='上海金融监管局：探索金融合作'+str(i),
                   text='上海金融监管局印发《推动上海银行业数字金融发展的若干措施》。探索产业合作，推进数字金融。',
                   excerpt='探索银行业合作',source='新浪财经快讯',url='https://finance.sina.cn/'+str(i),
                   published_at='2026-10-22 10:00:00',first_seen_at='2026-10-22 10:01:00',category='财经')
            events.append(e)
        found=J.news_for('国有大型银行Ⅱ',[],{},events,'2026-10-22 12:00:00')
        self.assertEqual(len(found),1)
        self.assertEqual(found[0]['catalyst']['kind'],'policy')
        self.assertEqual(len(found[0]['related_reports']),9)
        events[-1]['text']=events[-1]['text'].replace('若干措施','另一项措施')
        self.assertEqual(len(J.news_for('国有大型银行Ⅱ',[],{},events,'2026-10-22 12:00:00')),2)
        self.assertIsNone(J.catalyst_for({'title':'建设国际商务合作区','text':'探索城市融合应用。'},'theme_title'))

    def test_market_investor_words_are_not_capacity_catalysts(self):
        event=dict(title='投资者关注测试题材',excerpt='股价突破前高，投资者关注后续行情。',source='测试来源')
        self.assertIsNone(J.catalyst_for(event,'theme_title'))

    def test_catalysts_are_not_crowded_out_by_market_reports(self):
        events=[]
        for i in range(10):
            events.append(dict(id=str(i),title='测试题材走高',excerpt='测试题材走高',text='测试题材走高',
                source='来源',url='https://finance.sina.cn/a',published_at='2026-10-22 11:00:00',
                first_seen_at='2026-10-22 11:01:00',category='媒体快讯'))
        events.append(dict(events[0],id='event',title='测试题材投资新建产线',text='测试题材投资新建产线。',
                           published_at='2026-10-22 10:00:00'))
        rows=J.news_for('测试题材',[],{},events,'2026-10-22 12:00:00')
        self.assertEqual(rows[0]['id'],'event')
        self.assertEqual(rows[0]['catalyst']['kind'],'capacity')

    def test_strong_gate_requires_existing_flags_same_day_and_excludes_broad(self):
        board=dict(name='比亚迪概念',type='theme',market_strength=dict(trend_strong=True,trend_at='2026-10-22 10:00'))
        self.assertFalse(J.strong_evidence(board,'2026-10-22',True,False)['eligible'])
        board['name']='测试题材'
        self.assertTrue(J.strong_evidence(board,'2026-10-22',True,False)['eligible'])
        self.assertFalse(J.strong_evidence(board,'2026-10-23',True,False)['eligible'])
        self.assertFalse(J.strong_evidence(board,'2026-10-22',False,False)['eligible'])
        self.assertFalse(J.strong_evidence(board,'2026-10-22',True,True)['eligible'])
        board['market_strength']={}
        self.assertFalse(J.strong_evidence(board,'2026-10-22',True,False)['eligible'])

    def test_roles_disjoint_with_evidence_and_no_center_without_cap(self):
        snap=self.snap()
        for i,row in enumerate(snap['stocks']):
            row['market_strength']['trend_strong']=True
            row['float_mcap']=1000-i*100
        rows=[J.stock(s,'2026-10-22') for s in snap['stocks']]
        roles=J.role_candidates(rows)
        self.assertEqual(roles['leader'][0]['code'],'600000')
        codes=[r['code'] for k in ('leader','center','followers') for r in roles[k]]
        self.assertEqual(len(codes),len(set(codes)))
        for row in rows:row['float_mcap']=None
        self.assertEqual(J.role_candidates(rows)['center'],[])
        self.assertEqual(J.role_candidates(rows,True)['leader'],[])

    def test_stale_quote_cannot_be_role_candidate(self):
        snap=self.snap()
        row=J.stock(snap['stocks'][0],'2026-10-23')
        self.assertEqual(J.role_candidates([row])['leader'],[])

    def test_missing_definition_is_explicit_not_news_as_definition(self):
        b=dict(type='theme',name='测试题材')
        self.assertIsNone(J.definition_for(b,{})['text'])
        known=dict(text='已取得的定义',source='同花顺题材定义')
        self.assertEqual(J.definition_for(b,{'测试题材':known}),known)

    def test_does_not_mutate_shared_inputs_and_ladder_is_exact(self):
        snap=self.snap(); snap['stocks'][0]['emotion_relay']['height_exact']=False
        before=copy.deepcopy(snap); model=J.build(snap,fetch_news=False,persist=False)
        self.assertEqual(snap,before)
        b=model['current']['boards']['theme:测试题材']
        self.assertEqual(b['limit_count'],1);self.assertEqual(b['unknown_height'],1)
        self.assertEqual(b['highest'],0);self.assertEqual(b['ladder'],{'unknown':['600000']})

    def test_news_requires_literal_match_safe_url_and_no_future_knowledge(self):
        event=dict(id='1',title='测试题材新进展',excerpt='测试题材相关报道',text='测试题材相关报道',
                   source='新浪财经快讯',url='https://finance.sina.cn/7x24/a',
                   published_at='2026-10-21 10:00:00',first_seen_at='2026-10-22 10:00:00',category='媒体快讯')
        J.write(self.root/'news.json.gz',{'events':[event]})
        old=J.build(self.snap(day='2026-10-21'),fetch_news=False,persist=False)
        self.assertEqual(old['current']['boards']['theme:测试题材']['news'],[])
        current=J.build(self.snap(),fetch_news=False,persist=False)
        self.assertEqual(len(current['current']['boards']['theme:测试题材']['news']),1)
        self.assertIsNone(J.safe_url('https://finance.sina.cn.evil.test/a'))
        self.assertIsNone(J.safe_url('javascript:alert(1)'))

    def test_direct_theme_news_precedes_newer_company_only_mentions(self):
        def event(identity,text,at):
            return dict(id=identity,title=text,excerpt=text,text=text,source='新浪财经快讯',
                        url='https://finance.sina.cn/7x24/'+identity,published_at=at,
                        first_seen_at='2026-10-22 10:00:00',category='媒体快讯')
        J.write(self.root/'news.json.gz',{'events':[
            event('member','样本公司0汽车销量报道','2026-10-22 10:20:00'),
            event('theme','测试题材产业新进展','2026-10-22 10:10:00')]})
        model=J.build(self.snap(),fetch_news=False,persist=False)
        b=model['current']['boards']['theme:测试题材']
        self.assertEqual(b['news'][0]['id'],'theme')
        live=J.live_news(model['current'])
        self.assertEqual(live['source_at'],model['current']['source_at'])
        self.assertEqual(live['by_board']['theme:测试题材'][0]['id'],'theme')

    def test_auction_uses_auction_quote_and_never_carries_prior_ladder(self):
        snap=self.snap(at='09:29:30');snap['session']='竞价结束'
        snap['board_catalog'][0]['member_auction']=dict(ready=True,change_pct=1.2,up_pct=80,valid_count=6,pool_count=6,coverage_pct=100)
        for row in snap['stocks']:
            row['emotion_relay']['quote_at']='2026-10-21 15:00:00'
            row['session_context']=dict(quote_valid=True,quote_at='2026-10-22 09:29:30',gap_pct=1.2)
        model=J.build(snap,fetch_news=False,persist=False)['current']
        b=model['boards']['theme:测试题材']
        self.assertEqual(model['mode'],'竞价参考')
        self.assertEqual(b['limit_count'],0)
        self.assertEqual(b['return_pct'],1.2)
        self.assertEqual(model['stocks']['600000']['change_pct'],1.2)
        self.assertFalse(model['stocks']['600000']['sealed'])

    def test_same_source_does_not_repeat_changes_and_opened_stock_leaves_ladder(self):
        first=J.build(self.snap(at='10:20:00'),fetch_news=False)
        snap=self.snap();snap['stocks'][0]['emotion_relay']['sealed']=False
        second=J.build(snap,fetch_news=False)
        b=second['current']['boards']['theme:测试题材']
        self.assertEqual(b['limit_count'],0);self.assertEqual(b['changes']['opened'],['600000'])
        third=J.build(snap,fetch_news=False)
        self.assertEqual(third['current']['boards']['theme:测试题材']['changes'],b['changes'])
        self.assertEqual(len(third['current']['boards']['theme:测试题材']['timeline']),1)

    def test_membership_change_stops_increment_comparison(self):
        J.build(self.snap(at='10:20:00'),fetch_news=False)
        snap=self.snap();snap['board_catalog'][0]['member_codes'].pop()
        model=J.build(snap,fetch_news=False)
        self.assertEqual(model['current']['boards']['theme:测试题材']['changes']['comparable'],0)

    def test_formal_close_is_not_overwritten_by_intraday_rebuild(self):
        snap=self.snap(at='15:00:00');snap.update(session='已收盘',close_daily_verified_at='2026-10-22 15:05:00')
        J.build(snap,fetch_news=False)
        J.build(self.snap(),fetch_news=False)
        saved=J.read(self.root/'days/2026-10-22.json.gz')
        self.assertTrue(saved['formal']);self.assertEqual(saved['source_at'],'2026-10-22 15:00:00')

    def test_next_day_archives_are_frozen_not_backfilled(self):
        J.build(self.snap(),fetch_news=False)
        with patch.object(J,'clock',return_value=datetime(2026,10,23,10,30)):
            model=J.build(self.snap(day='2026-10-23'),fetch_news=False)
        self.assertEqual(model['dates'],['2026-10-23','2026-10-22'])
        self.assertEqual(model['archives']['2026-10-22']['stocks']['600000']['quote_at'],'2026-10-22 10:30:00')
        self.assertNotIn('2026-10-21',model['matrix'])

    def test_publication_pins_history_details_and_offline_root(self):
        first=J.build(self.snap(),fetch_news=False)
        with patch.object(J,'clock',return_value=datetime(2026,10,23,10,30)):
            journal=J.build(self.snap(day='2026-10-23'),fetch_news=False)
        full=self.snap(day='2026-10-23');full['board_journal']=journal
        # Avoid reading unrelated optional project results.
        full['stock_activity']={'fixture':True}
        page=self.root/'dashboard.html'
        package,token=ui_payload.prepare(full,'<html><script>var DATA=/*__DATA__*/null;</script></html>',page,project_charts=False)
        summary=ui_payload.unpack(package)
        self.assertEqual(summary['board_journal']['archives'],{})
        saved=ui_payload.detail(token,'journal','2026-10-22',page)
        self.assertEqual(saved,first['current'])
        with closing(ui_payload.connect(token,page)) as con:
            restored=ui_payload.restore_full(con)
        self.assertEqual(restored['board_journal']['archives']['2026-10-22'],saved)
        with self.assertRaises(ValueError):ui_payload.detail(token,'journal','../../bad',page)


if __name__=='__main__':
    unittest.main()
