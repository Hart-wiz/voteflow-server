"""Exercise authenticated vote and verification API paths end to end."""

import json
import re
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from ninja_jwt.tokens import RefreshToken

from accounts.models import User
from polls.models import Contest, Contestant, Poll
from voting.models import Vote, VoteAttempt, VotingPolicy


class VotingApiWorkflowTests(TestCase):
    def setUp(self):
        self.organizer = User.objects.create_user(
            email="workflow-organizer@example.com",
            name="Organizer",
            password="StrongPassword123!",
            role=User.Role.ORGANIZER,
        )
        self.voter = User.objects.create_user(
            email="workflow-voter@example.com",
            name="Voter",
            password="StrongPassword123!",
        )
        self.other_voter = User.objects.create_user(
            email="workflow-other@example.com",
            name="Other Voter",
            password="StrongPassword123!",
        )
        self.poll = Poll.objects.create(
            creator=self.organizer,
            title="Workflow Poll",
            slug="workflow-poll",
        )
        self.contest = Contest.objects.create(
            organizer=self.organizer,
            source_poll=self.poll,
            title="Workflow Contest",
            slug="workflow-contest",
            state=Contest.State.LIVE,
        )
        self.contestant = Contestant.objects.create(poll=self.poll, name="Candidate")
        self.policy = VotingPolicy.objects.create(
            contest=self.contest,
            price_per_vote=Decimal("0.00"),
            verification_method=VotingPolicy.VerificationMethod.EMAIL,
        )
        self.voter_client = self._client_for(self.voter)
        self.other_client = self._client_for(self.other_voter)

    def _client_for(self, user):
        token = RefreshToken.for_user(user).access_token
        client = self.client_class()
        client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {token}"
        return client

    @staticmethod
    def _post(client, path, payload):
        return client.post(path, data=json.dumps(payload), content_type="application/json")

    @override_settings(RESEND_API_KEY="re_test", DEFAULT_FROM_EMAIL="VoteFlow <test@example.com>")
    @patch("voting.providers.send_transactional_email")
    def test_email_verification_then_vote_commit(self, send_email):
        started = self._post(
            self.voter_client,
            "/api/v1/votes/initiate/",
            {
                "contest_id": str(self.contest.pk),
                "contestant_id": str(self.contestant.pk),
                "quantity": 2,
            },
        )
        self.assertEqual(started.status_code, 201, started.content)
        attempt_id = started.json()["id"]
        self.assertEqual(started.json()["state"], VoteAttempt.State.IDENTITY_CHECK)

        verification_started = self._post(
            self.voter_client,
            "/api/v1/votes/verify/",
            {
                "contest_id": str(self.contest.pk),
                "attempt_id": attempt_id,
                "method": VotingPolicy.VerificationMethod.EMAIL,
                "action": "start",
                "data": {},
            },
        )
        self.assertEqual(verification_started.status_code, 200, verification_started.content)
        verification_id = verification_started.json()["verification_id"]
        code = re.search(r"(\d{6})", send_email.call_args.kwargs["text"]).group(1)

        verification_completed = self._post(
            self.voter_client,
            "/api/v1/votes/verify/",
            {
                "contest_id": str(self.contest.pk),
                "attempt_id": attempt_id,
                "verification_id": verification_id,
                "method": VotingPolicy.VerificationMethod.EMAIL,
                "action": "complete",
                "data": {"code": code},
            },
        )
        self.assertEqual(verification_completed.status_code, 200, verification_completed.content)
        self.assertEqual(
            verification_completed.json()["attempt"]["state"],
            VoteAttempt.State.VERIFIED,
        )

        committed = self._post(
            self.voter_client,
            "/api/v1/votes/commit/",
            {"attempt_id": attempt_id},
        )
        self.assertEqual(committed.status_code, 200, committed.content)
        self.assertEqual(committed.json()["votes_created"], 2)
        self.assertEqual(Vote.objects.filter(poll=self.poll).count(), 2)
        self.assertEqual(
            VoteAttempt.objects.get(pk=attempt_id).state,
            VoteAttempt.State.COMPLETED,
        )

    def test_attempt_details_are_owner_only(self):
        started = self._post(
            self.voter_client,
            "/api/v1/votes/initiate/",
            {
                "contest_id": str(self.contest.pk),
                "contestant_id": str(self.contestant.pk),
                "quantity": 1,
            },
        )
        self.assertEqual(started.status_code, 201, started.content)
        attempt_id = started.json()["id"]
        self.assertEqual(
            self.voter_client.get(f"/api/v1/votes/attempt/{attempt_id}/").status_code,
            200,
        )
        self.assertEqual(
            self.other_client.get(f"/api/v1/votes/attempt/{attempt_id}/").status_code,
            404,
        )
