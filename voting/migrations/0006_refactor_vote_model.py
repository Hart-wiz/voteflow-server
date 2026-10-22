# Generated migration for task 3.2: Refactor Vote model for enhanced tracking

import hashlib
import uuid
from decimal import Decimal

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.utils.text import slugify


def migrate_existing_votes(apps, schema_editor):
    """
    Data migration to preserve existing Vote records.
    
    - Creates VoterIdentity for each voter/poll combination
    - Migrates vote fields to new structure
    - Sets vote_number sequentially per poll
    - Hashes IP addresses for security
    """
    Vote = apps.get_model('voting', 'Vote')
    VoterIdentity = apps.get_model('voting', 'VoterIdentity')
    Poll = apps.get_model('polls', 'Poll')
    Contest = apps.get_model('polls', 'Contest')

    # Preserve the legacy UUIDs so the voter identities below can safely use
    # contest_id=poll_id while both models coexist during the transition.
    state_map = {
        'active': 'LIVE',
        'ending_soon': 'LIVE',
        'closed': 'CLOSED',
        'draft': 'DRAFT',
        'new': 'DRAFT',
    }
    for poll in Poll.objects.order_by('created_at', 'id').iterator():
        existing = Contest.objects.filter(pk=poll.pk).first()
        if existing:
            if existing.organizer_id != poll.creator_id or existing.title != poll.title:
                raise RuntimeError(
                    f'Cannot migrate poll {poll.pk}: a different contest already uses its UUID.'
                )
            continue

        base_slug = (poll.slug or slugify(poll.title) or f'contest-{poll.pk}')[:280]
        slug = base_slug
        suffix = 1
        while Contest.objects.filter(slug=slug).exists():
            suffix_text = f'-{suffix}'
            slug = f'{base_slug[:300 - len(suffix_text)]}{suffix_text}'
            suffix += 1
        Contest.objects.create(
            id=poll.pk,
            organizer_id=poll.creator_id,
            title=poll.title,
            slug=slug,
            description=poll.description,
            category=poll.category,
            image=poll.image,
            tags=poll.tags,
            state=state_map.get(poll.status, 'DRAFT'),
            timezone='UTC',
            start_time=None,
            end_time=poll.ends_at,
            results_visibility='after_close',
            version=0,
        )
    
    # Process votes in batches to handle large datasets
    votes = Vote.objects.select_related('poll', 'voter').order_by('poll_id', 'created_at')
    
    vote_number_tracker = {}  # Track vote numbers per poll
    voter_identity_cache = {}  # Cache created VoterIdentity records
    
    for vote in votes:
        poll_id = vote.poll_id
        
        # Initialize vote number for this poll if not exists
        if poll_id not in vote_number_tracker:
            vote_number_tracker[poll_id] = 0
        
        # Increment vote number
        vote_number_tracker[poll_id] += 1
        vote.vote_number = vote_number_tracker[poll_id]
        
        # Create or get VoterIdentity if voter exists
        if vote.voter_id:
            cache_key = (vote.voter_id, poll_id)
            
            if cache_key not in voter_identity_cache:
                # Create VoterIdentity for this user/poll combination
                voter_identity, created = VoterIdentity.objects.get_or_create(
                    user_id=vote.voter_id,
                    contest_id=poll_id,  # Note: poll_id links to Poll for now
                    defaults={
                        'verification_status': 'VERIFIED',  # Assume existing votes are verified
                        'verified_at': vote.created_at,
                    }
                )
                voter_identity_cache[cache_key] = voter_identity
            else:
                voter_identity = voter_identity_cache[cache_key]
            
            # Link vote to voter_identity
            vote.voter_identity_id = voter_identity.id
        
        # Migrate device_fingerprint to device_identifier
        vote.device_identifier = vote.device_fingerprint or 'legacy'
        
        # Hash IP address if present
        if vote.ip_address:
            ip_hash = hashlib.sha256(str(vote.ip_address).encode()).hexdigest()
        else:
            # Use hash of default IP for legacy votes
            ip_hash = hashlib.sha256(b'0.0.0.0').hexdigest()
        vote.ip_hash = ip_hash
        
        # Set vote_quantity from existing quantity field
        vote.vote_quantity = vote.quantity or 1
        
        # Save the updated vote
        vote.save(update_fields=[
            'vote_number',
            'voter_identity_id',
            'device_identifier',
            'ip_hash',
            'vote_quantity'
        ])


def reverse_migrate_votes(apps, schema_editor):
    """
    Reverse migration - clear the new fields.
    This allows rolling back if needed.
    """
    Vote = apps.get_model('voting', 'Vote')
    
    Vote.objects.all().update(
        vote_number=None,
        voter_identity_id=None,
        device_identifier='',
        ip_hash='',
        vote_quantity=1
    )


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0001_initial'),
        ('voting', '0005_add_vote_attempt_model'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Step 1: Add new fields as nullable first
        migrations.AddField(
            model_name='vote',
            name='vote_number',
            field=models.IntegerField(
                null=True,
                blank=True,
                help_text='Sequential number within the contest'
            ),
        ),
        migrations.AddField(
            model_name='vote',
            name='vote_quantity',
            field=models.IntegerField(
                null=True,
                blank=True,
                validators=[
                    django.core.validators.MinValueValidator(1),
                    django.core.validators.MaxValueValidator(1000)
                ],
                help_text='Number of votes in this record (1-1000)'
            ),
        ),
        migrations.AddField(
            model_name='vote',
            name='device_identifier',
            field=models.CharField(
                max_length=255,
                blank=True,
                default='',
                help_text='Device fingerprint or identifier for fraud detection'
            ),
        ),
        migrations.AddField(
            model_name='vote',
            name='ip_hash',
            field=models.CharField(
                max_length=64,
                blank=True,
                default='',
                help_text='SHA-256 hash of the IP address for privacy and security'
            ),
        ),
        migrations.AddField(
            model_name='vote',
            name='voter_identity',
            field=models.ForeignKey(
                null=True,
                blank=True,
                on_delete=django.db.models.deletion.RESTRICT,
                related_name='votes',
                to='voting.voteridentity',
                help_text='The verified voter identity for this vote'
            ),
        ),
        migrations.AddField(
            model_name='vote',
            name='payment',
            field=models.ForeignKey(
                null=True,
                blank=True,
                on_delete=django.db.models.deletion.RESTRICT,
                related_name='votes',
                to='payments.payment',
                help_text='Payment record for paid contests'
            ),
        ),
        
        # Step 2: Run data migration to populate new fields
        migrations.RunPython(
            migrate_existing_votes,
            reverse_migrate_votes,
        ),
        
        # Step 3: Make vote_number and vote_quantity non-nullable
        migrations.AlterField(
            model_name='vote',
            name='vote_number',
            field=models.IntegerField(
                help_text='Sequential number within the contest'
            ),
        ),
        migrations.AlterField(
            model_name='vote',
            name='vote_quantity',
            field=models.IntegerField(
                default=1,
                validators=[
                    django.core.validators.MinValueValidator(1),
                    django.core.validators.MaxValueValidator(1000)
                ],
                help_text='Number of votes in this record (1-1000)'
            ),
        ),
        
        # Step 4: Add new indexes for performance
        migrations.AddIndex(
            model_name='vote',
            index=models.Index(fields=['poll', 'vote_number'], name='voting_vote_poll_vote_num_idx'),
        ),
        migrations.AddIndex(
            model_name='vote',
            index=models.Index(fields=['voter_identity'], name='voting_vote_voter_identity_idx'),
        ),
        migrations.AddIndex(
            model_name='vote',
            index=models.Index(fields=['payment'], name='voting_vote_payment_idx'),
        ),
    ]
