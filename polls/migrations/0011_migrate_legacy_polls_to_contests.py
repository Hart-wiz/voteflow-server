"""Link legacy Poll rows to UUID-preserving Contest rows and policies."""

from django.db import migrations
from django.db.models import F


ROLE_TRACKING_TABLE = "polls_legacy_role_promotions"


def copy_polls_to_contests(apps, schema_editor):
    Poll = apps.get_model("polls", "Poll")
    Contest = apps.get_model("polls", "Contest")
    VotingPolicy = apps.get_model("voting", "VotingPolicy")
    User = apps.get_model("accounts", "User")
    Vote = apps.get_model("voting", "Vote")
    connection = schema_editor.connection

    # Record only roles changed here so a rollback does not demote existing or
    # subsequently promoted organizers.
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT user_id FROM {ROLE_TRACKING_TABLE}")
        promoted = {row[0] for row in cursor.fetchall()}

    for poll in Poll.objects.order_by("created_at", "id").iterator():
        contest = Contest.objects.filter(pk=poll.pk).first()
        if contest is None:
            raise RuntimeError(
                f"Poll {poll.pk} has no UUID-preserving Contest. "
                "The legacy contest copy in voting.0006 must run first."
            )
        if contest.source_poll_id not in (None, poll.pk):
            raise RuntimeError(f"Contest {contest.pk} is linked to a different Poll.")
        if contest.source_poll_id is None:
            contest.source_poll_id = poll.pk
            contest.save(update_fields=["source_poll"])

        VotingPolicy.objects.get_or_create(
            contest_id=contest.pk,
            defaults={
                "price_per_vote": poll.price_per_vote if poll.is_paid else 0,
                "vote_limit_type": "UNLIMITED",
                "verification_method": "NONE",
                "revenue_share_percentage": 80,
                "allow_anonymous": False,
            },
        )

        user = User.objects.filter(pk=poll.creator_id).only("id", "role").first()
        if user and user.role == "USER" and str(user.pk) not in promoted:
            user.role = "ORGANIZER"
            user.save(update_fields=["role"])
            with connection.cursor() as cursor:
                cursor.execute(
                    f"INSERT INTO {ROLE_TRACKING_TABLE} (user_id) VALUES (%s)",
                    [str(user.pk)],
                )
            promoted.add(str(user.pk))

        # voting.0006 assigns voter identities, sequential vote numbers,
        # quantities, and privacy-safe device/IP fields before the immutable
        # vote triggers are installed. Fail clearly if that preparation missed
        # any historical voter record.
        if Vote.objects.filter(
            poll_id=poll.pk,
            voter_id__isnull=False,
            voter_identity__isnull=True,
        ).exists():
            raise RuntimeError(f"Poll {poll.pk} contains votes without voter identities.")


def _disable_vote_update_trigger(connection):
    with connection.cursor() as cursor:
        if connection.vendor == "postgresql":
            cursor.execute("ALTER TABLE voting_vote DISABLE TRIGGER prevent_vote_update")
        elif connection.vendor == "sqlite":
            cursor.execute("DROP TRIGGER IF EXISTS prevent_vote_update")


def _enable_vote_update_trigger(connection):
    with connection.cursor() as cursor:
        if connection.vendor == "postgresql":
            cursor.execute("ALTER TABLE voting_vote ENABLE TRIGGER prevent_vote_update")
        elif connection.vendor == "sqlite":
            cursor.execute(
                "CREATE TRIGGER prevent_vote_update BEFORE UPDATE ON voting_vote "
                "BEGIN SELECT RAISE(ABORT, 'Votes cannot be modified or deleted'); END"
            )


def unlink_migrated_polls(apps, schema_editor):
    Contest = apps.get_model("polls", "Contest")
    Vote = apps.get_model("voting", "Vote")
    Payment = apps.get_model("payments", "Payment")
    VoteAttempt = apps.get_model("voting", "VoteAttempt")
    User = apps.get_model("accounts", "User")
    connection = schema_editor.connection

    copied_ids = list(
        Contest.objects.filter(source_poll_id=F("pk"))
        .values_list("pk", flat=True)
        .iterator()
    )
    if not copied_ids:
        return
    _disable_vote_update_trigger(connection)
    try:
        tables = (
            ("voting", "VoteAttempt", "contest_id"),
            ("voting", "VotingPolicy", "contest_id"),
            ("polls", "Livestream", "contest_id"),
        )
        for offset in range(0, len(copied_ids), 500):
            id_batch = copied_ids[offset : offset + 500]
            prepared_ids = [
                str(value).replace("-", "") if connection.vendor == "sqlite" else str(value)
                for value in id_batch
            ]
            Vote.objects.filter(poll_id__in=id_batch).update(voter_identity_id=None)
            placeholders = ", ".join(["%s"] * len(id_batch))
            attempt_ids = VoteAttempt.objects.filter(contest_id__in=id_batch).values_list(
                "pk", flat=True
            )
            payment_ids = Payment.objects.filter(vote_attempt_id__in=attempt_ids).values_list(
                "pk", flat=True
            )
            Vote.objects.filter(payment_id__in=payment_ids).update(payment_id=None)
            with connection.cursor() as cursor:
                payment_table = schema_editor.quote_name(Payment._meta.db_table)
                payment_fk = schema_editor.quote_name(Payment._meta.get_field("vote_attempt").column)
                attempt_table = schema_editor.quote_name(VoteAttempt._meta.db_table)
                attempt_pk = schema_editor.quote_name(VoteAttempt._meta.pk.column)
                attempt_contest_fk = schema_editor.quote_name(VoteAttempt._meta.get_field("contest").column)
                cursor.execute(
                    f"DELETE FROM {payment_table} WHERE {payment_fk} IN "
                    f"(SELECT {attempt_pk} FROM {attempt_table} WHERE {attempt_contest_fk} IN ({placeholders}))",
                    prepared_ids,
                )
                for app_label, model_name, field_name in tables:
                    model = apps.get_model(app_label, model_name)
                    table = schema_editor.quote_name(model._meta.db_table)
                    column = schema_editor.quote_name(model._meta.get_field(field_name).column)
                    cursor.execute(
                        f"DELETE FROM {table} WHERE {column} IN ({placeholders})",
                        prepared_ids,
                    )
                identity = apps.get_model("voting", "VoterIdentity")
                identity_table = schema_editor.quote_name(identity._meta.db_table)
                identity_pk = schema_editor.quote_name(identity._meta.pk.column)
                identity_contest_fk = schema_editor.quote_name(identity._meta.get_field("contest").column)
                verification = apps.get_model("voting", "VoterVerification")
                verification_table = schema_editor.quote_name(verification._meta.db_table)
                verification_identity_fk = schema_editor.quote_name(
                    verification._meta.get_field("voter_identity").column
                )
                cursor.execute(
                    f"DELETE FROM {verification_table} WHERE {verification_identity_fk} IN "
                    f"(SELECT {identity_pk} FROM {identity_table} WHERE {identity_contest_fk} IN ({placeholders}))",
                    prepared_ids,
                )
                cursor.execute(
                    f"DELETE FROM {identity_table} WHERE {identity_contest_fk} IN ({placeholders})",
                    prepared_ids,
                )
        with connection.cursor() as cursor:
            contest_table = schema_editor.quote_name(Contest._meta.db_table)
            pk_column = schema_editor.quote_name(Contest._meta.pk.column)
            source_column = schema_editor.quote_name(Contest._meta.get_field("source_poll").column)
            cursor.execute(
                f"DELETE FROM {contest_table} WHERE {pk_column} = {source_column}"
            )
    finally:
        _enable_vote_update_trigger(connection)

    with connection.cursor() as cursor:
        cursor.execute(f"SELECT user_id FROM {ROLE_TRACKING_TABLE}")
        promoted_ids = [row[0] for row in cursor.fetchall()]
    for user in User.objects.filter(pk__in=promoted_ids, role="ORGANIZER").iterator():
        if not Contest.objects.filter(organizer_id=user.pk).exists():
            user.role = "USER"
            user.save(update_fields=["role"])


class Migration(migrations.Migration):
    dependencies = [
        ("polls", "0010_contest_source_poll"),
        ("payments", "0005_remove_payment_payments_pa_provide_48cfd7_idx_and_more"),
        ("voting", "0011_add_vote_immutability_triggers"),
    ]

    operations = [
        migrations.RunSQL(
            sql=f"CREATE TABLE {ROLE_TRACKING_TABLE} (user_id varchar(64) PRIMARY KEY)",
            reverse_sql=f"DROP TABLE {ROLE_TRACKING_TABLE}",
        ),
        migrations.RunPython(copy_polls_to_contests, unlink_migrated_polls),
    ]
