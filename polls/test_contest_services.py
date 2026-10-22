from datetime import timedelta
from types import SimpleNamespace
import uuid
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from hypothesis import given, settings as hypothesis_settings, strategies as st
from hypothesis.extra.django import SimpleTestCase as HypothesisSimpleTestCase
from hypothesis.extra.django import TestCase as HypothesisTestCase

from accounts.models import User
from config.errors import StateConflictError
from polls.models import Contest
from polls.services import (
    VALID_STATE_TRANSITIONS,
    can_view_results,
    close_due_contests,
    contest_accepts_votes,
    local_contest_time,
    transition_state,
)


class ContestStateServiceTests(TestCase):
    def setUp(self):
        self.organizer = User.objects.create_user(
            email="organizer@example.com", name="Organizer", password="StrongPassword123!", role=User.Role.ORGANIZER
        )
        self.contest = Contest.objects.create(
            organizer=self.organizer,
            title="A Contest",
            slug="a-contest",
            timezone="Africa/Lagos",
            start_time=timezone.now(),
            end_time=timezone.now() + timedelta(days=1),
        )

    def test_draft_to_live_sets_published_timestamp(self):
        result = transition_state(self.contest, Contest.State.LIVE, self.organizer)
        self.assertEqual(result.state, Contest.State.LIVE)
        self.assertIsNotNone(result.published_at)
        self.assertEqual(result.version, 1)

    def test_live_to_closed_sets_closed_timestamp(self):
        self.contest.state = Contest.State.LIVE
        self.contest.version = 1
        self.contest.save(update_fields=["state", "version"])
        result = transition_state(self.contest, Contest.State.CLOSED, self.organizer)
        self.assertEqual(result.state, Contest.State.CLOSED)
        self.assertIsNotNone(result.closed_at)

    def test_invalid_transition_raises_validation_error(self):
        with self.assertRaises(ValidationError):
            transition_state(self.contest, Contest.State.ARCHIVED, self.organizer)

    def test_stale_version_is_rejected(self):
        stale = Contest.objects.get(pk=self.contest.pk)
        current = Contest.objects.get(pk=self.contest.pk)
        transition_state(current, Contest.State.SCHEDULED, self.organizer)
        with self.assertRaises(StateConflictError):
            transition_state(stale, Contest.State.LIVE, self.organizer)

    def test_timezone_conversion_is_aware_and_contest_local(self):
        local_time = local_contest_time(self.contest, self.contest.start_time)
        self.assertEqual(local_time.tzinfo, ZoneInfo("Africa/Lagos"))

    def test_due_contests_are_closed(self):
        self.contest.start_time = timezone.now() - timedelta(days=2)
        self.contest.state = Contest.State.LIVE
        self.contest.end_time = timezone.now() - timedelta(minutes=1)
        self.contest.save(update_fields=["state", "start_time", "end_time"])
        self.assertEqual(close_due_contests(), 1)
        self.contest.refresh_from_db()
        self.assertEqual(self.contest.state, Contest.State.CLOSED)



class ContestTransitionPropertyTests(HypothesisTestCase):
    @hypothesis_settings(max_examples=10, deadline=None)
    @given(
        source=st.sampled_from(Contest.State.values),
        target=st.sampled_from(Contest.State.values),
    )
    def test_transition_property_matches_declared_graph(self, source, target):
        suffix = uuid.uuid4().hex
        organizer = User.objects.create_user(
            email=f"property-{suffix}@example.com",
            name="Property Organizer",
            password="StrongPassword123!",
            role=User.Role.ORGANIZER,
        )
        contest = Contest.objects.create(
            organizer=organizer,
            title="Property Contest",
            slug=f"property-contest-{suffix}",
            state=source,
        )
        if target in VALID_STATE_TRANSITIONS[source]:
            transition_state(contest, target, organizer)
            self.assertEqual(Contest.objects.get(pk=contest.pk).state, target)
        else:
            with self.assertRaises(ValidationError):
                transition_state(contest, target, organizer)


class ContestResultsVisibilityPropertyTests(HypothesisSimpleTestCase):
    @hypothesis_settings(max_examples=35)
    @given(
        visibility=st.sampled_from(Contest.ResultsVisibility.values),
        state=st.sampled_from(Contest.State.values),
    )
    def test_results_visibility_property(self, visibility, state):
        contest = SimpleNamespace(results_visibility=visibility, state=state)
        if visibility == Contest.ResultsVisibility.REAL_TIME:
            expected = True
        elif visibility == Contest.ResultsVisibility.NEVER:
            expected = False
        else:
            expected = state in (Contest.State.CLOSED, Contest.State.ARCHIVED)
        self.assertEqual(can_view_results(contest), expected)


class ContestVoteAvailabilityPropertyTests(HypothesisSimpleTestCase):
    @hypothesis_settings(max_examples=30)
    @given(state=st.sampled_from(Contest.State.values))
    def test_only_live_contests_accept_vote_attempts(self, state):
        self.assertEqual(contest_accepts_votes(state), state == Contest.State.LIVE)
