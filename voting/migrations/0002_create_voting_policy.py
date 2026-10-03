# Generated migration for VotingPolicy model

import uuid
from decimal import Decimal

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('voting', '0001_initial'),
        ('polls', '0002_contest'),
    ]

    operations = [
        migrations.CreateModel(
            name='VotingPolicy',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('vote_limit_type', models.CharField(
                    choices=[
                        ('ONE', 'One Vote'),
                        ('LIMITED', 'Limited Votes'),
                        ('UNLIMITED', 'Unlimited Votes')
                    ],
                    default='UNLIMITED',
                    help_text='Type of vote limit for this contest.',
                    max_length=20
                )),
                ('max_votes_per_voter', models.IntegerField(
                    blank=True,
                    help_text='Maximum votes per voter (required when vote_limit_type is LIMITED).',
                    null=True,
                    validators=[
                        django.core.validators.MinValueValidator(2),
                        django.core.validators.MaxValueValidator(1000)
                    ]
                )),
                ('verification_method', models.CharField(
                    choices=[
                        ('EMAIL', 'Email'),
                        ('PHONE', 'Phone'),
                        ('NIN', 'National ID Number'),
                        ('VOTERS_CARD', "Voter's Card"),
                        ('FINGERPRINT', 'Fingerprint'),
                        ('COMPOSITE', 'Multiple Methods'),
                        ('NONE', 'No Verification')
                    ],
                    default='NONE',
                    help_text='Identity verification method required for voters.',
                    max_length=20
                )),
                ('required_verification_methods', models.JSONField(
                    blank=True,
                    help_text="Array of verification methods for COMPOSITE type (e.g., ['EMAIL', 'PHONE']).",
                    null=True
                )),
                ('price_per_vote', models.DecimalField(
                    decimal_places=2,
                    default=Decimal('0.00'),
                    help_text='Price per individual vote in the contest currency.',
                    max_digits=8,
                    validators=[
                        django.core.validators.MinValueValidator(Decimal('0.00')),
                        django.core.validators.MaxValueValidator(Decimal('999999.99'))
                    ]
                )),
                ('revenue_share_percentage', models.IntegerField(
                    default=80,
                    help_text='Percentage of revenue that goes to organizer (0-100).',
                    validators=[
                        django.core.validators.MinValueValidator(0),
                        django.core.validators.MaxValueValidator(100)
                    ]
                )),
                ('allow_anonymous', models.BooleanField(
                    default=False,
                    help_text='Whether anonymous (non-authenticated) voting is permitted.'
                )),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('contest', models.OneToOneField(
                    help_text='The contest this voting policy applies to.',
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='voting_policy',
                    to='polls.contest'
                )),
            ],
            options={
                'verbose_name': 'Voting Policy',
                'verbose_name_plural': 'Voting Policies',
                'db_table': 'voting_votingpolicy',
            },
        ),
        migrations.AddConstraint(
            model_name='votingpolicy',
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ('vote_limit_type', 'LIMITED'),
                    ('max_votes_per_voter__isnull', False)
                ) | models.Q(
                    ('vote_limit_type__in', ['ONE', 'UNLIMITED']),
                    ('max_votes_per_voter__isnull', True)
                ),
                name='max_votes_required_for_limited',
                violation_error_message='max_votes_per_voter is required when vote_limit_type is LIMITED.'
            ),
        ),
        migrations.AddConstraint(
            model_name='votingpolicy',
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ('verification_method', 'COMPOSITE'),
                    ('required_verification_methods__isnull', False)
                ) | models.Q(
                    ('verification_method__in', ['EMAIL', 'PHONE', 'NIN', 'VOTERS_CARD', 'FINGERPRINT', 'NONE']),
                    ('required_verification_methods__isnull', True)
                ),
                name='composite_requires_methods',
                violation_error_message='required_verification_methods is required when verification_method is COMPOSITE.'
            ),
        ),
    ]
