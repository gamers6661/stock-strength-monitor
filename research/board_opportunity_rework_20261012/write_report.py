# -*- coding: utf-8 -*-
import hashlib,json,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
OUTPUT=ROOT/'output/playwright/board-opportunity-rework-20261012'
def result(name):
    raw=(OUTPUT/name).read_text(encoding='utf-8-sig')
    return json.JSONDecoder().raw_decode(raw.split('### Result',1)[1].lstrip())[0]
publish=json.loads((HERE/'publish_evidence.json').read_text(encoding='utf-8'))
browser=json.loads((HERE/'browser_evidence.json').read_text(encoding='utf-8'))
ime=result('verify_ime.txt');note=result('verify_status_note.txt');before=result('reproduce_before.txt')
assert publish['generation']==browser['generation']==note['generation']
assert before['exportAction']=="exportBoardOpportunities('industry')" and before['visibleBoards']==['theme:短剧游戏']
assert before['disabledFixedSort']
assert not ime['pageErrors'] and all(ime['checks'].values())
assert 'OK' in (HERE/'check_dashboard.txt').read_text(encoding='utf-8-sig')
assert 'OK pid=' in (HERE/'check_live_service.txt').read_text(encoding='utf-8-sig')
assert 'Ran 40 tests' in (HERE/'special_tests.txt').read_text(encoding='utf-8-sig')
assert hashlib.sha256((ROOT/'dashboard_template.html').read_bytes()).hexdigest()==publish['after_sha256']
def link(path,label):return f'[{label}]({path.as_posix()})'
report=f'''# 板块机会页面返工验收

本轮实际修改源文件仅 `{ROOT/'dashboard_template.html'}`，已发布到实际 HTTP 页面。后端规则、阈值及机会计算结果保持原口径。当前服务PID {publish['pid']}，页面代次 `{publish['generation']}`，数据版本 `{publish['data_version']}`。

## 修复结果

1. 工具栏切换时完整替换按钮，同步文字、事件、禁用状态及按钮结构。搜索框和父节点保持不动，保留中文输入、焦点与选区。
2. 题材／行业切换后导出绑定当前类型；搜索自动切换类型、独立题材页面也一致。卡片和导出共用排序函数，机会固定排序及原指数两种排序分别沿用。
3. 按本次要求隐藏机会详情中的指标审计表、数值门槛、逐项通过／不通过、成员资格审计和确认轮数；后台数据及JSON导出字段继续保留，页面只展示结果说明和来源时间。
4. “当前未入选”标签可点击查看解释，详情直接展示：{note['card_note']}

## 验证

修改前已在实际页面复现：页面仅显示题材“短剧游戏”，导出事件却为 `exportBoardOpportunities('industry')`；切到指数筛选后仍是禁用“机会固定排序”。

修改后12次实际JSON下载逐项核对类型、IDs、顺序、成员名单和完整机会对象；当前题材导出仅“短剧游戏”。6次指数排序动作与实际卡片顺序一致；机会→指数→机会、行业↔题材反复切换通过。详情判定表0张，卡片点击解释通过；浏览器JS错误0。

中文拼音真实组合输入（CDP）、选择提交、粘贴自动切换板块类型、清空搜索、焦点及选区保留均通过。

`python -B -X utf8 -m unittest test_board_opportunity`：40项通过；`python -B -X utf8 check_dashboard.py`、`python -B -X utf8 check_live_service.py`及模板 `node --check` 均通过。本轮未重跑全套测试；UI切换由实际浏览器回归验证。

从已有快照投影发布，核验磁盘快照未变化、机会结果未变化、日线记录哈希未变化，HTTP模型与快照一致；未推进确认次数。Python服务代码未改，页面模板由发布过程重新读取，无需重启服务。

## 文件与证据

- {link(HERE/'before/dashboard_template.html','修改前模板备份')} / {link(HERE/'before/snapshot.json','实施前快照')} / {link(HERE/'before/status.json','实施前服务状态')}
- {link(HERE/'dashboard_template.html.diff','完整源文件差异')}
- {link(HERE/'publish_evidence.json','发布与结果不变证据')}
- {link(HERE/'browser_evidence.json','切换、排序、下载核对证据')}
- {link(HERE/'special_tests.txt','40项专项测试')} / {link(HERE/'check_dashboard.txt','看板检查')} / {link(HERE/'check_live_service.txt','服务检查')}
- {link(OUTPUT/'verify_ime.txt','中文输入回归')} / {link(OUTPUT/'verify_status_note.txt','卡片解释回归')}

## 实际HTTP截图

- {link(OUTPUT/'theme-current-export.png','题材当前机会（短剧游戏）')}
- {link(OUTPUT/'index-sorting-restored.png','切回指数后的排序工具栏')}
- {link(OUTPUT/'detail-simplified.png','移除数值判定后的简洁详情')}
- {link(OUTPUT/'card-status-explanation.png','当前未入选的卡片解释')}
'''
(HERE/'返工验收.md').write_text(report,encoding='utf-8')
print(json.dumps({'source_files':1,'actual_exports':12,'sort_actions':6,'rules_unchanged':True,'report':str(HERE/'返工验收.md')},ensure_ascii=False))
