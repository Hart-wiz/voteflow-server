"""
Tests for accounts app models.

Requirements validated:
- 1.1: User role field validation
- 1.2: Default role assignment on registration
- 1.4: OrganizerProfile creation with is_approved=false
- 1.5: OrganizerProfile approval workflow
"""

from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.utils import timezone

from accounts.models import OrganizerProfile, User


class UserRBACFieldsTest(TestCase):
    """Test suite for User RBAC fields."""

    def test_default_role_assignment_on_registration(self):
        """
        Test that when a User completes registration, the role field is set to USER.
        **Validates: Requirements 1.1, 1.2**
        """
        user = User.objects.create_user(
            email="newuser@example.com",
            name="New User",
            password="testpass123",
        )

        # Verify the role defaults to USER
        self.assertEqual(user.role, User.Role.USER)

    def test_role_field_accepts_only_valid_values(self):
        """
        Test that the role field accepts only valid role values (USER, ORGANIZER, ADMIN).
        **Validates: Requirements 1.1**
        """
        # Test USER role
        user_with_user_role = User.objects.create_user(
            email="user@example.com",
            name="Regular User",
            password="testpass123",
            role=User.Role.USER,
        )
        self.assertEqual(user_with_user_role.role, User.Role.USER)

        # Test ORGANIZER role
        user_with_organizer_role = User.objects.create_user(
            email="organizer@example.com",
            name="Organizer User",
            password="testpass123",
            role=User.Role.ORGANIZER,
        )
        self.assertEqual(user_with_organizer_role.role, User.Role.ORGANIZER)

        # Test ADMIN role
        user_with_admin_role = User.objects.create_user(
            email="admin@example.com",
            name="Admin User",
            password="testpass123",
            role=User.Role.ADMIN,
        )
        self.assertEqual(user_with_admin_role.role, User.Role.ADMIN)

    def test_role_field_rejects_invalid_values(self):
        """
        Test that attempting to set an invalid role value raises an error.
        **Validates: Requirements 1.1**
        """
        user = User.objects.create_user(
            email="test@example.com",
            name="Test User",
            password="testpass123",
        )

        # Attempting to set an invalid role should fail validation
        user.role = "INVALID_ROLE"

        # This should raise a validation error when we try to save
        # Django's model validation happens at the form/serializer level,
        # but we can test the choices constraint
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            user.full_clean()  # This triggers model validation

    def test_role_field_database_indexing(self):
        """
        Test that the role field has a database index for query performance.
        **Validates: Requirements 1.1, 1.2**
        """
        # Create several users with different roles
        User.objects.create_user(
            email="user1@example.com",
            name="User 1",
            password="testpass123",
            role=User.Role.USER,
        )
        User.objects.create_user(
            email="organizer1@example.com",
            name="Organizer 1",
            password="testpass123",
            role=User.Role.ORGANIZER,
        )
        User.objects.create_user(
            email="admin1@example.com",
            name="Admin 1",
            password="testpass123",
            role=User.Role.ADMIN,
        )

        # Verify we can query efficiently by role
        organizers = User.objects.filter(role=User.Role.ORGANIZER)
        self.assertEqual(organizers.count(), 1)
        organizer = organizers.first()
        self.assertIsNotNone(organizer)
        assert organizer is not None
        self.assertEqual(organizer.email, "organizer1@example.com")

        # Check that the index exists in the database
        # Get the table name from the model's Meta
        table_name = User._meta.db_table

        # Query the database for indexes on the role field
        with connection.cursor() as cursor:
            # PostgreSQL-specific query to check for indexes
            cursor.execute(
                """
                SELECT indexname 
                FROM pg_indexes 
                WHERE tablename = %s 
                AND indexdef LIKE '%%role%%'
                """,
                [table_name],
            )
            indexes = cursor.fetchall()

            # Verify at least one index exists on the role field
            self.assertGreater(len(indexes), 0, "No index found on role field")

    def test_email_field_database_indexing(self):
        """
        Test that the email field has a database index.
        **Validates: Requirements 1.1**
        """
        User.objects.create_user(
            email="indexed@example.com",
            name="Indexed User",
            password="testpass123",
        )

        # Check that the index exists in the database
        table_name = User._meta.db_table

        with connection.cursor() as cursor:
            # PostgreSQL-specific query to check for indexes
            cursor.execute(
                """
                SELECT indexname 
                FROM pg_indexes 
                WHERE tablename = %s 
                AND indexdef LIKE '%%email%%'
                """,
                [table_name],
            )
            indexes = cursor.fetchall()

            # Verify at least one index exists on the email field
            self.assertGreater(len(indexes), 0, "No index found on email field")

    def test_is_email_verified_field_exists(self):
        """
        Test that the is_email_verified field exists and defaults to False.
        **Validates: Requirements 1.1**
        """
        user = User.objects.create_user(
            email="verified@example.com",
            name="Verified User",
            password="testpass123",
        )

        # Verify the field exists and defaults to False
        self.assertFalse(user.is_email_verified)

        # Test that we can update it to True
        user.is_email_verified = True
        user.save()
        user.refresh_from_db()
        self.assertTrue(user.is_email_verified)

    def test_multiple_users_with_same_role(self):
        """
        Test that multiple users can have the same role.
        **Validates: Requirements 1.1, 1.2**
        """
        # Create multiple users with USER role
        user1 = User.objects.create_user(
            email="user1@example.com",
            name="User One",
            password="testpass123",
        )
        user2 = User.objects.create_user(
            email="user2@example.com",
            name="User Two",
            password="testpass123",
        )

        # Both should have USER role
        self.assertEqual(user1.role, User.Role.USER)
        self.assertEqual(user2.role, User.Role.USER)

        # Verify we can query all users with a specific role
        users_with_user_role = User.objects.filter(role=User.Role.USER)
        self.assertGreaterEqual(users_with_user_role.count(), 2)


class OrganizerProfileModelTest(TestCase):
    """Test suite for OrganizerProfile model."""

    @classmethod
    def setUpTestData(cls):
        """Create test users for use in test cases."""
        cls.user = User.objects.create_user(
            email="organizer@example.com",
            name="Test Organizer",
            password="testpass123",
        )
        cls.admin_user = User.objects.create_user(
            email="admin@example.com",
            name="Admin User",
            password="adminpass123",
            role=User.Role.ADMIN,
            is_staff=True,
        )

    def test_organizer_profile_one_to_one_relationship(self):
        """
        Test that OrganizerProfile has a OneToOne relationship with User.
        **Validates: Requirements 1.4**
        """
        # Create organizer profile

        organizer_profile = OrganizerProfile.objects.create(
            user=self.user,
            bio="Test bio",
            business_name="Test Business",
        )

        # Verify the profile is accessible from user
        self.assertEqual(self.user.organizer_profile, organizer_profile)
        self.assertEqual(organizer_profile.user, self.user)

        # Verify only one profile can exist per user
        with self.assertRaises(IntegrityError), transaction.atomic():
            OrganizerProfile.objects.create(
                user=self.user,
                bio="Duplicate profile",
            )

    def test_organizer_profile_default_is_approved_false(self):
        """
        Test that is_approved defaults to False on creation.
        **Validates: Requirements 1.4**
        """
        organizer_profile = OrganizerProfile.objects.create(
            user=self.user,
            bio="Test bio",
        )

        # Verify is_approved is False by default
        self.assertFalse(organizer_profile.is_approved)
        self.assertIsNone(organizer_profile.approved_at)
        self.assertIsNone(organizer_profile.approved_by)

    def test_organizer_profile_approval_workflow_field_updates(self):
        """
        Test that approval workflow fields are updated correctly.
        **Validates: Requirements 1.5**
        """
        organizer_profile = OrganizerProfile.objects.create(
            user=self.user,
            bio="Test bio",
            business_name="Test Business",
        )

        # Verify initial state
        self.assertFalse(organizer_profile.is_approved)
        self.assertIsNone(organizer_profile.approved_at)
        self.assertIsNone(organizer_profile.approved_by)

        # Simulate approval
        approval_time = timezone.now()
        organizer_profile.is_approved = True
        organizer_profile.approved_at = approval_time
        organizer_profile.approved_by = self.admin_user
        organizer_profile.save()

        # Refresh from database
        organizer_profile.refresh_from_db()

        # Verify approval fields are set
        self.assertTrue(organizer_profile.is_approved)
        self.assertEqual(organizer_profile.approved_by, self.admin_user)
        self.assertIsNotNone(organizer_profile.approved_at)

    def test_organizer_profile_created_fields(self):
        """
        Test that timestamps are automatically set.
        **Validates: Requirements 1.4**
        """
        organizer_profile = OrganizerProfile.objects.create(
            user=self.user,
            bio="Test bio",
        )

        self.assertIsNotNone(organizer_profile.requested_at)
        self.assertIsNotNone(organizer_profile.created_at)
        self.assertIsNotNone(organizer_profile.updated_at)

    def test_organizer_profile_business_fields(self):
        """
        Test that business information fields are stored correctly.
        **Validates: Requirements 1.4**
        """
        organizer_profile = OrganizerProfile.objects.create(
            user=self.user,
            bio="Professional event organizer",
            business_name="Event Corp Ltd",
            business_registration_number="REG123456",
        )

        self.assertEqual(organizer_profile.bio, "Professional event organizer")
        self.assertEqual(organizer_profile.business_name, "Event Corp Ltd")
        self.assertEqual(organizer_profile.business_registration_number, "REG123456")

    def test_organizer_profile_is_verified_defaults_false(self):
        """
        Test that is_verified defaults to False.
        **Validates: Requirements 1.4**
        """
        organizer_profile = OrganizerProfile.objects.create(
            user=self.user,
        )

        self.assertFalse(organizer_profile.is_verified)

    def test_organizer_profile_cascade_delete(self):
        """
        Test that deleting a user cascades to delete the organizer profile.
        **Validates: Requirements 1.4**
        """
        organizer_profile = OrganizerProfile.objects.create(
            user=self.user,
            bio="Test bio",
        )
        profile_id = organizer_profile.id

        # Delete the user
        self.user.delete()

        # Verify profile is also deleted
        self.assertFalse(OrganizerProfile.objects.filter(id=profile_id).exists())

    def test_organizer_profile_approved_by_set_null_on_admin_delete(self):
        """
        Test that approved_by is set to NULL when admin user is deleted.
        **Validates: Requirements 1.5**
        """
        organizer_profile = OrganizerProfile.objects.create(
            user=self.user,
            bio="Test bio",
            is_approved=True,
            approved_by=self.admin_user,
            approved_at=timezone.now(),
        )

        # Delete admin user
        self.admin_user.delete()

        # Refresh from database
        organizer_profile.refresh_from_db()

        # Verify approved_by is set to None but profile still exists
        self.assertIsNone(organizer_profile.approved_by)
        self.assertTrue(organizer_profile.is_approved)

    def test_organizer_profile_str_representation(self):
        """
        Test the string representation of OrganizerProfile.
        **Validates: Requirements 1.4**
        """
        organizer_profile = OrganizerProfile.objects.create(
            user=self.user,
            bio="Test bio",
        )

        expected_str = f"OrganizerProfile for {self.user.email}"
        self.assertEqual(str(organizer_profile), expected_str)
