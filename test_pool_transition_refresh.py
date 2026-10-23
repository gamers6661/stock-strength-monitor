"""Current-universe changes must not abort the refresh or revive removed candidates."""
import copy
import unittest
from datetime import timedelta
import scoring
import market_strength as M
from test_market_strength import fixture


class PoolTransitionRefresh(unittest.TestCase):
    def prepare(self, missing=False):
        snap, quotes, pool, histories, calendar, now = fixture()
        removed = dict(snap["stocks"][0],code="603818",name="removed from current pool",
                       signal_date=calendar[-1],
                       market_strength=dict(focus=True,trend_score=99.,emotion_score=99.))
        old = copy.deepcopy(snap["stocks"])
        for row in old:
            row["signal_date"] = calendar[-1]
            row["intraday_quote_at"] = str(now-timedelta(days=1))
        old.append(removed)
        if missing:
            code = next(iter(pool))
            quotes.pop(code)
            snap["stocks"] = [r for r in snap["stocks"] if r["code"]!=code]
        return snap,quotes,pool,histories,calendar,now,old

    def evaluate(self, f):
        snap,quotes,pool,histories,calendar,now,old = f
        scoring.retain_missing_quote_rows(snap["stocks"],snap["coverage_catalog"],
                                         quotes,old,pool,calendar[-1])
        M.attach(snap,quotes,pool,histories,calendar,now=now)
        self.assertTrue(M.validate(snap))
        return snap

    def test_removed_prior_day_code_cannot_abort_market_projection(self):
        f=self.prepare();prior=copy.deepcopy(f[-1])
        snap=self.evaluate(f)
        codes={r["code"] for r in snap["stocks"]+snap["coverage_catalog"]}
        self.assertNotIn("603818",codes)
        self.assertNotIn("603818",snap["radar_opportunity"]["by_code"])
        self.assertEqual(prior,f[-1])

    def test_missing_quote_in_current_pool_keeps_reference_but_no_current_score(self):
        f=self.prepare(missing=True)
        snap=self.evaluate(f)
        row=snap["coverage_catalog"][0]
        self.assertIn(row["code"],f[2])
        self.assertTrue(row["stale_carried"])
        self.assertFalse(row["intraday_observation_available"])
        self.assertIsNone(row["market_strength"]["trend_score"])
        self.assertIsNone(row["market_strength"]["emotion_score"])
        self.assertFalse(row["radar_opportunity"]["current"])

    def test_pool_transition_does_not_change_scores_or_benchmark_of_current_stocks(self):
        f=self.prepare()
        baseline=copy.deepcopy(f[:6])
        M.attach(baseline[0],baseline[1],baseline[2],baseline[3],baseline[4],now=baseline[5])
        snap=self.evaluate(f)
        self.assertEqual(snap["market_strength"],baseline[0]["market_strength"])
        self.assertEqual(snap["radar_opportunity"],baseline[0]["radar_opportunity"])

    def test_new_pool_code_is_projected_without_a_previous_row(self):
        f=self.prepare();snap,quotes,pool,histories,calendar,now,_=f
        code="600010"
        pool[code]=dict(pool[next(iter(pool))],name="new")
        quotes[code]=dict(quotes[next(iter(quotes))],name="new")
        histories[code]=copy.deepcopy(histories[next(iter(histories))])
        self.evaluate(f)
        self.assertIn(code,snap["radar_opportunity"]["by_code"])
        self.assertEqual(snap["market_strength"]["coverage"]["pool"],len(pool))

    def test_same_day_quote_disappearance_keeps_only_current_pool_references(self):
        f=self.prepare(missing=True)
        for old in f[-1]:old["intraday_quote_at"]=str(f[5])
        snap=self.evaluate(f)
        self.assertEqual(set(snap["radar_opportunity"]["by_code"]),set(f[2]))
