"""Check that important query indexes and uniqueness constraints exist in DB."""

from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from hypothesis import given, settings as hypothesis_settings, strategies as st
import pytest

from accounts.models import User
from payments.models import Payment
from polls.models import Contest
from voting.models import AuditLog, Vote, VoteAttempt


class DatabaseIndexTests(TestCase):
    def _index_columns(self, model):
        with connection.cursor() as cursor:
            constraints = connection.introspection.get_constraints(
                cursor, model._meta.db_table
            )
        return {
            tuple(item["columns"])
            for item in constraints.values()
            if item.get("index")
        }

    def test_composite_and_time_order_indexes_exist(self):
        self.assertIn(("poll_id", "voter_identity_id"), self._index_columns(Vote))
        self.assertIn(("created_at",), self._index_columns(Vote))
        self.assertIn(
            ("contest_id", "state", "created_at"),
            self._index_columns(VoteAttempt),
        )
        self.assertIn(("timestamp",), self._index_columns(AuditLog))

    def test_unique_model_constraints_exist(self):
        user_constraints = self._constraints(User)
        contest_constraints = self._constraints(Contest)
        payment_constraints = self._constraints(Payment)
        self.assertTrue(any(item.get("unique") and item["columns"] == ["email"] for item in user_constraints.values()))
        self.assertTrue(any(item.get("unique") and item["columns"] == ["slug"] for item in contest_constraints.values()))
        self.assertTrue(any(item.get("unique") and item["columns"] == ["provider_reference"] for item in payment_constraints.values()))

    def _constraints(self, model):
        with connection.cursor() as cursor:
            return connection.introspection.get_constraints(cursor, model._meta.db_table)


@pytest.mark.django_db
@hypothesis_settings(max_examples=8, deadline=None)
@given(suffix=st.uuids().map(str))
def test_duplicate_unique_values_are_rejected(suffix):
    """Generated duplicate values cannot bypass core database uniqueness."""
    user = User.objects.create_user(
        email=f"constraint-{suffix}@example.test",
        name="Constraint Property",
        password="test-password",
    )
    contest = Contest.objects.create(
        organizer=user,
        title=f"Constraint Contest {suffix}",
        slug=f"constraint-{suffix}",
    )
    payment = Payment.objects.create(
        user=user,
        provider_reference=f"provider-{suffix}",
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            User.objects.create_user(
                email=user.email,
                name="Duplicate User",
                password="test-password",
            )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Contest.objects.create(
                organizer=user,
                title="Duplicate Contest",
                slug=contest.slug,
            )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Payment.objects.create(
                user=user,
                provider_reference=payment.provider_reference,
            )
