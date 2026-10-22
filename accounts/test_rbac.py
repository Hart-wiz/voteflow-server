from types import SimpleNamespace

from django.test import RequestFactory, SimpleTestCase, TestCase
from hypothesis import given, settings as hypothesis_settings, strategies as st

from accounts.models import OrganizerProfile, User
from accounts.permissions import require_contest_ownership, require_role
from accounts.services import (
    approve_organizer_request,
    reject_organizer_request,
    request_organizer_privileges,
)
from config.errors import AuthenticationError, AuthorizationError
from polls.models import Contest
from voting.models import AuditLog


class RoleDecoratorTests(SimpleTestCase):
    @given(st.sampled_from(["USER", "ORGANIZER", "ADMIN"]))
    def test_role_decorator_grants_only_allowed_roles(self, role):
        protected = require_role("ORGANIZER", "ADMIN")(
            lambda request: "allowed"
        )
        request = SimpleNamespace(user=SimpleNamespace(is_authenticated=True, role=role, is_superuser=False))
        if role in ("ORGANIZER", "ADMIN"):
            self.assertEqual(protected(request), "allowed")
        else:
            with self.assertRaises(AuthorizationError):
                protected(request)


class DefaultRolePropertyTests(SimpleTestCase):
    @hypothesis_settings(max_examples=50)
    @given(
        email=st.emails(),
        name=st.text(min_size=1, max_size=50),
    )
    def test_new_users_default_to_user_role(self, email, name):
        user = User(email=email, name=name)
        self.assertEqual(user.role, User.Role.USER)

    def test_role_decorator_requires_authentication(self):
        protected = require_role("ADMIN")(lambda request: "allowed")
        request = SimpleNamespace(user=SimpleNamespace(is_authenticated=False, role="ADMIN"))
        with self.assertRaises(AuthenticationError):
            protected(request)


class OrganizerApprovalWorkflowTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="admin@example.com", name="Admin", password="StrongPassword123!"
        )
        self.applicant = User.objects.create_user(
            email="applicant@example.com", name="Applicant", password="StrongPassword123!"
        )

    def test_request_creates_pending_profile(self):
        profile, created = request_organizer_privileges(
            self.applicant, business_name="Vote Co", bio="Local organizer"
        )
        self.assertTrue(created)
        self.assertFalse(profile.is_approved)
        self.assertEqual(profile.business_name, "Vote Co")

    def test_approval_promotes_user_and_audits_role_change(self):
        profile, _ = request_organizer_privileges(self.applicant, business_name="Vote Co")
        approved, changed = approve_organizer_request(self.admin, profile.pk)
        self.applicant.refresh_from_db()
        self.assertTrue(changed)
        self.assertTrue(approved.is_approved)
        self.assertEqual(self.applicant.role, User.Role.ORGANIZER)
        self.assertTrue(AuditLog.objects.filter(action_type=AuditLog.ActionType.ROLE_CHANGE).exists())

    def test_rejection_keeps_user_role(self):
        profile, _ = request_organizer_privileges(self.applicant, business_name="Vote Co")
        self.assertTrue(reject_organizer_request(self.admin, profile.pk))
        self.applicant.refresh_from_db()
        self.assertEqual(self.applicant.role, User.Role.USER)
        self.assertFalse(OrganizerProfile.objects.filter(pk=profile.pk).exists())

    def test_only_admin_can_approve(self):
        profile, _ = request_organizer_privileges(self.applicant, business_name="Vote Co")
        with self.assertRaises(PermissionError):
            approve_organizer_request(self.applicant, profile.pk)


class ContestOwnershipTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="owner@example.com", name="Owner", password="StrongPassword123!", role=User.Role.ORGANIZER
        )
        self.other = User.objects.create_user(
            email="other@example.com", name="Other", password="StrongPassword123!", role=User.Role.ORGANIZER
        )
        self.contest = Contest.objects.create(
            organizer=self.owner, title="Contest", slug="decorator-contest"
        )
        self.factory = RequestFactory()
        self.view = require_contest_ownership(
            lambda request, slug: request.contest.pk
        )

    def test_owner_is_allowed(self):
        request = self.factory.get("/")
        request.user = self.owner
        self.assertEqual(self.view(request, slug=self.contest.slug), self.contest.pk)

    def test_other_organizer_is_denied(self):
        request = self.factory.get("/")
        request.user = self.other
        with self.assertRaises(AuthorizationError):
            self.view(request, slug=self.contest.slug)
