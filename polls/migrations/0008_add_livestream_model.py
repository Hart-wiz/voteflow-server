# Generated migration for Livestream model

import uuid
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('polls', '0007_add_contestant_media'),
    ]

    operations = [
        migrations.CreateModel(
            name='Livestream',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('stream_url', models.URLField(help_text='URL of the livestream (e.g., YouTube, Twitch, custom RTMP endpoint).', max_length=2048)),
                ('stream_key', models.CharField(help_text='Private streaming key for the provider.', max_length=255)),
                ('provider', models.CharField(help_text="Livestream provider (e.g., 'youtube', 'twitch', 'custom').", max_length=100)),
                ('status', models.CharField(choices=[('SCHEDULED', 'Scheduled'), ('LIVE', 'Live'), ('ENDED', 'Ended')], default='SCHEDULED', help_text='Current status of the livestream.', max_length=20)),
                ('scheduled_start_time', models.DateTimeField(help_text='When the livestream is scheduled to start (timezone-aware).')),
                ('actual_start_time', models.DateTimeField(blank=True, help_text='When the livestream actually started (set when status → LIVE).', null=True)),
                ('ended_at', models.DateTimeField(blank=True, help_text='When the livestream ended (set when status → ENDED).', null=True)),
                ('viewer_count', models.PositiveIntegerField(default=0, help_text='Current number of viewers watching the livestream.')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('contest', models.OneToOneField(blank=True, help_text='The contest this livestream is associated with.', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='livestream', to='polls.contest')),
            ],
            options={
                'db_table': 'polls_livestream',
            },
        ),
        migrations.AddIndex(
            model_name='livestream',
            index=models.Index(fields=['contest', 'status'], name='polls_lives_contest_status_idx'),
        ),
    ]
