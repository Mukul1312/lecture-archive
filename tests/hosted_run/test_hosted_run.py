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
