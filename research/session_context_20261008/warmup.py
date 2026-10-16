"""实际补取缺口日线、全池资金，重算最近20日参考；不更改实测历史。"""
import gzip
import json
from pathlib import Path
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
import config
import datafeed as df
import fund_history
import history_reference
import strength

def backup():
    target=ROOT/'backups/latest_before_session_context'
    if (target/'source.zip').exists():return
    target.mkdir(parents=True,exist_ok=True)
    original=zipfile.ZipFile(ROOT/'backups/latest_before_wyckoff_round1/source.zip')
    # 这两份源码在上一轮没有修改；恢复本轮刚编辑前的确切字节。
    restored={'stock_strength.py','fund_confirmation.py'}
    new={'history_reference.py','fund_history.py','session_context.py','test_session_context.py','test_history_reference.py'}
    with zipfile.ZipFile(target/'source.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for p in ROOT.iterdir():
            if p.is_file() and p.name not in new and (p.suffix in ('.py','.pyw','.ps1','.bat','.vbs') or p.name=='dashboard_template.html'):
                archive.writestr(p.name,original.read(p.name) if p.name in restored else p.read_bytes())
    with gzip.open(target/'snapshot.json.gz','wb') as f:f.write(config.SNAPSHOT_JSON.read_bytes())
    (target/'README.md').write_text('# 本轮修改前最近一期备份\n\n压缩源码与快照仅供停止服务后恢复，不参与新版导入或判断。\n',encoding='utf-8')

def run():
    backup();out=Path(__file__).parent
    before=json.loads((out/'before.json').read_text(encoding='utf-8'))
    codes=[r['code'] for r in before['repair_candidates']]
    fetched,truncated=df.fetch_klines_bulk(codes,days=80)
    conn=df.db();conn.execute('PRAGMA busy_timeout=30000')
    # 同源逐股整段返回落库，不能把不同复权批次拼成最近窗口。
    inserted=df.save_klines(conn,'kline','code',fetched)
    pool=json.loads(config.POOL_CACHE.read_text(encoding='utf-8'))
    series={code:df.load_kline(conn,'kline','code',code) for code in pool}
    conn.close()
    current=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
    asof=current['strength_model']['asof']
    calendar=strength.trading_calendar({c:[b for b in ks if b['date']<=asof] for c,ks in series.items()})
    print(json.dumps(dict(kline_requested=len(codes),kline_received=len(fetched),rows_written=inserted,truncated=truncated),ensure_ascii=False),flush=True)
    references=history_reference.ensure(series,asof)
    print(json.dumps(references,ensure_ascii=False),flush=True)
    funds=fund_history.refresh(list(pool),calendar,workers=10,deadline=240)
    result=dict(kline_requested=len(codes),kline_received=len(fetched),rows_written=inserted,
                truncated=truncated,references=references,funds=funds)
    (out/'warmup_evidence.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(funds,ensure_ascii=False),flush=True)

if __name__=='__main__':run()
