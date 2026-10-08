"""Only fresh, unique Isolation Forest decisions can qualify an episode."""

import unittest
from datetime import datetime, timedelta, timezone

from app.models.schemas import AnomalyResult
from app.services.environment import EnvironmentIntelligence
from test_schemas import anomaly


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)
        self.engine = EnvironmentIntelligence()

    def result(self, seconds=0, abnormal=True, **changes):
        return AnomalyResult.model_validate(anomaly(
            ts=(self.now + timedelta(seconds=seconds)).isoformat(), anomaly=abnormal,
            score=-0.18 if abnormal else 0.12, **changes))

    def feed(self, seconds, abnormal=True, **changes):
        decision = self.engine.prepare(self.result(seconds, abnormal, **changes), connected=True,
                                       now=self.now + timedelta(seconds=seconds))
        self.engine.commit(decision)
        return decision

    def test_warning_critical_single_episode_rearm_and_second_episode(self):
        self.assertEqual(self.feed(0, False).level, "NORMAL")
        self.assertEqual(self.feed(1).level, "WARNING")
        first = self.feed(2)
        self.assertEqual(first.level, "CRITICAL")
        self.assertEqual(first.alert.type, "ENVIRONMENTAL_ANOMALY")
        self.assertEqual(first.alert.severity, "critical")
        for second in (3, 4, 5):
            decision = self.feed(second)
            self.assertEqual(decision.level, "CRITICAL")
            self.assertIsNone(decision.alert)
        self.assertEqual(self.feed(6, False).level, "CRITICAL")
        self.assertEqual(self.feed(7, False).level, "NORMAL")
        self.assertEqual(self.feed(8).level, "WARNING")
        second = self.feed(9)
        self.assertEqual(second.level, "CRITICAL")
        self.assertNotEqual(first.alert.id, second.alert.id)

    def test_two_of_three_results_can_be_nonconsecutive(self):
        self.assertEqual(self.feed(0).level, "WARNING")
        self.assertEqual(self.feed(1, False).level, "NORMAL")
        self.assertEqual(self.feed(2).level, "CRITICAL")

    def test_duplicates_and_nonmonotonic_results_cannot_trigger_or_rearm(self):
        self.feed(0)
        before = self.engine.state
        for offset in (0, -1):
            decision = self.engine.prepare(self.result(offset), connected=True, now=self.now)
            self.assertEqual(decision.state, before)
            self.assertIsNone(decision.alert)
            self.engine.commit(decision)
        self.feed(1)
        self.feed(2, False)
        duplicate = self.engine.prepare(self.result(2, False), connected=True,
                                        now=self.now + timedelta(seconds=2))
        self.engine.commit(duplicate)
        self.assertTrue(self.engine.state["critical_active"])
        self.assertEqual(self.engine.state["normal_streak"], 1)
        self.assertEqual(self.feed(3, False).level, "NORMAL")

    def test_stale_future_calibration_offline_and_other_models_are_not_evidence(self):
        cases = [(self.result(-31), True), (self.result(6), True),
                 (self.result(), False), (self.result(model="different_model"), True),
                 (AnomalyResult.model_validate(anomaly(ts=self.now.isoformat(), ready=False,
                                                       anomaly=False, score=None)), True)]
        for result, connected in cases:
            engine = EnvironmentIntelligence()
            with self.subTest(result=result, connected=connected):
                decision = engine.prepare(result, connected=connected, now=self.now)
                self.assertIsNone(decision.level)
                self.assertIsNone(decision.alert)
                self.assertEqual(decision.state["window"], [])
                self.assertFalse(decision.state["critical_active"])

    def test_exact_freshness_boundary_and_future_tolerance(self):
        for offset in (-30, 5):
            engine = EnvironmentIntelligence()
            self.assertEqual(engine.prepare(self.result(offset), connected=True,
                                            now=self.now).level, "WARNING")

    def test_gaps_and_disconnection_reset_evidence_but_keep_episode_latched(self):
        self.feed(0)
        self.assertEqual(self.feed(31).level, "WARNING")
        self.assertEqual(self.feed(32).level, "CRITICAL")
        self.feed(33, False)
        self.engine.commit(self.engine.prepare_disconnect())
        self.assertEqual(self.feed(34, False).level, "CRITICAL")
        self.assertEqual(self.feed(65, False).level, "CRITICAL")
        self.assertEqual(self.feed(66, False).level, "NORMAL")

    def test_replay_and_saved_state_never_create_an_alert_or_replay_evidence(self):
        first, second = self.result(0), self.result(1)
        restored = EnvironmentIntelligence.restore([first, second])
        self.assertTrue(restored.state["critical_active"])
        decision = restored.prepare(self.result(2), connected=True,
                                    now=self.now + timedelta(seconds=2))
        self.assertIsNone(decision.alert)
        self.assertEqual(decision.level, "CRITICAL")
        saved = EnvironmentIntelligence.restore([], restored.state)
        self.assertEqual(saved.state["window"], [])
        self.assertTrue(saved.state["critical_active"])

    def test_preparing_decision_does_not_mutate_state_before_database_commit(self):
        before = self.engine.state
        decision = self.engine.prepare(self.result(), connected=True, now=self.now)
        self.assertEqual(self.engine.state, before)
        self.assertNotEqual(decision.state, before)


if __name__ == "__main__":
    unittest.main()
