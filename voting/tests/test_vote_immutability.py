"""
Tests for Vote immutability enforcement via database triggers.

Tests task 3.3: Database triggers prevent UPDATE and DELETE operations on Vote records.
Validates Requirement 5.4: Vote immutability.
"""

import pytest
from django.db import IntegrityError, connection
from django.test import TestCase, TransactionTestCase

from accounts.models import User
from polls.models import Contest, Contestant, Poll
from voting.models import Vote, VoterIdentity


@pytest.mark.django_db
class TestVoteImmutabilityTriggers(TransactionTestCase):
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
            contest_id=self.poll.id,  # Using poll.id as contest reference
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
            cursor.execute("""
                SELECT EXISTS (
                    SELECT 1 
                    FROM pg_proc 
                    WHERE proname = 'prevent_vote_modification'
                );
            """)
            function_exists = cursor.fetchone()[0]

        self.assertTrue(
            function_exists, "prevent_vote_modification() function should exist"
        )

    def test_update_trigger_exists(self):
        """
        Test that the UPDATE trigger exists on voting_vote table.
        """
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT EXISTS (
                    SELECT 1 
                    FROM pg_trigger 
                    WHERE tgname = 'prevent_vote_update'
                );
            """)
            trigger_exists = cursor.fetchone()[0]

        self.assertTrue(trigger_exists, "prevent_vote_update trigger should exist")

    def test_delete_trigger_exists(self):
        """
        Test that the DELETE trigger exists on voting_vote table.
        """
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT EXISTS (
                    SELECT 1 
                    FROM pg_trigger 
                    WHERE tgname = 'prevent_vote_delete'
                );
            """)
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


class TestVoteImmutabilityEdgeCases(TransactionTestCase):
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

        self.contestant = Contestant.objects.create(
            poll=self.poll, name="Test Contestant 2", votes=0
        )

        self.voter_identity = VoterIdentity.objects.create(
            user=self.user,
            contest_id=self.poll.id,
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


# Property-based test placeholder for future implementation
# TODO: Implement property test using hypothesis
# @given(vote_record=...)
# def test_vote_immutability_property(vote_record):
#     """
#     Property: For any Vote record, any attempt to UPDATE or DELETE SHALL fail.
#     Validates: Requirements 5.4
#     """
#     pass
