"""Exercise the legacy Poll/Vote upgrade and reverse on an isolated test DB."""

import hashlib
import uuid

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class LegacyPollMigrationTests(TransactionTestCase):
    reset_sequences = True
    migrate_from = [
        ("accounts", "0002_organizerprofile_userotp_and_more"),
        ("polls", "0006_remove_contest_valid_time_range_and_more"),
        ("payments", "0002_alter_transaction_options"),
        ("voting", "0005_add_vote_attempt_model"),
    ]
    migrate_to = [
        ("accounts", "0002_organizerprofile_userotp_and_more"),
        ("polls", "0011_migrate_legacy_polls_to_contests"),
        ("payments", "0005_remove_payment_payments_pa_provide_48cfd7_idx_and_more"),
        ("voting", "0011_add_vote_immutability_triggers"),
    ]

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps

        User = old_apps.get_model("accounts", "User")
        Poll = old_apps.get_model("polls", "Poll")
        Contestant = old_apps.get_model("polls", "Contestant")
        Vote = old_apps.get_model("voting", "Vote")

        suffix = uuid.uuid4().hex
        self.user_id = uuid.uuid4()
        self.user = User.objects.create(
            id=self.user_id,
            email=f"legacy-{suffix}@example.com",
            name="Legacy Organizer",
            password="!",
            role="USER",
            is_email_verified=False,
        )
        self.poll_id = uuid.uuid4()
        self.poll = Poll.objects.create(
            id=self.poll_id,
            creator_id=self.user_id,
            title="Legacy Music Poll",
            slug=f"legacy-music-{suffix}",
            status="active",
            is_paid=True,
            price_per_vote="2.50",
        )
        self.contestant = Contestant.objects.create(
            poll_id=self.poll_id,
            name="Legacy Candidate",
            votes=3,
        )
        self.vote_id = uuid.uuid4()
        Vote.objects.create(
            id=self.vote_id,
            poll_id=self.poll_id,
            contestant_id=self.contestant.pk,
            voter_id=self.user_id,
            quantity=3,
            voter_email=self.user.email,
            ip_address="203.0.113.8",
            device_fingerprint="",
        )

        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        self.apps = executor.loader.project_state(self.migrate_to).apps

    def tearDown(self):
        try:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
        finally:
            super().tearDown()

    def _fixture_teardown(self):
        # TransactionTestCase flush deletes rows directly, so temporarily
        # remove the immutable-vote triggers while Django clears test data.
        with connection.cursor() as cursor:
            if connection.vendor == "postgresql":
                cursor.execute("DROP TRIGGER IF EXISTS prevent_vote_update ON voting_vote")
                cursor.execute("DROP TRIGGER IF EXISTS prevent_vote_delete ON voting_vote")
                cursor.execute("DROP FUNCTION IF EXISTS prevent_vote_modification()")
            elif connection.vendor == "sqlite":
                cursor.execute("DROP TRIGGER IF EXISTS prevent_vote_update")
                cursor.execute("DROP TRIGGER IF EXISTS prevent_vote_delete")

        try:
            super()._fixture_teardown()
        finally:
            with connection.cursor() as cursor:
                if connection.vendor == "postgresql":
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
                    cursor.execute(
                        "CREATE TRIGGER prevent_vote_update BEFORE UPDATE ON voting_vote "
                        "FOR EACH ROW EXECUTE FUNCTION prevent_vote_modification()"
                    )
                    cursor.execute(
                        "CREATE TRIGGER prevent_vote_delete BEFORE DELETE ON voting_vote "
                        "FOR EACH ROW EXECUTE FUNCTION prevent_vote_modification()"
                    )
                elif connection.vendor == "sqlite":
                    cursor.execute(
                        "CREATE TRIGGER prevent_vote_update BEFORE UPDATE ON voting_vote "
                        "BEGIN SELECT RAISE(ABORT, 'Votes cannot be modified or deleted'); END"
                    )
                    cursor.execute(
                        "CREATE TRIGGER prevent_vote_delete BEFORE DELETE ON voting_vote "
                        "BEGIN SELECT RAISE(ABORT, 'Votes cannot be modified or deleted'); END"
                    )

    def test_poll_vote_and_user_data_migrate_and_reverse(self):
        User = self.apps.get_model("accounts", "User")
        Poll = self.apps.get_model("polls", "Poll")
        Contest = self.apps.get_model("polls", "Contest")
        Contestant = self.apps.get_model("polls", "Contestant")
        VotingPolicy = self.apps.get_model("voting", "VotingPolicy")
        VoterIdentity = self.apps.get_model("voting", "VoterIdentity")
        Vote = self.apps.get_model("voting", "Vote")

        poll = Poll.objects.get(pk=self.poll_id)
        contest = Contest.objects.get(pk=self.poll_id)
        voter_identity = VoterIdentity.objects.get(user_id=self.user_id, contest_id=contest.pk)
        vote = Vote.objects.get(pk=self.vote_id)
        policy = VotingPolicy.objects.get(contest_id=contest.pk)
        user = User.objects.get(pk=self.user_id)

        self.assertEqual(contest.source_poll_id, poll.pk)
        self.assertEqual(contest.organizer_id, self.user_id)
        self.assertEqual(contest.state, "LIVE")
        self.assertEqual(policy.price_per_vote, 2.5)
        self.assertEqual(user.role, "ORGANIZER")
        self.assertEqual(voter_identity.verification_status, "VERIFIED")
        self.assertEqual(vote.voter_identity_id, voter_identity.pk)
        self.assertEqual(vote.vote_number, 1)
        self.assertEqual(vote.vote_quantity, 3)
        self.assertEqual(vote.device_identifier, "legacy")
        self.assertEqual(vote.ip_hash, hashlib.sha256(b"203.0.113.8").hexdigest())
        self.assertEqual(Contestant.objects.get(pk=self.contestant.pk).votes, 3)

        from scripts.verify_migration import CHECKS

        for _, check in CHECKS:
            check()

        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        OldPoll = old_apps.get_model("polls", "Poll")
        OldVote = old_apps.get_model("voting", "Vote")
        OldUser = old_apps.get_model("accounts", "User")

        self.assertTrue(OldPoll.objects.filter(pk=self.poll_id).exists())
        self.assertEqual(OldVote.objects.get(pk=self.vote_id).quantity, 3)
        self.assertEqual(OldUser.objects.get(pk=self.user_id).role, "USER")
        self.assertFalse(
            executor.loader.project_state(self.migrate_from)
            .apps.get_model("polls", "Contest")
            .objects.filter(pk=self.poll_id)
            .exists()
        )
