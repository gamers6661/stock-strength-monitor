# -*- coding: utf-8 -*-
"""均线趋势日报；只陈述完成日线与已取得的资金数据。"""
import argparse
import json
import config


def build(snap=None):
    snap = snap or json.loads(config.SNAPSHOT_JSON.read_text(encoding="utf-8"))
    model = snap.get("strength_model") or {}
    intraday = snap.get("intraday_model") or {}
    funds = snap.get("fund_confirmation") or {}
    fund_meta = snap.get("fund_meta") or {}
    emotion = snap.get("market_emotion") or {}
    coverage = snap.get("coverage_stats") or {}
    axes = snap.get("axis_counts") or {}
    rows = sorted((s for s in snap.get("stocks", []) if s.get("watch_candidate")),
                  key=lambda s: -s.get("stock_strength_score", 0))
    visible_rows = list(snap.get("stocks", [])) + list(snap.get("coverage_catalog", []))
    live_rows = sorted((s for s in visible_rows if s.get("current_strong_candidate")),
                       key=lambda s: (-(s.get("intraday_score") or 0),
                                     -(s.get("stock_strength_score") or 0),
                                     str(s.get("code") or "")))
    lines = ["# 股票强势监测 · " + snap.get("factor_model_version", model.get("version", "版本未知")), "",
             f"扫描开始：{snap.get('scan_started_at', '未知')}；逐股报价采集：{snap.get('quote_capture_at', '未知')}；扫描完成：{snap.get('scan_completed_at', snap.get('generated_at', '未知'))}；完成日线判断日：{model.get('asof', '未知')}。", "",
             "日线趋势资格：完成日 MA5＞MA10＞MA20、MA20 较前一完成日上行，且完成日收盘守住 MA10。日线进攻比较5/10/20日实际推进与相对速度，20日涨幅保留为单项指标。", "",
             f"完成日线评分样本 {len(snap.get('stocks', []))} 只；日线趋势在线 {len(rows)} 只；当前回踩候选 {model.get('entry_watch_count', 0)} 只。另有 {coverage.get('excluded', 0)} 只数据未齐，其中均线趋势在线 {coverage.get('trend_online_outside', 0)} 只，在同一个股列表标注强度待评分。",
             f"日线进攻强度入口：进攻强势 {model.get('persistent_strong_count', 0)} 只；日线近期增强 {model.get('recent_improving_count', 0)} 只；日线高位衰减 {model.get('high_fading_count', 0)} 只。分位参考 {model.get('strength_reference_count', 0)} 只，主板等权基准 {model.get('strength_market_benchmark_count', 0)} 只。",
             f"盘中观察：阶段 {intraday.get('phase_status', snap.get('session', '未知'))}；最新有效逐股报价 {intraday.get('latest_valid_quote_at', '未知')}；有效报价 {intraday.get('valid_quote_count', 0)}/{intraday.get('reference_pool_count', 0)}；主板同期等权涨幅 {intraday.get('mainboard_equal_weight_change_pct', '未知')}%；完整盘中分 {intraday.get('complete_score_count', 0)} 只；历史与报价口径异常 {intraday.get('price_basis_mismatch_count', 0)} 只；当前强势 {model.get('current_strong_count', 0)} 只；转弱／修复 {model.get('turn_weak_repair_count', 0)} 只；初步转强 {sum(bool(s.get('startup_candidate')) for s in visible_rows)} 只。当前强势逐项要求历史强势基础、上一完成日日线趋势、暂态趋势、上涨、跑赢主板、不低于开盘、三项完整评分和风险通过。",
             f"双轴：情绪活跃且趋势在线 {axes.get('情绪活跃·趋势在线', 0)} 只；情绪活跃但趋势未在线 {axes.get('情绪活跃·趋势未在线', 0)} 只；趋势在线但情绪平稳 {axes.get('趋势在线·情绪平稳', 0)} 只；趋势未在线且情绪平稳 {axes.get('趋势未在线·情绪平稳', 0)} 只；情绪未核验 {axes.get('情绪数据不足', 0)} 只。",
             f"主板交易情绪：{emotion.get('state', '数据不足')}；同池成交 {emotion.get('traded', '未知')} 只、{'当前接近涨停' if emotion.get('provisional') else '收盘涨停'} {emotion.get('limit_up', '未知')} 只、昨日涨停 {emotion.get('limit_up_yesterday', '未知')} 只；主榜外情绪活跃 {len(snap.get('emotion_candidates') or [])} 只（趋势资格见个股详情）。",
             f"当日资金：来源 {snap.get('fund_source', '未知')}；覆盖 {fund_meta.get('coverage', 0)} 只；采集时间 {fund_meta.get('fetched_at', '未知')}。逐股明细保留各自来源与采集时间；多日逐股覆盖不足时显示未知。",
             f"同源日级资金历史覆盖 {funds.get('covered', 0)}/{funds.get('total', 0)} 只；其中三期均为正 {funds.get('positive_all', 0)} 只。未覆盖标未知，不据此排除。", "",
             "| 当前强势 | 逐股报价 | 当日涨幅 | 主板超额百分点 | 日线进攻强度 | 盘中强度 | 相对评分变化 | 趋势状态 | 风险 |",
             "|---|---|---:|---:|---:|---:|---|---|---|"]
    for s in live_rows[:30]:
        quote_at = s.get("intraday_quote_at") or "未知"
        if s.get("intraday_quote_fresh") is not True:
            quote_at += "（" + str(s.get("intraday_quote_status") or "报价不可判断") + "）"
        day_change = f"{s['change_pct']:+.2f}%" if s.get("intraday_quote_fresh") and s.get("change_pct") is not None else "不可判断"
        score_delta = (f"{s['intraday_score_delta']:+.1f}分 · {s.get('intraday_delta_state', '')}"
                       if s.get("intraday_score_delta") is not None else s.get("intraday_delta_state", "首轮扫描"))
        risk = "；".join(s.get("intraday_risk_flags") or []) or "未触发明显风险"
        relative = (f"{s['intraday_relative_return_pct']:+.2f}" if s.get("intraday_relative_return_pct") is not None else "未知")
        lines.append(f"| {s['name']} {s['code']} | {quote_at} | {day_change} | {relative} | {s.get('stock_strength_score', '待评分')} | {s.get('intraday_score', '待评分')} | {score_delta} | {s.get('intraday_trend_state', '未知')} | {risk} |")
    if not live_rows:
        lines.append("| 本轮无候选 | — | — | — | — | — | — | — | 请查看转弱／修复、初步转强或日线观察池 |")
    attack_board = snap.get("attack_monitor") or {}
    attack_lines = ["## 进攻监测", "", attack_board.get("criterion", "暂无有效进攻观察"),
                    f"本轮有效进攻样本 {attack_board.get('sample_count', 0)} 只；当前候选 {attack_board.get('count', 0)} 只；形态为盘中观察，待收盘确认。", "",
                    "| 股票 | 暂态进攻分 | 日线档 | 当日涨幅 | 现价形态 | 报价时间 | 独立风险 |",
                    "|---|---:|---|---:|---|---|---|"]
    for s in attack_board.get("rows") or []:
        risk = "；".join(s.get("intraday_risk_flags") or []) or "未触发既定风险提示"
        if s.get("intraday_risk_level") == "待核验":
            risk += "；风险仍有待核验项"
        attack_lines.append(f"| {s.get('name')} {s.get('code')} | {s.get('live_attack_score')} | {s.get('trend_tier') or '未在线'} | {s.get('change_pct')} | {s.get('live_attack_stage')} | {s.get('intraday_quote_at')} | {risk} |")
    lines[6:6] = attack_lines + [""]
    close_board = snap.get("close_strong_board") or {}
    trend = snap.get("trend_ma5_observation") or {}
    new_strength = snap.get("intraday_new_strength") or {}
    if snap.get("session") in ("早盘", "午间休市", "午盘", "尾盘"):
        lead = [f"## 盘中监控 · {new_strength.get('day', '未知')}", "",
                f"今日盘中强势 {len(new_strength.get('rows') or [])} 只；上一完成日 {trend.get('baseline_asof') or '未留档'} 趋势成立且站上 MA5 {trend.get('base_count', 0)} 只，其中贴线未破 {len(trend.get('main_rows') or [])} 只，15 分钟内收回 {len(trend.get('reclaim_rows') or [])} 只。现价距暂态 MA5 不超过 1%；跌破后的收回须有连续分钟行情核验。", "",
                "| 今日盘中强势 | 当日涨幅 | 主板超额百分点 | 盘中分 | 逐股报价 | 状态 |",
                "|---|---:|---:|---:|---|---|"]
        for s in new_strength.get("rows") or []:
            lead.append(f"| {s.get('name')} {s.get('code')} | {s.get('change_pct')} | {s.get('relative_return_pct')} | {s.get('intraday_score')} | {s.get('quote_at')} | {s.get('kind')} |")
        lead += ["", "| MA5 趋势观察 | 当日涨幅 | 现价距暂态 MA5 | 日低距 MA5 临界价 | 逐股报价 | 状态 |",
                 "|---|---:|---:|---:|---|---|"]
        for s in (trend.get("main_rows") or []) + (trend.get("reclaim_rows") or []):
            lead.append(f"| {s.get('name')} {s.get('code')} | {s.get('change_pct')} | "
                        f"{s.get('distance_pct')}% | {s.get('low_distance_pct')}% | "
                        f"{s.get('quote_at') or '暂无'} | {s.get('status')} |")
        lead += ["", "## 详细分析", ""]
    else:
        lead = [f"## 收盘强势主榜 · {close_board.get('asof') or '待生成'}", "",
                ("今日正式收盘日线尚未生成，以下为最近一次完成日留档。" if close_board.get("today_pending") else
                 "按现有日线因子资格筛选，按日线进攻强度排序。"), "",
                "行业及概念涨幅是同日有效成员剔除本股后的平均涨幅；概念只列同伴上涨者。", "",
                "| 收盘强势 | 当日涨幅 | 所属行业板块 | 行业同伴涨幅 | 上涨的关联概念 | 日线基础分 | 趋势阶段 |",
                "|---|---:|---|---:|---|---:|---|"]
        for s in close_board.get("stocks") or []:
            concepts = "；".join(f"{c['name']} {c['peer_change_pct']:+.2f}%"
                                for c in s.get("rising_concepts") or []) or "暂无同伴上涨"
            day_change = (f"{s['today_change_pct']:+.2f}%" if s.get("today_change_pct") is not None else "—")
            industry_change = (f"{s['industry_peer_change_pct']:+.2f}%"
                               if s.get("industry_peer_change_pct") is not None else "样本不足")
            lead.append(f"| {s.get('name')} {s.get('code')} | {day_change} | {s.get('industry') or '待确认'} | "
                        f"{industry_change} | {concepts} | {s.get('score')} | {s.get('trend_stage') or '—'} |")
        if not close_board.get("stocks"):
            lead.append("| 暂无符合条件的股票 | — | — | — | — | — | — |")
        lead += ["", "## 详细分析", ""]
    lines[4:4] = lead
    lines += ["", "## 日线趋势观察（历史基础，不代表当前盘中精选）", "",
              "| 股票 | 日线进攻强度/分位 | 日线近期变化 | 强项/短板 | 20日涨幅 | 趋势 | 情绪 | 行业状态 | 同花顺题材关系 |",
              "|---|---:|---|---|---:|---|---|---|---|"]
    for s in rows[:30]:
        lines.append(f"| {s['name']} {s['code']} | {s.get('stock_strength_score', 0):.1f}/{s.get('stock_strength_percentile', 0):.1f} | "
                     f"{s.get('stock_strength_display_state', '数据不足')} | "
                     f"{s.get('stock_strength_main_good', '—')} / {s.get('stock_strength_main_weak', '—')} | "
                     f"{s['ret20']:+.2f}% | {s.get('trend_stage', '数据不足')} | "
                     f"{s.get('emotion_heat', '数据不足')} | "
                     f"{s.get('industry_trend_state', '数据不足')}、{s.get('industry_stock_relation', '数据不足')} | "
                     f"{'；'.join(r.get('name', '')+':'+r.get('state', '数据不足') for r in s.get('theme_relations', [])) or '数据不足'} |")
    lines += ["", "## 口径", "",
              "- 回踩只看最近3个完成交易日；盘中低点可跌破当日MA10，收盘站回才算守住。收盘后继续上涨与仅站回待确认分开。",
              "- 主力净额是东财按成交单分类的统计，不代表可识别某个机构；3/5/10日均正只是辅助确认，不加权也不是买入指令。",
              "- 日级资金使用本地全池同源历史，按完成日增补；缺口保留逐股原因，资金源故障时不以价量推算代替。",
              "- 行业广度及相对同行收益单列，缺失不补；个股进攻统一比较5/10/20日绝对推进与相对速度，同行覆盖不改变评分公式。现价距离MA10过远单列风险。",
              "- 日线进攻研究权重：5日50%、10日30%、20日20%；每周期60%绝对推进、40%相对分位。绝对推进满分对应5日8%、10日12%、20日20%。各项原始依据见看板和CSV；权重与入口阈值尚未做样本外验证。",
              "- 强度分位变化优先使用真实留档，缺失日期使用最近20个完成日的历史重算参考；每股标注来源。重算采用当前池，不是当时实测名单。",
              "- 回撤修复指20日窗口内历史最大回撤的修复程度；当前距20日高点的回撤另列。量价表现是日线成交量与价格关系的描述，不代表真实资金意图。",
              "- 日线强度分位是横截面相对位置；绝对下跌时即使分位靠前，也只能称为抗跌。盘中行情不参与完成日线强度。盘中观察分三项全部有效时等权，缺一项不生成完整分；相对主板分位用于解释是否跑赢市场，排序与直接涨幅相同，不作为独立重复信息。",
               "- 情绪基于全主板报价池的短期交易行为；趋势仍基于有效完成日线。主榜不设成交额门槛；主榜外股票若有连续21日完成日线，可单独核验均线趋势，但缺少完整25日核心日线时不参与日线进攻强度评分。",
              "- 全体进攻排名独立保留；A为趋势在线、进攻分≥65、5/20日上涨且5日≥5%或10日≥8%或20日≥12%；B为进攻分≥45、20日上涨且达到较低涨幅门槛或存在强势进攻段；C为其余结构在线股。各档不设名额。量价、回撤、过热与成交限制不计入进攻分。",
              "- 个股题材和行业优先核对同花顺F10；概念详情成员只作交叉对照，缺失时明确标待核对。行业与所有题材关系逐项比较并排除本股；重叠题材不累计奖励。盘中情绪为暂态。",
              "- 趋势和情绪助攻是共同参与观察；20日领涨是涨幅次序，不表示带动板块。题材标签不能当作因果证据。",
              "- 趋势阶段、情绪状态与助攻标签是可复查的描述分类，阈值未经过样本外收益验证，不代表优先买入。",
              "- 报价与完成日线分开；仅在收盘后确认当日回踩状态。"]
    if snap.get("mode") == "local-rebuild":
        lines.append("- 本次仅用本地日线重建；沿用原报价时间，未声称行情已更新。")
    structure = snap.get('wyckoff_structure') or {}
    lines += ['', '## 固定平台量价结构观察', '',
              f"版本 {structure.get('version','未生成')}；独立观察，不参与进攻分或原候选筛选。", '',
              '| 股票 | 完成日结构 | 证据截至 | 盘中位置 | 当前限制 |',
              '|---|---|---|---|---|']
    for item in structure.get('rows', []):
        lines.append(f"| {item['name']} {item['code']} | {item['label']} | {item['evidence_asof']} | {item['live_label']} | {'；'.join(item['restrictions']) or '未触发'} |")
    if not structure.get('rows'): lines.append('| 暂无已识别周期 | — | — | — | — |')
    context=snap.get('session_context') or {}
    refs=snap.get('history_reference') or {}
    lines += ['', '## 最新价格与结构判断（昨日收盘衔接当日判断）', '',
              f"版本 {context.get('version','未生成')}；完成日 {context.get('previous_close_asof')} → {context.get('stage')}，报价判断 {context.get('price_judged_count',0)} 只、口径可比结构判断 {context.get('structure_judged_count',0)} 只。",
              f"本地完成日参考 {len(refs.get('available_days',[]))} 日；真实留档优先，历史重算明确标来源，后续完成日增补。",
              '9:15开始当日竞价观察，每分钟获取。竞价结合昨收主榜、同源日线、ATR位置和当前价格判断；虚拟匹配/未匹配量未获核验，不认定量价突破。',
              'ATR20使用含跳空真实波幅简单平均；威科夫仅验证供需、努力/结果及SOS/LPS量价特征，完整A-E阶段和点数图目标尚未验证。', '',
              '| 股票 | 最新判断 | 当前结构 | 报价截至 | 整理条件 | 历史日线数 | 较昨收ATR | 风险 |', '|---|---|---|---|---|---|---|---|']
    candidates=[r['session_context'] for r in visible_rows if r.get('session_context') and r['session_context']['quote_valid']]
    candidates.sort(key=lambda c:(not c['monitor_candidate'],-(c['price_attack_score'] or 0),c['code']))
    for c in candidates[:30]:
        gap=round(c['gap_atr'],2) if c['gap_atr'] is not None else '待核验'
        lines.append(f"| {c['name']} {c['code']} | {c.get('current_label') or c['label']} | {c.get('structure_state') or '口径待核验'} | {c['quote_at']} | {c.get('setup_state') or '待核验'} | {(c.get('history_evidence') or {}).get('count',0)} | {gap} | {'；'.join(c['risks']) or '当前未触发'} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-o", "--output")
    args = parser.parse_args()
    result = build()
    if args.output:
        config.atomic_write_text(args.output, result)
    else:
        print(result)
