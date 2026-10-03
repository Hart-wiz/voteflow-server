# Generated migration for task 3.3: Create database triggers for Vote immutability

from django.db import migrations


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
        migrations.RunSQL(
            sql="""
            -- Create function that prevents vote modification
            CREATE OR REPLACE FUNCTION prevent_vote_modification()
            RETURNS TRIGGER AS $$
            BEGIN
                RAISE EXCEPTION 'Votes cannot be modified or deleted';
                RETURN NULL;
            END;
            $$ LANGUAGE plpgsql;
            
            -- Create trigger to prevent UPDATE operations
            CREATE TRIGGER prevent_vote_update
                BEFORE UPDATE ON voting_vote
                FOR EACH ROW
                EXECUTE FUNCTION prevent_vote_modification();
            
            -- Create trigger to prevent DELETE operations
            CREATE TRIGGER prevent_vote_delete
                BEFORE DELETE ON voting_vote
                FOR EACH ROW
                EXECUTE FUNCTION prevent_vote_modification();
            """,
            reverse_sql="""
            -- Drop triggers
            DROP TRIGGER IF EXISTS prevent_vote_update ON voting_vote;
            DROP TRIGGER IF EXISTS prevent_vote_delete ON voting_vote;
            
            -- Drop function
            DROP FUNCTION IF EXISTS prevent_vote_modification();
            """
        ),
    ]
