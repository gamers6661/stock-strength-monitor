"""Refetch missing completed daily bars from the quote source; never synthesize bars."""
import json
from contextlib import closing

import config
import datafeed as df
import strength
import history_increment


@config.single_writer
def run():
    snapshot = json.loads(config.SNAPSHOT_JSON.read_text(encoding="utf-8"))
    asof = snapshot["strength_model"]["asof"]
    targets = [row["code"] for row in snapshot.get("coverage_catalog", [])
               if row["reason"] in ("unaligned", "stale")]
    with closing(df.db()) as conn:
        return repair(snapshot, asof, targets, conn)


def repair(snapshot, asof, targets, conn):
    wanted = strength.trading_calendar({
        row["code"]: strength.completed(df.load_kline(conn, "kline", "code", row["code"]))
        for row in snapshot["stocks"]})[-61:]
    old_dates = {code: {bar["date"] for bar in df.load_kline(conn, "kline", "code", code)}
                 for code in targets}
    quotes = {r['code']:r for r in snapshot.get('stocks',[])+snapshot.get('coverage_catalog',[])}
    # Share overlap/adjustment validation; this maintenance entry must not merge incompatible scales.
    acquisition = history_increment.update(conn,targets,quotes,required_day=asof,force=True,progress=True)
    clean = {code:df.load_kline(conn,'kline','code',code) for code in targets}
    restored = {code: sorted((set(wanted) - old_dates[code]) &
                             {bar["date"] for bar in bars})
                for code, bars in clean.items()}
    result = {"asof": asof, "targeted": len(targets), "fetched": len(targets)-acquisition['failed'],
              "saved_rows": acquisition['changed_rows'], "restored_stocks": sum(bool(v) for v in restored.values()),
              "restored_dates": sum(map(len, restored.values())), "truncated": acquisition['truncated'],
              "acquisition":acquisition}
    print(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == "__main__":
    run()
