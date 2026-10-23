"""冻结规则回放：当前股票池的探索性比较；不宣称可成交收益或无偏历史回测。"""
import json
import statistics
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
import config
import market_strength
import stock_selection as S
import stock_selection_data as D


def evaluate(histories,code,day,horizon,calendar):
    offset=calendar.index(day)
    if offset+horizon>=len(calendar):return None
    end_day=calendar[offset+horizon];bs=histories[code]
    first=next((b for b in bs if b['date']==day),None);last=next((b for b in bs if b['date']==end_day),None)
    if first is None or last is None:return None
    future=[b for b in bs if day<b['date']<=end_day]
    return dict(return_pct=100*(last['close']/first['close']-1),mae_pct=100*(min(b['low'] for b in future)/first['close']-1))


def main():
    start=time.monotonic();snap=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf8'))
    histories,calendar=S.inputs(snap);records=D.load();state={};days=[];results=[];last_ids=set()
    for day in calendar[-45:]:
        source=dict(snap,quote_capture_at=day+' 15:00:00',session='已收盘',close_daily_verified_at=day+' 16:00:00',_historical_replay=True,board_catalog=[])
        model=S.build(source,histories,calendar,state,records,now=S.parse_at(day+' 15:00:00'));state=model['_state']
        scored=[c for c in model['order'] if model['items'][c]['score'] is not None]
        if len(scored)<len(histories)*.8:continue
        # 旧市场强度用同一天截断历史，绝不使用今天的盘中事件身份回填过去。
        old=market_strength.historical_scores(histories,calendar,day)
        selectors=dict(new_score=scored[:20],return5=sorted(scored,key=lambda c:model['items'][c]['evidence']['returns']['5'],reverse=True)[:20],
                       legacy_trend=sorted(scored,key=lambda c:old.get(c,{}).get('trend_score') or -1,reverse=True)[:20])
        for dim in ('price','relative','volume'):
            selectors['only_'+dim]=sorted(scored,key=lambda c:model['items'][c]['dimensions'][dim],reverse=True)[:20]
        selectors['qualified']=[c for c in scored if model['items'][c]['eligible']] if model['coverage']['amount_complete']/max(len(scored),1)>=.8 else []
        outcomes={h:{c:v for c in scored if (v:=evaluate(histories,c,day,h,calendar)) is not None} for h in (1,5,10,20)}
        bases={h:statistics.median(v['return_pct'] for v in values.values()) if values else None for h,values in outcomes.items()}
        for method,codes in selectors.items():
            for horizon in (1,5,10,20):
                base=bases[horizon]
                for c in codes:
                    outcome=outcomes[horizon].get(c)
                    if outcome is not None and base is not None:
                        results.append(dict(day=day,code=c,method=method,horizon=horizon,
                                            excess_pct=outcome['return_pct']-base,**outcome))
        ids=set(selectors['qualified']);days.append(dict(day=day,coverage=model['coverage'],counts=model['counts'],
            top20=selectors['new_score'],qualified=sorted(ids),changes=len(ids^last_ids)))
        last_ids=ids
        print('replay',day,len(scored),'qualified',len(ids),flush=True)
    aggregate=[]
    for method in sorted({r['method'] for r in results}):
        for horizon in (1,5,10,20):
            xs=[r for r in results if r['method']==method and r['horizon']==horizon]
            if xs:aggregate.append(dict(method=method,horizon=horizon,observations=len(xs),days=len({x['day'] for x in xs}),
                mean_excess=statistics.mean(x['excess_pct'] for x in xs),median_excess=statistics.median(x['excess_pct'] for x in xs),
                positive_excess_share=statistics.mean(x['excess_pct']>0 for x in xs),mean_mae=statistics.mean(x['mae_pct'] for x in xs)))
    report=dict(version=S.VERSION,rules=S.R,days=days,aggregate=aggregate,seconds=round(time.monotonic()-start,2),
        limitations=['使用当前股票池和当前成员，存在存活与分类偏差','重叠日期样本相关，不作为独立交易样本',
                     '价格表现不等于可实现收益；未模拟T+1、费用、滑点和无法成交',
                     '参数预先冻结；此轮不按结果调权重','资金流与板块不进入主分；仅比较单维与完整主分',
                     '历史真实金额覆盖不均，金额完整覆盖不足80%的日期不统计准入组合；主分比较不依赖金额',
                     '未形成充分跨市场阶段的样本外有效性证据'])
    path=Path(__file__).with_name('replay.json');path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print('saved',path,'seconds',report['seconds'])


if __name__=='__main__':main()
