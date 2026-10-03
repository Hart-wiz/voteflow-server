# Generated migration for Contest model

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('polls', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Contest',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('slug', models.SlugField(db_index=True, max_length=300, unique=True)),
                ('title', models.CharField(max_length=255)),
                ('description', models.TextField(blank=True, default='')),
                ('category', models.CharField(blank=True, default='', max_length=100)),
                ('image', models.ImageField(blank=True, null=True, upload_to='contests/')),
                ('tags', models.JSONField(blank=True, default=list)),
                ('state', models.CharField(
                    choices=[
                        ('DRAFT', 'Draft'),
                        ('SCHEDULED', 'Scheduled'),
                        ('LIVE', 'Live'),
                        ('PAUSED', 'Paused'),
                        ('CLOSED', 'Closed'),
                        ('CANCELLED', 'Cancelled'),
                        ('ARCHIVED', 'Archived'),
                        ('SUSPENDED', 'Suspended')
                    ],
                    db_index=True,
                    default='DRAFT',
                    help_text='Current lifecycle state of the contest.',
                    max_length=20
                )),
                ('timezone', models.CharField(
                    default='UTC',
                    help_text="IANA timezone identifier (e.g., 'America/New_York')",
                    max_length=50
                )),
                ('start_time', models.DateTimeField(
                    blank=True,
                    help_text='When the contest is scheduled to start (timezone-aware).',
                    null=True
                )),
                ('end_time', models.DateTimeField(
                    blank=True,
                    help_text='When the contest is scheduled to end (timezone-aware).',
                    null=True
                )),
                ('published_at', models.DateTimeField(
                    blank=True,
                    help_text='When the contest transitioned to LIVE state.',
                    null=True
                )),
                ('closed_at', models.DateTimeField(
                    blank=True,
                    help_text='When the contest transitioned to CLOSED state.',
                    null=True
                )),
                ('results_visibility', models.CharField(
                    choices=[
                        ('after_close', 'After Close'),
                        ('real_time', 'Real Time'),
                        ('never', 'Never')
                    ],
                    default='after_close',
                    help_text='Controls when results can be viewed by users.',
                    max_length=20
                )),
                ('version', models.IntegerField(
                    default=0,
                    help_text='Version number for optimistic locking during state transitions.'
                )),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('organizer', models.ForeignKey(
                    help_text='The user who created and manages this contest.',
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='contests',
                    to=settings.AUTH_USER_MODEL
                )),
            ],
            options={
                'db_table': 'polls_contest',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='contest',
            index=models.Index(fields=['slug'], name='polls_conte_slug_a1b2c3_idx'),
        ),
        migrations.AddIndex(
            model_name='contest',
            index=models.Index(fields=['state', 'start_time'], name='polls_conte_state_d4e5f6_idx'),
        ),
        migrations.AddIndex(
            model_name='contest',
            index=models.Index(fields=['organizer', 'state'], name='polls_conte_organiz_g7h8i9_idx'),
        ),
        migrations.AddIndex(
            model_name='contest',
            index=models.Index(fields=['category'], name='polls_conte_categor_j0k1l2_idx'),
        ),
        migrations.AddConstraint(
            model_name='contest',
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ('end_time__gte', models.F('start_time'))
                ) | models.Q(
                    ('end_time__isnull', True)
                ) | models.Q(
                    ('start_time__isnull', True)
                ),
                name='valid_time_range'
            ),
        ),
    ]
