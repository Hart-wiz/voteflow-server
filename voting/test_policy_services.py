import uuid
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from hypothesis import given, settings as hypothesis_settings, strategies as st
from hypothesis.extra.django import SimpleTestCase as HypothesisSimpleTestCase
from hypothesis.extra.django import TestCase as HypothesisTestCase

from accounts.models import User
from polls.models import Contest, Contestant, Poll
from voting.models import VoterIdentity, VoterVerification, Vote, VotingPolicy
from voting.policies import (
    check_composite_verification,
    check_vote_limit,
    identity_status_allows_voting,
    requires_verification,
    verification_methods_satisfied,
)


class VotingPolicyServiceTests(TestCase):
    def setUp(self):
        self.organizer = User.objects.create_user(
            email="organizer@example.com", name="Organizer", password="StrongPassword123!", role=User.Role.ORGANIZER
        )
        self.voter = User.objects.create_user(
            email="voter@example.com", name="Voter", password="StrongPassword123!"
        )
        self.poll = Poll.objects.create(creator=self.organizer, title="Policy Poll", slug="policy-poll")
        self.contest = Contest.objects.create(
            organizer=self.organizer,
            source_poll=self.poll,
            title="Policy Contest",
            slug="policy-contest",
        )
        self.contestant = Contestant.objects.create(poll=self.poll, name="Option A")
        self.identity = VoterIdentity.objects.create(user=self.voter, contest=self.contest)
        self.policy = VotingPolicy.objects.create(contest=self.contest)

    def _create_vote(self, number, quantity=1):
        return Vote.objects.create(
            poll=self.poll,
            contestant=self.contestant,
            voter=self.voter,
            voter_identity=self.identity,
            vote_number=number,
            quantity=quantity,
            vote_quantity=quantity,
        )

    def test_one_vote_limit_blocks_second_vote(self):
        self.policy.vote_limit_type = VotingPolicy.VoteLimitType.ONE
        self.policy.save()
        self._create_vote(1)
        with self.assertRaises(ValidationError):
            check_vote_limit(self.voter, self.contest, 1)

    def test_limited_vote_limit_respects_quantity(self):
        self.policy.vote_limit_type = VotingPolicy.VoteLimitType.LIMITED
        self.policy.max_votes_per_voter = 5
        self.policy.save()
        self._create_vote(1, quantity=3)
        self.assertTrue(check_vote_limit(self.voter, self.contest, 2))
        with self.assertRaises(ValidationError):
            check_vote_limit(self.voter, self.contest, 3)

    def test_unlimited_allows_any_valid_quantity(self):
        self.assertTrue(check_vote_limit(self.voter, self.contest, 1000))

    def test_quantity_outside_supported_range_is_rejected(self):
        for quantity in (0, 1001):
            with self.assertRaises(ValidationError):
                check_vote_limit(self.voter, self.contest, quantity)

    def test_verification_requirement_matches_policy(self):
        self.assertFalse(requires_verification(self.contest))
        self.policy.verification_method = VotingPolicy.VerificationMethod.EMAIL
        self.policy.save()
        self.assertTrue(requires_verification(self.contest))

    def test_composite_verification_requires_all_methods(self):
        required = [VotingPolicy.VerificationMethod.EMAIL, VotingPolicy.VerificationMethod.PHONE]
        self.policy.verification_method = VotingPolicy.VerificationMethod.COMPOSITE
        self.policy.required_verification_methods = required
        self.policy.save()
        VoterVerification.objects.create(
            voter_identity=self.identity,
            provider="resend",
            method=VotingPolicy.VerificationMethod.EMAIL,
            status=VoterVerification.Status.SUCCESS,
        )
        self.assertFalse(check_composite_verification(self.identity, required))
        VoterVerification.objects.create(
            voter_identity=self.identity,
            provider="identity_gateway",
            method=VotingPolicy.VerificationMethod.PHONE,
            status=VoterVerification.Status.SUCCESS,
        )
        self.assertTrue(check_composite_verification(self.identity, required))



class VoteLimitPropertyTests(HypothesisTestCase):
    @hypothesis_settings(max_examples=10, deadline=None)
    @given(prior=st.integers(min_value=0, max_value=20), quantity=st.integers(min_value=1, max_value=10))
    def test_limited_policy_property(self, prior, quantity):
        suffix = uuid.uuid4().hex
        organizer = User.objects.create_user(
            email=f"organizer-{suffix}@example.com",
            name="Organizer",
            password="StrongPassword123!",
            role=User.Role.ORGANIZER,
        )
        voter = User.objects.create_user(
            email=f"voter-{suffix}@example.com",
            name="Voter",
            password="StrongPassword123!",
        )
        poll = Poll.objects.create(creator=organizer, title="Policy Poll", slug=f"policy-poll-{suffix}")
        contest = Contest.objects.create(
            organizer=organizer,
            source_poll=poll,
            title="Policy Contest",
            slug=f"policy-contest-{suffix}",
        )
        contestant = Contestant.objects.create(poll=poll, name="Option A")
        identity = VoterIdentity.objects.create(user=voter, contest=contest)
        VotingPolicy.objects.create(
            contest=contest,
            vote_limit_type=VotingPolicy.VoteLimitType.LIMITED,
            max_votes_per_voter=10,
        )
        for number in range(1, prior + 1):
            Vote.objects.create(
                poll=poll,
                contestant=contestant,
                voter=voter,
                voter_identity=identity,
                vote_number=number,
                vote_quantity=1,
            )
        if prior + quantity <= 10:
            self.assertTrue(check_vote_limit(voter, contest, quantity))
        else:
            with self.assertRaises(ValidationError):
                check_vote_limit(voter, contest, quantity)


class CompositeVerificationPropertyTests(HypothesisSimpleTestCase):
    METHODS = ["EMAIL", "PHONE", "NIN", "VOTERS_CARD", "FINGERPRINT"]

    @hypothesis_settings(max_examples=60)
    @given(
        required=st.lists(
            st.sampled_from(METHODS), min_size=2, max_size=5, unique=True
        ),
        successful=st.sets(st.sampled_from(METHODS)),
    )
    def test_composite_verification_requires_every_method(self, required, successful):
        self.assertEqual(
            verification_methods_satisfied(required, successful),
            set(required) <= successful,
        )


class IdentityStatusPropertyTests(HypothesisSimpleTestCase):
    @hypothesis_settings(max_examples=40)
    @given(
        status=st.sampled_from(VoterIdentity.VerificationStatus.values),
        expired=st.booleans(),
    )
    def test_only_current_verified_identities_are_allowed(self, status, expired):
        now = timezone.now()
        expires_at = now - timedelta(seconds=1) if expired else now + timedelta(seconds=1)
        self.assertEqual(
            identity_status_allows_voting(status, expires_at, now),
            status == VoterIdentity.VerificationStatus.VERIFIED and not expired,
        )

