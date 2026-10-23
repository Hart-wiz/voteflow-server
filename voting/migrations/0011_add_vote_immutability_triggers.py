"""Install immutable-vote triggers after the final Vote table alteration."""

from django.db import migrations


def install_vote_triggers(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor == "postgresql":
        create_function = """
            CREATE OR REPLACE FUNCTION prevent_vote_modification()
            RETURNS TRIGGER AS $$
            BEGIN
                RAISE EXCEPTION 'Votes cannot be modified or deleted';
            END;
            $$ LANGUAGE plpgsql
        """
        trigger_statements = {
            "prevent_vote_update": "CREATE TRIGGER prevent_vote_update BEFORE UPDATE ON voting_vote FOR EACH ROW EXECUTE FUNCTION prevent_vote_modification()",
            "prevent_vote_delete": "CREATE TRIGGER prevent_vote_delete BEFORE DELETE ON voting_vote FOR EACH ROW EXECUTE FUNCTION prevent_vote_modification()",
        }
    elif vendor == "sqlite":
        create_function = None
        trigger_statements = {
            "prevent_vote_update": "CREATE TRIGGER prevent_vote_update BEFORE UPDATE ON voting_vote BEGIN SELECT RAISE(ABORT, 'Votes cannot be modified or deleted'); END",
            "prevent_vote_delete": "CREATE TRIGGER prevent_vote_delete BEFORE DELETE ON voting_vote BEGIN SELECT RAISE(ABORT, 'Votes cannot be modified or deleted'); END",
        }
    else:
        return

    with schema_editor.connection.cursor() as cursor:
        if vendor == "postgresql":
            cursor.execute(create_function)
            cursor.execute(
                "SELECT tgname FROM pg_trigger "
                "WHERE tgrelid = 'voting_vote'::regclass AND NOT tgisinternal"
            )
        else:
            cursor.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'trigger' AND tbl_name = 'voting_vote'"
            )
        existing_triggers = {row[0] for row in cursor.fetchall()}
        for name, statement in trigger_statements.items():
            if name not in existing_triggers:
                cursor.execute(statement)


def remove_vote_triggers(apps, schema_editor):
    # voting.0007 owns these triggers. This follow-up migration only repairs
    # missing triggers after the Vote table changes, so reversing it must not
    # remove triggers that are still owned by the earlier migration.
    return None


class Migration(migrations.Migration):
    dependencies = [("voting", "0010_remove_vote_voting_vote_voter_i_a33aec_idx_and_more")]

    operations = [
        migrations.RunPython(install_vote_triggers, remove_vote_triggers),
    ]
