from django.core.cache import cache
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from hypothesis import given, settings as hypothesis_settings, strategies as st

from accounts.models import User
from polls.models import Contest, Contestant, Poll
from voting.audit import create_audit_log
from voting.models import AuditLog, VoteAttempt
from voting.tasks import detect_suspicious_patterns
from voting.utils import extract_device_fingerprint, hash_ip_address
from config.middleware import RateLimitMiddleware


class RateLimitMiddlewareTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = RateLimitMiddleware(lambda request: HttpResponse("ok"))
        cache.clear()

    def tearDown(self):
        cache.clear()

    @override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "rate-limit-test"}})
    def test_authentication_endpoint_is_limited_to_twenty_per_minute(self):
        cache.clear()
        responses = []
        for _ in range(21):
            request = self.factory.post("/api/v1/auth/login/", REMOTE_ADDR="192.0.2.5")
            responses.append(self.middleware(request))
        self.assertTrue(all(response.status_code == 200 for response in responses[:20]))
        self.assertEqual(responses[-1].status_code, 429)
        self.assertGreaterEqual(int(responses[-1]["Retry-After"]), 1)
        self.assertLessEqual(int(responses[-1]["Retry-After"]), 60)

    @hypothesis_settings(max_examples=25)
    @given(request_count=st.integers(min_value=1, max_value=125))
    def test_vote_rate_limit_property(self, request_count):
        cache.clear()
        responses = [
            self.middleware(self.factory.post("/api/v1/votes/initiate/", REMOTE_ADDR="192.0.2.6"))
            for _ in range(request_count)
        ]
        self.assertEqual(sum(response.status_code == 200 for response in responses), min(request_count, 100))
        self.assertEqual(sum(response.status_code == 429 for response in responses), max(0, request_count - 100))


class AuditAndDetectionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="security@example.com", name="Security", password="StrongPassword123!"
        )
        self.poll = Poll.objects.create(creator=self.user, title="Security Poll", slug="security-poll")
        self.contest = Contest.objects.create(
            organizer=self.user,
            source_poll=self.poll,
            title="Security Contest",
            slug="security-contest",
            state=Contest.State.LIVE,
        )
        self.contestant = Contestant.objects.create(poll=self.poll, name="Target")

    def test_audit_helper_hashes_ip_and_extracts_fingerprint(self):
        request = RequestFactory().post(
            "/api/v1/votes/initiate/",
            HTTP_USER_AGENT="Test Browser",
            HTTP_ACCEPT_LANGUAGE="en-NG",
            REMOTE_ADDR="2001:db8::1",
        )
        request.user = self.user
        entry = create_audit_log(
            action_type=AuditLog.ActionType.VOTE_STARTED,
            user=self.user,
            resource_type="VoteAttempt",
            resource_id="attempt-1",
            request=request,
        )
        self.assertEqual(entry.ip_hash, hash_ip_address("2001:db8::1"))
        self.assertNotEqual(entry.ip_hash, "2001:db8::1")
        self.assertIn("UA:Test Browser", entry.device_fingerprint)
        self.assertLessEqual(len(entry.device_fingerprint), 512)
        self.assertLessEqual(len(extract_device_fingerprint(request)), 512)

    def test_audit_helper_records_supported_security_actions(self):
        for action in AuditLog.ActionType.values:
            entry = create_audit_log(
                action_type=action,
                user=self.user,
                resource_type="SecurityTest",
                resource_id=action,
                metadata={"nested": {"ok": True}},
            )
            self.assertEqual(entry.metadata["nested"]["ok"], True)
        self.assertEqual(
            AuditLog.objects.filter(resource_type="SecurityTest").count(),
            len(AuditLog.ActionType.values),
        )

    def test_suspicious_patterns_are_detected_and_deduplicated(self):
        common_hash = hash_ip_address("192.0.2.10")
        for index in range(11):
            VoteAttempt.objects.create(
                user=self.user,
                contest=self.contest,
                contestant=self.contestant,
                state=VoteAttempt.State.REJECTED,
                rejection_reason=f"failure {index}",
                ip_hash=common_hash,
            )
        self.assertGreaterEqual(detect_suspicious_patterns(), 3)
        self.assertEqual(
            AuditLog.objects.filter(action_type=AuditLog.ActionType.SUSPICIOUS_PATTERN).count(),
            3,
        )
        self.assertEqual(detect_suspicious_patterns(), 0)

