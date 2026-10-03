import pytz
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection
from django.test import TestCase
from django.urls import reverse

from .models import Contest, Contestant, Poll

User = get_user_model()


class PollViewSetTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="test@example.com", name="Test User", password="password123"
        )
        self.poll = Poll.objects.create(
            title="Test Poll",
            slug="test-poll",
            description="A test poll",
            creator=self.user,
            status=Poll.Status.ACTIVE,
            category="Others",
        )
        self.contestant = Contestant.objects.create(name="Contestant 1", poll=self.poll)

    def test_list_polls(self):
        response = self.client.get(reverse("polls:poll-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["title"], "Test Poll")

    def test_vote_free_poll(self):
        url = reverse("polls:poll-vote", kwargs={"slug": self.poll.slug})
        data = {
            "contestant_id": str(self.contestant.id),
            "quantity": 1,
            "email": "voter@example.com",
        }
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])

        # Verify the vote was recorded
        self.contestant.refresh_from_db()
        self.assertEqual(self.contestant.votes, 1)

    def test_vote_rate_limit(self):
        # Cast 3 votes quickly (the limit is 3 per 10 seconds)
        url = reverse("polls:poll-vote", kwargs={"slug": self.poll.slug})
        data = {
            "contestant_id": str(self.contestant.id),
            "quantity": 1,
            "email": "voter@example.com",
        }

        for _ in range(3):
            res = self.client.post(url, data, format="json", REMOTE_ADDR="127.0.0.1")
            self.assertEqual(res.status_code, status.HTTP_200_OK)

        # The 4th vote should be rate-limited
        res_limited = self.client.post(
            url, data, format="json", REMOTE_ADDR="127.0.0.1"
        )
        self.assertEqual(res_limited.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_create_poll_with_nested_contestants(self):
        self.client.force_authenticate(user=self.user)
        url = reverse("polls:poll-list")
        import json

        data = {
            "title": "New Nested Poll",
            "category": "Tech",
            "description": "Nested poll test",
            "status": "active",
            "contestants": json.dumps(
                [
                    {"name": "Dev A", "author": "Alice"},
                    {"name": "Dev B", "author": "Bob"},
                ]
            ),
        }

        response = self.client.post(url, data, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        poll = Poll.objects.get(id=response.data["id"])
        self.assertEqual(poll.contestants.count(), 2)
        names = [c.name for c in poll.contestants.all()]
        self.assertIn("Dev A", names)
        self.assertIn("Dev B", names)

        # Test the add_contestant endpoint
        add_url = reverse("polls:poll-add-contestant", kwargs={"slug": poll.slug})
        add_data = {"name": "Dev C", "author": "Charlie"}
        add_response = self.client.post(add_url, add_data, format="json")
        self.assertEqual(add_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(poll.contestants.count(), 3)

    def test_create_poll_with_form_data_array_contestants(self):
        self.client.force_authenticate(user=self.user)
        url = reverse("polls:poll-list")

        data = {
            "title": "Form Data Array Poll",
            "category": "Tech",
            "description": "Form data array test",
            "status": "active",
            "contestants[0][name]": "Dev X",
            "contestants[0][author]": "Xavier",
            "contestants[1][name]": "Dev Y",
            "contestants[1][author]": "Yara",
        }

        response = self.client.post(url, data, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        poll = Poll.objects.get(id=response.data["id"])
        self.assertEqual(poll.contestants.count(), 2)
        names = [c.name for c in poll.contestants.all()]
        self.assertIn("Dev X", names)
        self.assertIn("Dev Y", names)


class ContestModelTest(TestCase):
    """
    Test suite for Contest model.

    Requirements validated:
    - 2.1: Contest state field with DRAFT default
    - 2.2: Timezone field validation
    - 2.3: CHECK constraint for time_range
    """

    def setUp(self):
        """Create test user for use in test cases."""
        self.user = User.objects.create_user(
            email="organizer@example.com",
            name="Test Organizer",
            password="testpass123",
        )

    def test_initial_state_is_draft(self):
        """
        Test that when a Contest is created, the state field defaults to DRAFT.
        **Validates: Requirements 2.1**
        """
        contest = Contest.objects.create(
            title="New Contest",
            organizer=self.user,
        )

        # Verify the state defaults to DRAFT
        self.assertEqual(contest.state, Contest.State.DRAFT)

    def test_contest_accepts_all_valid_state_values(self):
        """
        Test that the state field accepts all valid state enum values.
        **Validates: Requirements 2.1**
        """
        valid_states = [
            Contest.State.DRAFT,
            Contest.State.SCHEDULED,
            Contest.State.LIVE,
            Contest.State.PAUSED,
            Contest.State.CLOSED,
            Contest.State.CANCELLED,
            Contest.State.ARCHIVED,
            Contest.State.SUSPENDED,
        ]

        for state in valid_states:
            contest = Contest.objects.create(
                title=f"Contest {state}",
                organizer=self.user,
                state=state,
            )
            self.assertEqual(contest.state, state)

    def test_contest_state_rejects_invalid_values(self):
        """
        Test that attempting to set an invalid state value raises an error.
        **Validates: Requirements 2.1**
        """
        contest = Contest.objects.create(
            title="Test Contest",
            organizer=self.user,
        )

        # Attempting to set an invalid state should fail validation
        contest.state = "INVALID_STATE"

        with self.assertRaises(ValidationError):
            contest.full_clean()  # This triggers model validation

    def test_timezone_field_validation_with_valid_timezone(self):
        """
        Test that the timezone field accepts valid IANA timezone identifiers.
        **Validates: Requirements 2.2, 2.3**
        """
        valid_timezones = [
            "UTC",
            "America/New_York",
            "Europe/London",
            "Asia/Tokyo",
            "Africa/Lagos",
            "Australia/Sydney",
        ]

        for tz in valid_timezones:
            contest = Contest.objects.create(
                title=f"Contest {tz}",
                organizer=self.user,
                timezone=tz,
            )
            self.assertEqual(contest.timezone, tz)

            # Verify it's a valid timezone that pytz can use
            try:
                pytz.timezone(tz)
            except pytz.exceptions.UnknownTimeZoneError:
                self.fail(f"{tz} should be a valid timezone")

    def test_timezone_field_defaults_to_utc(self):
        """
        Test that the timezone field defaults to 'UTC' when not specified.
        **Validates: Requirements 2.2**
        """
        contest = Contest.objects.create(
            title="Default Timezone Contest",
            organizer=self.user,
        )

        self.assertEqual(contest.timezone, "UTC")

    def test_check_constraint_for_valid_time_range(self):
        """
        Test that the CHECK constraint allows valid time ranges (end_time >= start_time).
        **Validates: Requirements 2.3**
        """
        from django.utils import timezone as django_timezone

        # Valid: end_time is after start_time
        start_time = django_timezone.now()
        end_time = start_time + django_timezone.timedelta(hours=2)

        contest = Contest.objects.create(
            title="Valid Time Range Contest",
            organizer=self.user,
            start_time=start_time,
            end_time=end_time,
        )

        # Should save successfully
        self.assertIsNotNone(contest.id)
        self.assertEqual(contest.start_time, start_time)
        self.assertEqual(contest.end_time, end_time)

    def test_check_constraint_for_equal_start_and_end_time(self):
        """
        Test that the CHECK constraint allows start_time == end_time.
        **Validates: Requirements 2.3**
        """
        from django.utils import timezone as django_timezone

        # Edge case: end_time equals start_time (should be valid)
        same_time = django_timezone.now()

        contest = Contest.objects.create(
            title="Equal Time Contest",
            organizer=self.user,
            start_time=same_time,
            end_time=same_time,
        )

        # Should save successfully
        self.assertIsNotNone(contest.id)

    def test_check_constraint_rejects_invalid_time_range(self):
        """
        Test that the CHECK constraint rejects end_time < start_time.
        **Validates: Requirements 2.3**
        """
        from django.utils import timezone as django_timezone

        # Invalid: end_time is before start_time
        start_time = django_timezone.now()
        end_time = start_time - django_timezone.timedelta(hours=2)

        with self.assertRaises(IntegrityError) as context:
            Contest.objects.create(
                title="Invalid Time Range Contest",
                organizer=self.user,
                start_time=start_time,
                end_time=end_time,
            )

        # Verify the error is related to the check constraint
        self.assertIn("valid_time_range", str(context.exception))

    def test_check_constraint_allows_null_start_time(self):
        """
        Test that the CHECK constraint allows NULL start_time with any end_time.
        **Validates: Requirements 2.3**
        """
        from django.utils import timezone as django_timezone

        end_time = django_timezone.now()

        contest = Contest.objects.create(
            title="Null Start Time Contest",
            organizer=self.user,
            start_time=None,
            end_time=end_time,
        )

        # Should save successfully
        self.assertIsNotNone(contest.id)
        self.assertIsNone(contest.start_time)
        self.assertEqual(contest.end_time, end_time)

    def test_check_constraint_allows_null_end_time(self):
        """
        Test that the CHECK constraint allows NULL end_time with any start_time.
        **Validates: Requirements 2.3**
        """
        from django.utils import timezone as django_timezone

        start_time = django_timezone.now()

        contest = Contest.objects.create(
            title="Null End Time Contest",
            organizer=self.user,
            start_time=start_time,
            end_time=None,
        )

        # Should save successfully
        self.assertIsNotNone(contest.id)
        self.assertEqual(contest.start_time, start_time)
        self.assertIsNone(contest.end_time)

    def test_check_constraint_allows_both_times_null(self):
        """
        Test that the CHECK constraint allows both start_time and end_time to be NULL.
        **Validates: Requirements 2.3**
        """
        contest = Contest.objects.create(
            title="Both Times Null Contest",
            organizer=self.user,
            start_time=None,
            end_time=None,
        )

        # Should save successfully
        self.assertIsNotNone(contest.id)
        self.assertIsNone(contest.start_time)
        self.assertIsNone(contest.end_time)

    def test_contest_slug_auto_generation(self):
        """
        Test that slug is auto-generated from title if not provided.
        **Validates: Requirements 2.1**
        """
        contest = Contest.objects.create(
            title="My Test Contest",
            organizer=self.user,
        )

        self.assertEqual(contest.slug, "my-test-contest")

    def test_contest_slug_uniqueness(self):
        """
        Test that duplicate slugs are handled with incremental suffixes.
        **Validates: Requirements 2.1**
        """
        contest1 = Contest.objects.create(
            title="Same Title",
            organizer=self.user,
        )
        contest2 = Contest.objects.create(
            title="Same Title",
            organizer=self.user,
        )

        self.assertEqual(contest1.slug, "same-title")
        self.assertEqual(contest2.slug, "same-title-1")

    def test_contest_results_visibility_default(self):
        """
        Test that results_visibility defaults to AFTER_CLOSE.
        **Validates: Requirements 2.1**
        """
        contest = Contest.objects.create(
            title="Results Visibility Contest",
            organizer=self.user,
        )

        self.assertEqual(
            contest.results_visibility, Contest.ResultsVisibility.AFTER_CLOSE
        )

    def test_contest_version_field_defaults_to_zero(self):
        """
        Test that the version field defaults to 0 for optimistic locking.
        **Validates: Requirements 2.1**
        """
        contest = Contest.objects.create(
            title="Version Test Contest",
            organizer=self.user,
        )

        self.assertEqual(contest.version, 0)

    def test_contest_timestamps_auto_populated(self):
        """
        Test that created_at and updated_at timestamps are automatically set.
        **Validates: Requirements 2.1**
        """
        contest = Contest.objects.create(
            title="Timestamp Contest",
            organizer=self.user,
        )

        self.assertIsNotNone(contest.created_at)
        self.assertIsNotNone(contest.updated_at)

    def test_contest_state_timestamp_fields_nullable(self):
        """
        Test that published_at and closed_at are NULL by default.
        **Validates: Requirements 2.1**
        """
        contest = Contest.objects.create(
            title="State Timestamp Contest",
            organizer=self.user,
        )

        self.assertIsNone(contest.published_at)
        self.assertIsNone(contest.closed_at)

    def test_contest_str_representation(self):
        """
        Test the string representation of Contest includes title and state.
        **Validates: Requirements 2.1**
        """
        contest = Contest.objects.create(
            title="String Test Contest",
            organizer=self.user,
            state=Contest.State.LIVE,
        )

        expected_str = "String Test Contest (LIVE)"
        self.assertEqual(str(contest), expected_str)

    def test_contest_organizer_cascade_delete(self):
        """
        Test that deleting organizer cascades to delete contests.
        **Validates: Requirements 2.1**
        """
        contest = Contest.objects.create(
            title="Cascade Test Contest",
            organizer=self.user,
        )
        contest_id = contest.id

        # Delete the organizer
        self.user.delete()

        # Verify contest is also deleted
        self.assertFalse(Contest.objects.filter(id=contest_id).exists())

    def test_contest_database_indexes_exist(self):
        """
        Test that database indexes are created for key fields.
        **Validates: Requirements 2.1**
        """
        table_name = Contest._meta.db_table

        with connection.cursor() as cursor:
            # PostgreSQL-specific query to check for indexes
            cursor.execute(
                """
                SELECT indexname 
                FROM pg_indexes 
                WHERE tablename = %s
                """,
                [table_name],
            )
            indexes = cursor.fetchall()
            index_names = [idx[0] for idx in indexes]

            # Check that indexes exist (the exact names may vary)
            self.assertGreater(len(indexes), 0, "No indexes found on Contest table")

            # Verify key fields have indexes
            _index_str = " ".join(index_names)
            self.assertTrue(
                any("slug" in idx for idx in index_names), "No index on slug field"
            )
            self.assertTrue(
                any("state" in idx for idx in index_names), "No index on state field"
            )
