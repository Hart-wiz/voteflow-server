"""Install immutable-vote triggers after the final Vote table alteration."""

from django.db import migrations


def install_vote_triggers(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor == "postgresql":
        statements = [
            """
            CREATE OR REPLACE FUNCTION prevent_vote_modification()
            RETURNS TRIGGER AS $$
            BEGIN
                RAISE EXCEPTION 'Votes cannot be modified or deleted';
            END;
            $$ LANGUAGE plpgsql
            """,
            "CREATE TRIGGER prevent_vote_update BEFORE UPDATE ON voting_vote FOR EACH ROW EXECUTE FUNCTION prevent_vote_modification()",
            "CREATE TRIGGER prevent_vote_delete BEFORE DELETE ON voting_vote FOR EACH ROW EXECUTE FUNCTION prevent_vote_modification()",
        ]
    elif vendor == "sqlite":
        statements = [
            "CREATE TRIGGER prevent_vote_update BEFORE UPDATE ON voting_vote BEGIN SELECT RAISE(ABORT, 'Votes cannot be modified or deleted'); END",
            "CREATE TRIGGER prevent_vote_delete BEFORE DELETE ON voting_vote BEGIN SELECT RAISE(ABORT, 'Votes cannot be modified or deleted'); END",
        ]
    else:
        return

    with schema_editor.connection.cursor() as cursor:
        for statement in statements:
            cursor.execute(statement)


def remove_vote_triggers(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    with schema_editor.connection.cursor() as cursor:
        if vendor == "postgresql":
            cursor.execute("DROP TRIGGER IF EXISTS prevent_vote_update ON voting_vote")
            cursor.execute("DROP TRIGGER IF EXISTS prevent_vote_delete ON voting_vote")
            cursor.execute("DROP FUNCTION IF EXISTS prevent_vote_modification()")
        elif vendor == "sqlite":
            cursor.execute("DROP TRIGGER IF EXISTS prevent_vote_update")
            cursor.execute("DROP TRIGGER IF EXISTS prevent_vote_delete")


class Migration(migrations.Migration):
    dependencies = [("voting", "0010_remove_vote_voting_vote_voter_i_a33aec_idx_and_more")]

    operations = [
        migrations.RunPython(install_vote_triggers, remove_vote_triggers),
    ]
