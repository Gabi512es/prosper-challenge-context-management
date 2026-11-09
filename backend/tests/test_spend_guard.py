from decimal import Decimal
from types import SimpleNamespace
import unittest

from evals.spend_guard import SpendGuard


class SpendGuardTest(unittest.TestCase):
    def usage(self, prompt=4000, cached=3000, completion=50):
        return SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion,
                               prompt_tokens_details=SimpleNamespace(cached_tokens=cached))

    def test_observed_cost_replaces_worst_case_reservation(self):
        guard = SpendGuard("0.08")
        first = guard.reserve()
        guard.settle(first, self.usage())
        # $0.00675 observed; next reservation is 50% above that, not
        # a full uncached prompt plus maximal completion allowance.
        self.assertEqual(guard.observed[0], Decimal("0.00675"))
        second = guard.reserve()
        self.assertEqual(second, Decimal("0.010125"))
        guard.settle(second, self.usage())
        self.assertEqual(guard.accounted, Decimal("0.01350"))

    def test_forecast_does_not_admit_calls_above_remaining_limit(self):
        guard = SpendGuard("0.02")
        first = guard.reserve()
        guard.settle(first, self.usage(prompt=6000, cached=0, completion=0))
        with self.assertRaises(RuntimeError):
            guard.reserve()
        self.assertEqual(guard.requests, 1)

    def test_unknown_usage_is_not_zero_and_blocks_new_requests(self):
        guard = SpendGuard("0.20")
        reservation = guard.reserve()
        guard.settle(reservation, self.usage(cached=None))
        self.assertEqual(guard.accounted, reservation)
        self.assertTrue(guard.unknown_usage)
        self.assertEqual(guard.observed, [])
        with self.assertRaises(RuntimeError):
            guard.reserve()
