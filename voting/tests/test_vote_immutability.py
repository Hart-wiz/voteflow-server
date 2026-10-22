"""
Tests for Vote immutability enforcement via database triggers.

Tests task 3.3: Database triggers prevent UPDATE and DELETE operations on Vote records.
Validates Requirement 5.4: Vote immutability.
"""

import pytest
import uuid
from django.db import IntegrityError, connection, transaction
from django.test import TestCase, TransactionTestCase

from accounts.models import User
from polls.models import Contest, Contestant, Poll
from voting.models import Vote, VoterIdentity


def _install_test_vote_triggers():
    """Restore the immutable-vote triggers after TransactionTestCase flushes."""
    with connection.cursor() as cursor:
        if connection.vendor == "postgresql":
            cursor.execute(
                "SELECT tgname FROM pg_trigger "
                "WHERE tgname IN ('prevent_vote_update', 'prevent_vote_delete') "
                "AND NOT tgisinternal"
            )
            existing = {row[0] for row in cursor.fetchall()}
            if len(existing) == 2:
                return
            cursor.execute(
                """
                CREATE OR REPLACE FUNCTION prevent_vote_modification()
                RETURNS TRIGGER AS $$
                BEGIN
                    RAISE EXCEPTION 'Votes cannot be modified or deleted';
                END;
                $$ LANGUAGE plpgsql
                """
            )
            if "prevent_vote_update" not in existing:
                cursor.execute(
                    "CREATE TRIGGER prevent_vote_update BEFORE UPDATE ON voting_vote "
                    "FOR EACH ROW EXECUTE FUNCTION prevent_vote_modification()"
                )
            if "prevent_vote_delete" not in existing:
                cursor.execute(
                    "CREATE TRIGGER prevent_vote_delete BEFORE DELETE ON voting_vote "
                    "FOR EACH ROW EXECUTE FUNCTION prevent_vote_modification()"
                )
        elif connection.vendor == "sqlite":
            cursor.execute(
                "CREATE TRIGGER IF NOT EXISTS prevent_vote_update BEFORE UPDATE "
                "ON voting_vote BEGIN SELECT RAISE(ABORT, "
                "'Votes cannot be modified or deleted'); END"
            )
            cursor.execute(
                "CREATE TRIGGER IF NOT EXISTS prevent_vote_delete BEFORE DELETE "
                "ON voting_vote BEGIN SELECT RAISE(ABORT, "
                "'Votes cannot be modified or deleted'); END"
            )


def _remove_test_vote_triggers():
    with connection.cursor() as cursor:
        if connection.vendor == "postgresql":
            cursor.execute("DROP TRIGGER IF EXISTS prevent_vote_update ON voting_vote")
            cursor.execute("DROP TRIGGER IF EXISTS prevent_vote_delete ON voting_vote")
            cursor.execute("DROP FUNCTION IF EXISTS prevent_vote_modification()")
        elif connection.vendor == "sqlite":
            cursor.execute("DROP TRIGGER IF EXISTS prevent_vote_update")
            cursor.execute("DROP TRIGGER IF EXISTS prevent_vote_delete")


class VoteTriggerTransactionTestCase(TransactionTestCase):
    """Keep trigger-protected votes testable while Django flushes test rows."""

    @classmethod
    def _fixture_setup(cls):
        super()._fixture_setup()
        _install_test_vote_triggers()

    def _fixture_teardown(self):
        _remove_test_vote_triggers()
        try:
            super()._fixture_teardown()
        finally:
            _install_test_vote_triggers()


@pytest.mark.django_db
class TestVoteImmutabilityTriggers(VoteTriggerTransactionTestCase):
    """
    Test suite for Vote immutability database triggers.

    Uses TransactionTestCase because we need to test database-level
    triggers which require actual database commits.
    """

    def setUp(self):
        """Create test data for vote immutability tests."""
        # Create user
        self.user = User.objects.create(
            email="voter@example.com", name="Test Voter", password="testpass123"
        )

        # Create organizer
        self.organizer = User.objects.create(
            email="organizer@example.com",
            name="Test Organizer",
            role=User.Role.ORGANIZER,
            password="testpass123",
        )

        # Create poll (using Poll model as per current codebase)
        self.poll = Poll.objects.create(
            title="Test Poll",
            description="Test poll for immutability",
            creator=self.organizer,
            status="active",
        )

        # VoterIdentity is contest-scoped. Mirror the legacy Poll UUID in a
        # Contest record so this fixture satisfies the current foreign key.
        self.contest = Contest.objects.create(
            id=self.poll.id,
            source_poll=self.poll,
            organizer=self.organizer,
            title=self.poll.title,
        )

        # Create contestant
        self.contestant = Contestant.objects.create(
            poll=self.poll,
            name="Test Contestant",
            description="Test contestant",
            votes=0,
        )

        # Create voter identity
        self.voter_identity = VoterIdentity.objects.create(
            user=self.user,
            contest=self.contest,
            verification_status=VoterIdentity.VerificationStatus.VERIFIED,
        )

        # Create a vote
        self.vote = Vote.objects.create(
            poll=self.poll,
            contestant=self.contestant,
            voter_identity=self.voter_identity,
            voter=self.user,
            vote_number=1,
            vote_quantity=1,
            device_identifier="test-device",
            ip_hash="abc123def456",
            quantity=1,
        )

    def test_vote_update_is_blocked(self):
        """
        Test that attempting to UPDATE a Vote record raises an exception.

        Validates: Requirement 5.4 - Vote immutability
        """
        # Attempt to update the vote
        with self.assertRaises(Exception) as context:
            self.vote.vote_quantity = 5
            self.vote.save()

        # Verify the exception message indicates immutability
        self.assertIn("cannot be modified", str(context.exception).lower())

    def test_vote_delete_is_blocked(self):
        """
        Test that attempting to DELETE a Vote record raises an exception.

        Validates: Requirement 5.4 - Vote immutability
        """
        # Attempt to delete the vote
        with self.assertRaises(Exception) as context:
            self.vote.delete()

        # Verify the exception message indicates immutability
        self.assertIn("cannot be", str(context.exception).lower())

    def test_vote_bulk_update_is_blocked(self):
        """
        Test that bulk UPDATE operations are also blocked.

        Validates: Requirement 5.4 - Vote immutability
        """
        # Attempt bulk update
        with self.assertRaises(Exception) as context:
            Vote.objects.filter(id=self.vote.id).update(vote_quantity=10)

        # Verify operation was blocked
        self.assertIn("cannot be modified", str(context.exception).lower())

    def test_vote_bulk_delete_is_blocked(self):
        """
        Test that bulk DELETE operations are also blocked.

        Validates: Requirement 5.4 - Vote immutability
        """
        # Attempt bulk delete
        with self.assertRaises(Exception) as context:
            Vote.objects.filter(id=self.vote.id).delete()

        # Verify operation was blocked
        self.assertIn("cannot be", str(context.exception).lower())

    def test_vote_creation_still_works(self):
        """
        Test that creating new Vote records still works normally.

        The immutability triggers should only prevent UPDATE/DELETE,
        not INSERT operations.
        """
        # Create a new vote
        new_vote = Vote.objects.create(
            poll=self.poll,
            contestant=self.contestant,
            voter_identity=self.voter_identity,
            voter=self.user,
            vote_number=2,
            vote_quantity=1,
            device_identifier="test-device-2",
            ip_hash="xyz789ghi012",
            quantity=1,
        )

        # Verify the vote was created
        self.assertIsNotNone(new_vote.id)
        self.assertEqual(new_vote.vote_number, 2)

        # Verify it's persisted in the database
        retrieved_vote = Vote.objects.get(id=new_vote.id)
        self.assertEqual(retrieved_vote.vote_number, 2)

    def test_trigger_function_exists(self):
        """
        Test that the prevent_vote_modification() function exists in the database.
        """
        with connection.cursor() as cursor:
            if connection.vendor == "postgresql":
                cursor.execute(
                    "SELECT EXISTS (SELECT 1 FROM pg_proc "
                    "WHERE proname = 'prevent_vote_modification')"
                )
            else:
                cursor.execute(
                    "SELECT EXISTS (SELECT 1 FROM sqlite_master "
                    "WHERE type = 'trigger' AND name = 'prevent_vote_update')"
                )
            function_exists = cursor.fetchone()[0]

        self.assertTrue(
            function_exists, "prevent_vote_modification() function should exist"
        )

    def test_update_trigger_exists(self):
        """
        Test that the UPDATE trigger exists on voting_vote table.
        """
        with connection.cursor() as cursor:
            if connection.vendor == "postgresql":
                cursor.execute(
                    "SELECT EXISTS (SELECT 1 FROM pg_trigger "
                    "WHERE tgname = 'prevent_vote_update')"
                )
            else:
                cursor.execute(
                    "SELECT EXISTS (SELECT 1 FROM sqlite_master "
                    "WHERE type = 'trigger' AND name = 'prevent_vote_update')"
                )
            trigger_exists = cursor.fetchone()[0]

        self.assertTrue(trigger_exists, "prevent_vote_update trigger should exist")

    def test_delete_trigger_exists(self):
        """
        Test that the DELETE trigger exists on voting_vote table.
        """
        with connection.cursor() as cursor:
            if connection.vendor == "postgresql":
                cursor.execute(
                    "SELECT EXISTS (SELECT 1 FROM pg_trigger "
                    "WHERE tgname = 'prevent_vote_delete')"
                )
            else:
                cursor.execute(
                    "SELECT EXISTS (SELECT 1 FROM sqlite_master "
                    "WHERE type = 'trigger' AND name = 'prevent_vote_delete')"
                )
            trigger_exists = cursor.fetchone()[0]

        self.assertTrue(trigger_exists, "prevent_vote_delete trigger should exist")

    def test_vote_remains_unchanged_after_failed_update(self):
        """
        Test that a Vote record remains unchanged after a failed update attempt.

        Validates: Requirement 5.4 - Vote immutability ensures data integrity
        """
        original_quantity = self.vote.vote_quantity
        original_device = self.vote.device_identifier

        # Attempt to update (should fail)
        try:
            self.vote.vote_quantity = 100
            self.vote.device_identifier = "hacked-device"
            self.vote.save()
        except IntegrityError:
            pass  # Expected to fail

        # Refresh from database
        self.vote.refresh_from_db()

        # Verify values haven't changed
        self.assertEqual(self.vote.vote_quantity, original_quantity)
        self.assertEqual(self.vote.device_identifier, original_device)


class TestVoteImmutabilityEdgeCases(VoteTriggerTransactionTestCase):
    """
    Additional edge case tests for Vote immutability.
    """

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create(email="voter2@example.com", name="Test Voter 2")

        self.organizer = User.objects.create(
            email="organizer2@example.com",
            name="Test Organizer 2",
            role=User.Role.ORGANIZER,
        )

        self.poll = Poll.objects.create(
            title="Test Poll 2",
            description="Test poll 2",
            creator=self.organizer,
            status="active",
        )

        self.contest = Contest.objects.create(
            id=self.poll.id,
            source_poll=self.poll,
            organizer=self.organizer,
            title=self.poll.title,
        )

        self.contestant = Contestant.objects.create(
            poll=self.poll, name="Test Contestant 2", votes=0
        )

        self.voter_identity = VoterIdentity.objects.create(
            user=self.user,
            contest=self.contest,
            verification_status=VoterIdentity.VerificationStatus.VERIFIED,
        )

    def test_multiple_vote_creation_and_immutability(self):
        """
        Test creating multiple votes and verifying each is immutable.
        """
        votes = []

        # Create 5 votes
        for i in range(1, 6):
            vote = Vote.objects.create(
                poll=self.poll,
                contestant=self.contestant,
                voter_identity=self.voter_identity,
                voter=self.user,
                vote_number=i,
                vote_quantity=1,
                device_identifier=f"device-{i}",
                ip_hash=f"hash-{i}",
                quantity=1,
            )
            votes.append(vote)

        # Verify all votes were created
        self.assertEqual(len(votes), 5)

        # Attempt to modify each vote (should all fail)
        for vote in votes:
            with self.assertRaises(IntegrityError):
                vote.vote_quantity = 999
                vote.save()

        # Verify count is still correct
        self.assertEqual(Vote.objects.filter(poll=self.poll).count(), 5)

    def test_update_attempt_with_different_fields(self):
        """
        Test that updating any field on a Vote is blocked.
        """
        vote = Vote.objects.create(
            poll=self.poll,
            contestant=self.contestant,
            voter_identity=self.voter_identity,
            voter=self.user,
            vote_number=1,
            vote_quantity=1,
            device_identifier="test-device",
            ip_hash="hash123",
            quantity=1,
        )

        # Test updating different fields
        fields_to_test = [
            ("vote_quantity", 5),
            ("device_identifier", "new-device"),
            ("ip_hash", "new-hash"),
            ("is_paid", True),
            ("is_suspicious", True),
        ]

        for field_name, new_value in fields_to_test:
            with self.assertRaises(Exception):
                setattr(vote, field_name, new_value)
                vote.save()

            # Verify value hasn't changed
            vote.refresh_from_db()
            self.assertNotEqual(getattr(vote, field_name), new_value)


"""
Property-Based Tests for Vote Immutability

Tests task 3.5: Property test verifying Vote immutability across random Vote records.
Validates Requirement 5.4: Vote records cannot be modified or deleted.

**Property 10: Vote Immutability**
**Validates: Requirements 5.4**
"""

from hypothesis import given, settings, strategies as st
from hypothesis.extra.django import TestCase as HypothesisTestCase


class TestVoteImmutabilityProperty(HypothesisTestCase):
    """
    Property-based tests for Vote immutability using Hypothesis.

    This test suite generates random Vote records and attempts to modify
    or delete them, verifying that all such attempts fail with database exceptions.
    """

    def setUp(self):
        """Create foundational test data for property tests."""
        _install_test_vote_triggers()
        suffix = uuid.uuid4().hex
        # Create a reusable user and organizer
        self.user = User.objects.create(
            email=f"property-voter-{suffix}@example.com",
            name="Property Test Voter",
            password="testpass123"
        )

        self.organizer = User.objects.create(
            email=f"property-organizer-{suffix}@example.com",
            name="Property Test Organizer",
            role=User.Role.ORGANIZER,
            password="testpass123"
        )

        # Create a poll
        self.poll = Poll.objects.create(
            title="Property Test Poll",
            description="Poll for property-based testing",
            creator=self.organizer,
            status="active"
        )

        self.contest = Contest.objects.create(
            id=self.poll.id,
            source_poll=self.poll,
            organizer=self.organizer,
            title=self.poll.title,
        )

        # Create a contestant
        self.contestant = Contestant.objects.create(
            poll=self.poll,
            name="Property Test Contestant",
            description="Contestant for property testing",
            votes=0
        )

        # Create voter identity
        self.voter_identity = VoterIdentity.objects.create(
            user=self.user,
            contest=self.contest,
            verification_status=VoterIdentity.VerificationStatus.VERIFIED
        )

    @given(
        vote_quantity=st.integers(min_value=1, max_value=1000),
        device_id=st.text(min_size=1, max_size=255, alphabet=st.characters(blacklist_categories=['Cs', 'Cc'])),
        ip_hash=st.text(min_size=8, max_size=64, alphabet=st.characters(min_codepoint=33, max_codepoint=126)),
    )
    @settings(max_examples=100, deadline=5000)
    def test_vote_update_always_fails_property(self, vote_quantity, device_id, ip_hash):
        """
        Property Test: For any Vote record, UPDATE operations SHALL always fail.

        **Property 10: Vote Immutability**
        **Validates: Requirements 5.4**

        Generates random vote records with varying quantities, device identifiers,
        and IP hashes, then attempts to modify them and verifies all attempts fail.
        """
        # Generate a unique vote number for this test run
        import random
        vote_number = random.randint(1, 1000000)

        # Create a vote with random properties
        vote = Vote.objects.create(
            poll=self.poll,
            contestant=self.contestant,
            voter_identity=self.voter_identity,
            voter=self.user,
            vote_number=vote_number,
            vote_quantity=vote_quantity,
            device_identifier=device_id[:255],  # Ensure within length limit
            ip_hash=ip_hash[:64],  # Ensure within length limit
            quantity=vote_quantity,
        )

        # Store original values
        original_quantity = vote.vote_quantity
        original_device = vote.device_identifier
        original_ip = vote.ip_hash

        # Attempt to update vote_quantity - should fail
        with self.assertRaises(Exception) as context:
            with transaction.atomic():
                vote.vote_quantity = vote_quantity + 100
                vote.save()

        self.assertIn("cannot be modified", str(context.exception).lower())

        # Refresh and verify vote is unchanged
        vote.refresh_from_db()
        self.assertEqual(vote.vote_quantity, original_quantity)
        self.assertEqual(vote.device_identifier, original_device)
        self.assertEqual(vote.ip_hash, original_ip)

        # Clean up for next iteration
        # Note: We can't delete the vote due to immutability, but Django will
        # handle cleanup between test methods via TransactionTestCase

    @given(
        vote_quantity=st.integers(min_value=1, max_value=100),
    )
    @settings(max_examples=100, deadline=5000)
    def test_vote_delete_always_fails_property(self, vote_quantity):
        """
        Property Test: For any Vote record, DELETE operations SHALL always fail.

        **Property 10: Vote Immutability**
        **Validates: Requirements 5.4**

        Generates random vote records and attempts to delete them,
        verifying that all deletion attempts fail with database exceptions.
        """
        import random
        vote_number = random.randint(1, 1000000)

        # Create a vote with random quantity
        vote = Vote.objects.create(
            poll=self.poll,
            contestant=self.contestant,
            voter_identity=self.voter_identity,
            voter=self.user,
            vote_number=vote_number,
            vote_quantity=vote_quantity,
            device_identifier=f"device-{vote_number}",
            ip_hash=f"hash-{vote_number}",
            quantity=vote_quantity,
        )

        vote_id = vote.id

        # Attempt to delete - should fail
        with self.assertRaises(Exception) as context:
            with transaction.atomic():
                vote.delete()

        self.assertIn("cannot be", str(context.exception).lower())

        # Verify vote still exists in database
        self.assertTrue(Vote.objects.filter(id=vote_id).exists())

    @given(
        field_updates=st.lists(
            st.tuples(
                st.sampled_from(['vote_quantity', 'device_identifier', 'ip_hash', 'is_paid', 'is_suspicious']),
                st.one_of(
                    st.integers(min_value=1, max_value=1000),
                    st.text(min_size=1, max_size=100, alphabet=st.characters(blacklist_categories=['Cs', 'Cc'])),
                    st.booleans()
                )
            ),
            min_size=1,
            max_size=5,
            unique_by=lambda x: x[0]  # Ensure unique field names
        )
    )
    @settings(max_examples=50, deadline=5000)
    def test_vote_any_field_update_fails_property(self, field_updates):
        """
        Property Test: For any Vote record, updating ANY field SHALL fail.

        **Property 10: Vote Immutability**
        **Validates: Requirements 5.4**

        Generates random combinations of field updates and verifies that
        attempting to modify any field on a Vote record fails.
        """
        import random
        vote_number = random.randint(1, 1000000)

        # Create a vote
        vote = Vote.objects.create(
            poll=self.poll,
            contestant=self.contestant,
            voter_identity=self.voter_identity,
            voter=self.user,
            vote_number=vote_number,
            vote_quantity=1,
            device_identifier=f"device-{vote_number}",
            ip_hash=f"hash-{vote_number}",
            quantity=1,
        )

        # Attempt to update each field - all should fail
        for field_name, new_value in field_updates:
            # Store original value
            original_value = getattr(vote, field_name)

            # Attempt update
            with self.assertRaises(Exception):
                with transaction.atomic():
                    # Convert value to appropriate type for the field
                    if field_name == 'vote_quantity':
                        new_value = int(new_value) if isinstance(new_value, int) else 1
                    elif field_name in ['device_identifier', 'ip_hash']:
                        new_value = str(new_value)[:255] if isinstance(new_value, str) else "test"
                    elif field_name in ['is_paid', 'is_suspicious']:
                        new_value = bool(new_value) if isinstance(new_value, bool) else False

                    setattr(vote, field_name, new_value)
                    vote.save()

            # Refresh and verify field hasn't changed
            vote.refresh_from_db()
            current_value = getattr(vote, field_name)

            # Values should remain unchanged
            self.assertEqual(current_value, original_value,
                           f"Field {field_name} should not have changed from {original_value}")

    @given(
        num_votes=st.integers(min_value=2, max_value=10),
    )
    @settings(max_examples=50, deadline=10000)
    def test_bulk_operations_fail_property(self, num_votes):
        """
        Property Test: Bulk UPDATE and DELETE operations SHALL fail for any set of Votes.

        **Property 10: Vote Immutability**
        **Validates: Requirements 5.4**

        Generates multiple vote records and attempts bulk operations,
        verifying that all bulk modifications are blocked.
        """
        import random
        base_vote_number = random.randint(1, 100000)

        # Create multiple votes
        created_votes = []
        for i in range(num_votes):
            vote = Vote.objects.create(
                poll=self.poll,
                contestant=self.contestant,
                voter_identity=self.voter_identity,
                voter=self.user,
                vote_number=base_vote_number + i,
                vote_quantity=i + 1,
                device_identifier=f"bulk-device-{base_vote_number}-{i}",
                ip_hash=f"bulk-hash-{base_vote_number}-{i}",
                quantity=i + 1,
            )
            created_votes.append(vote.id)

        # Verify all votes were created
        self.assertEqual(
            Vote.objects.filter(id__in=created_votes).count(),
            num_votes
        )

        # Attempt bulk update - should fail
        with self.assertRaises(Exception) as context:
            with transaction.atomic():
                Vote.objects.filter(id__in=created_votes).update(vote_quantity=999)

        self.assertIn("cannot be modified", str(context.exception).lower())

        # Verify votes still exist and are unchanged
        votes_after_update = Vote.objects.filter(id__in=created_votes)
        self.assertEqual(votes_after_update.count(), num_votes)

        # Verify quantities haven't changed
        for i, vote in enumerate(votes_after_update.order_by('vote_number')):
            self.assertEqual(vote.vote_quantity, i + 1)

        # Attempt bulk delete - should fail
        with self.assertRaises(Exception) as context:
            with transaction.atomic():
                Vote.objects.filter(id__in=created_votes).delete()

        self.assertIn("cannot be", str(context.exception).lower())

        # Verify all votes still exist
        self.assertEqual(
            Vote.objects.filter(id__in=created_votes).count(),
            num_votes
        )
