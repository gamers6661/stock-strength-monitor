# -*- coding: utf-8 -*-
"""按用户明确要求更新同花顺分类；日常行情刷新不调用此脚本。"""
import time
import json

import config
import datafeed as df


FILES = (
    config.THS_CONCEPT_CACHE,
    config.THS_INDUSTRY_CACHE,
    config.THS_MEMBER_CACHE,
    config.THS_INDUSTRY_MEMBER_CACHE,
    config.BOARD_CACHE,
    config.CACHE_DIR / "themes.json",
)
JOURNAL_NAME = 'classification_transaction.json'
JOURNAL_VERSION = '分类事务恢复1'


def recover_interrupted():
    """Called after the shared writer lock is acquired, before any reader builds a new model."""
    journal=config.CACHE_DIR/JOURNAL_NAME
    if not journal.exists():
        return False
    try:
        record=json.loads(journal.read_text(encoding='utf-8'))
        backups=record['backups']
        expected={p.name for p in FILES}
        if (record.get('version')!=JOURNAL_VERSION or record.get('phase') not in ('updating','committed')
                or not isinstance(backups,dict) or set(backups)!=expected
                or not all(v is None or isinstance(v,str) for v in backups.values())):
            raise ValueError('invalid classification recovery record')
    except (KeyError,TypeError,ValueError) as exc:
        raise RuntimeError('分类恢复记录损坏，暂停写入；保留已发布页面供核验') from exc
    if record['phase']=='updating':
        for name,content in backups.items():
            # Only fixed, known cache names; a journal cannot redirect writes outside this cache.
            target=config.CACHE_DIR/name
            if content is not None:
                config.atomic_write_text(target,content)
            elif target.exists():
                target.unlink()
        print('[MEMBERS] 已恢复被中断更新前的完整分类名单')
    try:
        journal.unlink()
    except OSError:
        if record['phase']=='updating':
            raise
        print('[WARN] 已完成的分类恢复记录暂未清理，不影响有效名单')
    return True


def _fresh(path, started):
    return path.exists() and path.stat().st_mtime >= started


@config.single_writer
def main():
    if any(p.parent.resolve()!=config.CACHE_DIR.resolve() for p in FILES):
        raise RuntimeError('分类缓存目录不一致，未开始更新')
    backups = {path: path.read_text(encoding="utf-8") if path.exists() else None
               for path in FILES}
    journal=config.CACHE_DIR/JOURNAL_NAME
    recovery=dict(version=JOURNAL_VERSION,phase='updating',backups={p.name:v for p,v in backups.items()})
    config.atomic_write_text(journal,json.dumps(recovery,ensure_ascii=False))
    started = time.time()
    try:
        concepts = df.fetch_ths_concept_catalog(force=True)
        industries = df.fetch_ths_industry_catalog(force=True)
        if not (_fresh(config.THS_CONCEPT_CACHE, started)
                and _fresh(config.THS_INDUSTRY_CACHE, started)):
            raise RuntimeError("同花顺目录未成功更新")

        concept_members = df.build_ths_members(force=True, progress=True)
        industry_members = df.build_ths_industry_members(force=True, progress=True)
        if ((concept_members.get("stat") or {}).get("failed")
                or (industry_members.get("stat") or {}).get("failed")
                or not df._is_verified_ths_member_cache(concept_members)
                or not _fresh(config.THS_MEMBER_CACHE, started)
                or not _fresh(config.THS_INDUSTRY_MEMBER_CACHE, started)):
            raise RuntimeError("成员详情有缺失，未采用本轮分类更新")

        boards = df.scan_ths_boards(force=True)
        if not boards or not _fresh(config.BOARD_CACHE, started):
            raise RuntimeError("同花顺概念指数映射未成功更新")
        theme_map = df.build_theme_map(force=True)
        if not theme_map or not _fresh(config.CACHE_DIR / "themes.json", started):
            raise RuntimeError("个股分类映射未成功生成")
        recovery['phase']='committed'
        config.atomic_write_text(journal,json.dumps(recovery,ensure_ascii=False))
        try:
            journal.unlink()
        except OSError:
            print('[WARN] 分类更新已完成，恢复记录等待下一写入周期清理')
        print(f"[OK] 分类已更新：概念目录 {len(concepts.get('detail') or {})}、"
              f"行业目录 {len(industries.get('detail') or {})}、"
              f"概念成员 {len(concept_members.get('map') or {})} 只、"
              f"行业成员 {len(industry_members.get('map') or {})} 只、"
              f"概念指数 {len(boards)} 个；下轮正常行情扫描使用新分类")
        return 0
    except Exception as exc:
        recover_interrupted()
        print(f"[FAIL] 分类更新未完成，保留原有分类：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
