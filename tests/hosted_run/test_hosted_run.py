"""What a hosted run is allowed to spend, and what it must refuse to retry.

These are billing tests, and they exist because the same mistake was made three times in one
day. ElevenLabs answers an exhausted quota with **HTTP 401**, which reads as a bad key; the
retry logic was written believing it was a rate limit, so it waited 20, 40, 80 and 160 seconds
and asked again for something no amount of patience would grant. The body said so in one line
and `raise_for_status()` was throwing the body away.

The second half is the budget. A free tier holds about two and a half hours of Scribe, the
corpus holds seventy, so *which* lectures get sent is a decision and not an accident of
manifest order.
"""

import unittest

from scripts.hosted_run import (
    CREDITS_PER_MINUTE,
    HostedFailure,
    SARVAM_PROVEN_CEILING,
    fits_the_budget,
    period_start_ms,
    remaining_credits,
    retryable,
    too_long_for_sarvam,
)

QUOTA_BODY = ('{"detail":{"status":"quota_exceeded","message":"This request exceeds your quota '
              'of 10000. You have 90 credits remaining, while 4865 credits are required."}}')


def lecture(slug, minutes):
    return {"slug": slug, "audio_seconds": minutes * 60}


class RetryTests(unittest.TestCase):
    def test_an_exhausted_quota_is_never_retried(self):
        # The failure that cost three wrong diagnoses. Waiting cannot refill an account.
        self.assertFalse(retryable(HostedFailure(401, QUOTA_BODY)))

    def test_no_401_is_retried_whatever_the_body_says(self):
        # On this API 401 has meant quota or a bad key. Retrying fixes neither, and the
        # pre-flight credit check now tells the two apart before anything is sent.
        self.assertFalse(retryable(HostedFailure(401, '{"detail":"invalid api key"}')))

    def test_a_real_rate_limit_is_retried(self):
        self.assertTrue(retryable(HostedFailure(429, "too many requests")))

    def test_a_server_error_is_retried(self):
        self.assertTrue(retryable(HostedFailure(503, "upstream unavailable")))

    def test_a_bad_request_is_not_retried(self):
        # Sarvam refuses over-long audio with 400. The file will not get shorter by waiting.
        self.assertFalse(retryable(HostedFailure(400, "audio too long")))

    def test_the_body_survives_into_the_message(self):
        # The whole point: whatever else happens, the sentence that explains it is visible.
        self.assertIn("quota_exceeded", str(HostedFailure(401, QUOTA_BODY)))


class BudgetTests(unittest.TestCase):
    def test_a_lecture_the_other_system_has_read_is_sent_first(self):
        # A lecture only one system has transcribed compares with nothing, and comparison is
        # the product. So pairing beats length.
        paired, alone = lecture("paired", 20), lecture("alone", 50)
        chosen = fits_the_budget([alone, paired], credits=20 * CREDITS_PER_MINUTE,
                                 paired_with_other_service={"paired"})
        self.assertEqual([l["slug"] for l in chosen], ["paired"])

    def test_the_longest_affordable_lecture_wins_among_equals(self):
        chosen = fits_the_budget([lecture("short", 10), lecture("long", 50)],
                                 credits=60 * CREDITS_PER_MINUTE, paired_with_other_service=set())
        self.assertEqual([l["slug"] for l in chosen], ["long", "short"])

    def test_it_stops_at_the_balance_rather_than_failing_at_it(self):
        chosen = fits_the_budget([lecture("a", 50), lecture("b", 50), lecture("c", 50)],
                                 credits=110 * CREDITS_PER_MINUTE, paired_with_other_service=set())
        self.assertEqual(len(chosen), 2)

    def test_an_empty_account_sends_nothing(self):
        self.assertEqual(fits_the_budget([lecture("a", 5)], credits=0,
                                         paired_with_other_service=set()), [])

    def test_a_lecture_larger_than_the_whole_balance_is_skipped_not_attempted(self):
        # This is what produced the 401 storm: nine lectures attempted against 90 credits.
        self.assertEqual(fits_the_budget([lecture("huge", 150)], credits=10_000,
                                         paired_with_other_service=set()), [])


class SarvamCeilingTests(unittest.TestCase):
    def test_the_longest_proven_success_is_allowed(self):
        # 60.8 minutes went through. The ceiling must not exclude a measured success.
        self.assertFalse(too_long_for_sarvam(lecture("bg-3-37", 60.8)))

    def test_a_lecture_past_the_ceiling_is_refused_before_it_is_uploaded(self):
        self.assertTrue(too_long_for_sarvam(lecture("long", 86.3)))

    def test_the_ceiling_sits_between_the_measured_success_and_failure(self):
        self.assertTrue(60.8 * 60 <= SARVAM_PROVEN_CEILING < 86.3 * 60)


class BalanceTests(unittest.TestCase):
    """Two meters on the same account, and the obvious one does not move.

    After two lectures totalling 114.6 minutes, `/v1/user/subscription` still reported
    `character_count: 0` while `/v1/usage/character-stats` reported 9,168 - which at 80.0
    credits a minute is exactly what those lectures should have cost. Believing the counter
    would mean sending an hour of audio at an account holding 832 credits.
    """

    def test_the_usage_series_is_believed_over_a_counter_that_has_not_moved(self):
        self.assertEqual(
            remaining_credits(10_000, 0, {"All": [0.0, 0.0, 9168.0]}), 832)

    def test_a_larger_counter_is_believed_over_the_series(self):
        # Whichever says more has been spent wins. Skipping a lecture that could have gone is
        # a smaller error than sending one that will be refused.
        self.assertEqual(remaining_credits(10_000, 9_500, {"All": [100.0]}), 500)

    def test_several_series_are_added_not_maximised(self):
        self.assertEqual(
            remaining_credits(10_000, 0, {"scribe": [4000.0], "tts": [1000.0]}), 5_000)

    def test_an_empty_usage_report_falls_back_to_the_counter(self):
        self.assertEqual(remaining_credits(10_000, 250, {}), 9_750)


class PeriodTests(unittest.TestCase):
    """Usage is counted from the last reset, not from 31 days before the next one.

    The 31-day window reached one day into the previous period and counted 9,168 credits spent
    on 2026-09-24 against a period that began on 09-25, reporting -307 credits for an account
    holding 8,861. Spend from a period that has already refilled must not be charged again.
    """

    def test_the_period_begins_one_calendar_month_before_the_next_reset(self):
        # Next reset 2026-10-25 01:46:16 UTC; the period began on the day of 2026-09-25.
        start = period_start_ms(1792892776)
        self.assertEqual(start, 1790294400000)  # 2026-09-25 00:00 UTC

    def test_last_periods_spend_is_not_counted(self):
        sept_24, oct_10 = 1790208000000, 1791590400000  # UTC midnights, the API's day buckets
        start = period_start_ms(1792892776)
        self.assertLess(sept_24, start)
        self.assertGreaterEqual(oct_10, start)

    def test_a_reset_late_in_a_long_month_does_not_skip_into_the_next(self):
        # 31 March has no 31 February; the period began on the last day of February.
        start = period_start_ms(1806451200)  # 2027-03-31 00:00 UTC
        self.assertEqual(start, 1803772800000)  # 2027-02-28 00:00 UTC
