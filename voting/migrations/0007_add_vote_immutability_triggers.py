# Generated migration for task 3.3: Create database triggers for Vote immutability

from django.db import migrations


def install_vote_triggers(apps, schema_editor):
    """Install equivalent immutable-vote triggers on PostgreSQL and SQLite."""
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
        cursor.execute("DROP TRIGGER IF EXISTS prevent_vote_update ON voting_vote" if vendor == "postgresql" else "DROP TRIGGER IF EXISTS prevent_vote_update")
        cursor.execute("DROP TRIGGER IF EXISTS prevent_vote_delete ON voting_vote" if vendor == "postgresql" else "DROP TRIGGER IF EXISTS prevent_vote_delete")
        if vendor == "postgresql":
            cursor.execute("DROP FUNCTION IF EXISTS prevent_vote_modification()")


class Migration(migrations.Migration):
    """
    Add database-level immutability constraints for Vote records.
    
    Creates PostgreSQL triggers that prevent any UPDATE or DELETE operations
    on the voting_vote table after a vote is created, ensuring vote records
    remain immutable and maintaining data integrity for audit purposes.
    
    Requirements: 5.4 - Vote immutability
    """

    dependencies = [
        ('voting', '0006_refactor_vote_model'),
    ]

    operations = [
        migrations.RunPython(install_vote_triggers, remove_vote_triggers),
    ]
