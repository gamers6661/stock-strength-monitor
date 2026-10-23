# -*- coding: utf-8 -*-
"""一键日更 —— 自动化任务的统一入口

顺序：打分（quick 增量）→ 生成看板 → 生成报告 → 打印报告到 stdout

用法：
    python daily.py            # 盘中/收盘通用，输出报告并刷新看板
    python daily.py --full     # 全量重建（首次或数据异常时用，约 3-5 分钟）
    python daily.py --quiet    # 仅刷新数据与看板，不打印报告

退出码：0 正常 / 1 失败 / 2 跳过（行情未就绪，例如集合竞价期间没有成交额）
"""
import json
import sys
import time
from datetime import datetime

import config


@config.single_writer
def main():
    args = sys.argv[1:]
    full = "--full" in args
    quiet = "--quiet" in args
    import serve
    try:
        previous = json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        previous = {}
    mode = "full" if full else serve.pick_mode(datetime.now(), snapshot=previous)

    t0 = time.time()
    print(f"=== 股票强势监测 · 日更（{mode}）===", flush=True)

    # 1. 打分
    try:
        import scoring
        snap = scoring.run(mode=mode, rebuild_pool=full, progress=False)
    except scoring.DataNotReady as e:
        # 行情未就绪（典型：集合竞价无成交额）—— 不是故障，本轮跳过即可，
        # 绝不能把空数据写进快照，否则看板会被清成"今天没有数据"
        print(f"[SKIP] {e}")
        return 2
    except Exception as e:
        print(f"[FAIL] 打分失败：{type(e).__name__}: {e}")
        return 1

    # 3. 看板
    try:
        import make_dashboard
        page = make_dashboard.build(snap)
        if page is None or not page.exists():
            raise RuntimeError('看板页面未生成')
    except Exception as e:
        print(f"[FAIL] 看板生成失败：{type(e).__name__}: {e}")
        return 1

    # 4. 报告
    try:
        import report
        text = report.build(snap)
        config.atomic_write_text(config.ROOT / "snapshot_report.md", text)
    except Exception as e:
        print(f"[FAIL] 报告生成失败：{type(e).__name__}: {e}")
        return 1

    # 5. 摘要行（便于自动化快速判断是否需要提醒）
    al = snap.get("alerts", [])
    print(f"--- 摘要 ---")
    print(f"数据时间: {snap.get('generated_at')}")
    print(f"股票池: {snap.get('pool_size')} 只 | 有效样本: {snap.get('stock_count')} 只")
    print(f"回踩反弹观察: {len(al)} 条")
    print(f"耗时: {time.time()-t0:.1f}s")
    print()

    if not quiet:
        print("--- 报告正文 ---")
        print(text)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except config.PipelineBusy as exc:
        print(f'[SKIP] {exc}')
        sys.exit(2)
