import json
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from ninja_jwt.tokens import RefreshToken

from accounts.models import User
from polls.models import Contest, Contestant, Poll
from voting.models import AuditLog, VotingPolicy


class ContestApiTests(TestCase):
    def setUp(self):
        self.organizer = User.objects.create_user(
            email="organizer@example.com", name="Organizer", password="StrongPassword123!", role=User.Role.ORGANIZER
        )
        self.other = User.objects.create_user(
            email="other@example.com", name="Other", password="StrongPassword123!", role=User.Role.ORGANIZER
        )
        self.admin = User.objects.create_superuser(
            email="admin@example.com", name="Admin", password="StrongPassword123!"
        )
        self.poll = Poll.objects.create(creator=self.organizer, title="Legacy", slug="legacy-poll")
        self.contest = Contest.objects.create(
            organizer=self.organizer,
            source_poll=self.poll,
            title="Legacy",
            slug="legacy-contest",
            state=Contest.State.LIVE,
        )
        self.contestant = Contestant.objects.create(poll=self.poll, name="One")
        self.organizer_client = self._client_for(self.organizer)
        self.other_client = self._client_for(self.other)
        self.admin_client = self._client_for(self.admin)

    def _client_for(self, user):
        token = RefreshToken.for_user(user).access_token
        client = self.client_class()
        client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {token}"
        return client

    def _request(self, client, method, path, payload=None):
        return client.generic(
            method,
            path,
            data=json.dumps(payload) if payload is not None else None,
            content_type="application/json",
        )

    def test_public_contest_listing_and_detail(self):
        response = self.client.get("/api/v1/contests/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["slug"], "legacy-contest")
        detail = self.client.get("/api/v1/contests/legacy-contest/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["contestants"][0]["name"], "One")

    def test_organizer_can_create_update_transition_and_delete_own_contest(self):
        now = timezone.now()
        create = self._request(
            self.organizer_client,
            "POST",
            "/api/v1/contests/",
            {
                "title": "New Contest",
                "category": "Music",
                "start_time": now.isoformat(),
                "end_time": (now + timedelta(days=1)).isoformat(),
                "contestants": [{"name": "Singer"}],
                "policy": {"price_per_vote": "2.50", "revenue_share_percentage": 80},
            },
        )
        self.assertEqual(create.status_code, 201, create.content)
        created = create.json()
        contest = Contest.objects.get(pk=created["id"])
        self.assertTrue(contest.source_poll_id)
        self.assertEqual(contest.source_poll.contestants.count(), 1)
        self.assertEqual(contest.voting_policy.price_per_vote, 2.5)
        transition = self._request(
            self.organizer_client,
            "POST",
            f"/api/v1/contests/{contest.slug}/transition/",
            {"state": Contest.State.LIVE},
        )
        self.assertEqual(transition.status_code, 200, transition.content)
        self.assertIsNotNone(Contest.objects.get(pk=contest.pk).published_at)
        update = self._request(
            self.organizer_client,
            "PATCH",
            f"/api/v1/contests/{contest.slug}/",
            {"description": "Updated"},
        )
        self.assertEqual(update.status_code, 400)
        close = self._request(
            self.organizer_client,
            "POST",
            f"/api/v1/contests/{contest.slug}/transition/",
            {"state": Contest.State.CLOSED},
        )
        self.assertEqual(close.status_code, 200)
        source_poll_id = contest.source_poll_id
        deleted = self._request(
            self.organizer_client, "DELETE", f"/api/v1/contests/{contest.slug}/"
        )
        self.assertEqual(deleted.status_code, 200)
        self.assertFalse(Contest.objects.filter(pk=contest.pk).exists())
        self.assertFalse(Poll.objects.filter(pk=source_poll_id).exists())

    def test_contest_mutations_require_owner_or_admin(self):
        denied = self._request(
            self.other_client,
            "PATCH",
            f"/api/v1/contests/{self.contest.slug}/",
            {"description": "Not mine"},
        )
        self.assertEqual(denied.status_code, 403)
        allowed = self._request(
            self.admin_client,
            "POST",
            f"/api/v1/contests/{self.contest.slug}/transition/",
            {"state": Contest.State.PAUSED},
        )
        self.assertEqual(allowed.status_code, 200)

    def test_results_follow_visibility_rules(self):
        self.contest.results_visibility = Contest.ResultsVisibility.AFTER_CLOSE
        self.contest.save(update_fields=["results_visibility"])
        self.assertEqual(self.client.get("/api/v1/contests/legacy-contest/results/").status_code, 403)
        self.contest.state = Contest.State.CLOSED
        self.contest.save(update_fields=["state"])
        self.assertEqual(self.client.get("/api/v1/contests/legacy-contest/results/").status_code, 200)
        self.contest.results_visibility = Contest.ResultsVisibility.NEVER
        self.contest.save(update_fields=["results_visibility"])
        self.assertEqual(self.client.get("/api/v1/contests/legacy-contest/results/").status_code, 403)


class AdminApiTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="admin@example.com", name="Admin", password="StrongPassword123!"
        )
        self.user = User.objects.create_user(
            email="user@example.com", name="User", password="StrongPassword123!"
        )
        token = RefreshToken.for_user(self.admin).access_token
        self.client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {token}"

    def _request(self, method, path, payload=None):
        return self.client.generic(
            method,
            path,
            data=json.dumps(payload) if payload is not None else None,
            content_type="application/json",
        )

    def test_admin_can_manage_roles_and_audit_logs(self):
        response = self._request(
            "PATCH", f"/api/v1/admin/users/{self.user.pk}/role/", {"role": User.Role.ORGANIZER}
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.role, User.Role.ORGANIZER)
        self.assertTrue(AuditLog.objects.filter(action_type=AuditLog.ActionType.ROLE_CHANGE).exists())
        logs = self.client.get("/api/v1/admin/audit-logs/")
        self.assertEqual(logs.status_code, 200)

    def test_non_admin_cannot_access_admin_routes(self):
        token = RefreshToken.for_user(self.user).access_token
        self.client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {token}"
        response = self.client.get("/api/v1/admin/users/")
        self.assertEqual(response.status_code, 403)

