# Generated manually for Task 4.1: Enhance Payment model with vote attempt linking
# Requirements: 7.1, 7.3, 7.5, 7.9, 7.10, 7.12, 7.13

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0002_alter_transaction_options'),
        ('voting', '0005_add_vote_attempt_model'),
    ]

    operations = [
        # Add vote_attempt FK with CASCADE delete (nullable for backward compatibility)
        migrations.AddField(
            model_name='payment',
            name='vote_attempt',
            field=models.ForeignKey(
                blank=True,
                help_text='The vote attempt this payment is associated with',
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='payments',
                to='voting.voteattempt'
            ),
        ),
        
        # Add provider_reference with unique constraint and index (nullable for migration)
        migrations.AddField(
            model_name='payment',
            name='provider_reference',
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text='Unique reference from payment provider (e.g., Paystack)',
                max_length=255,
                null=True,
                unique=True
            ),
        ),
        
        # Add total_amount decimal field
        migrations.AddField(
            model_name='payment',
            name='total_amount',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Total payment amount (vote_quantity × price_per_vote)',
                max_digits=8,
                null=True
            ),
        ),
        
        # Add organizer_earnings decimal field
        migrations.AddField(
            model_name='payment',
            name='organizer_earnings',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Amount credited to organizer after revenue share calculation',
                max_digits=8,
                null=True
            ),
        ),
        
        # Add currency field (ISO 4217)
        migrations.AddField(
            model_name='payment',
            name='currency',
            field=models.CharField(
                default='NGN',
                help_text='ISO 4217 currency code (e.g., NGN, USD, EUR)',
                max_length=3
            ),
        ),
        
        # Add confirmed_at timestamp
        migrations.AddField(
            model_name='payment',
            name='confirmed_at',
            field=models.DateTimeField(
                blank=True,
                help_text='Timestamp when payment was confirmed',
                null=True
            ),
        ),
        
        # Update Status enum choices to include CONFIRMED and REFUNDED
        migrations.AlterField(
            model_name='payment',
            name='status',
            field=models.CharField(
                choices=[
                    ('PENDING', 'Pending'),
                    ('CONFIRMED', 'Confirmed'),
                    ('FAILED', 'Failed'),
                    ('REFUNDED', 'Refunded'),
                ],
                default='PENDING',
                max_length=20
            ),
        ),
        
        # Make email field optional (for backward compatibility)
        migrations.AlterField(
            model_name='payment',
            name='email',
            field=models.EmailField(blank=True, default='', max_length=254),
        ),
        
        # Make amount field optional (use total_amount instead)
        migrations.AlterField(
            model_name='payment',
            name='amount',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='[LEGACY] Use total_amount instead',
                max_digits=10,
                null=True
            ),
        ),
        
        # Make reference field optional (use provider_reference instead)
        migrations.AlterField(
            model_name='payment',
            name='reference',
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text='[LEGACY] Use provider_reference instead',
                max_length=255,
                null=True,
                unique=True
            ),
        ),
        
        # Add new indexes
        migrations.AddIndex(
            model_name='payment',
            index=models.Index(fields=['provider_reference'], name='payments_pa_provide_idx'),
        ),
        migrations.AddIndex(
            model_name='payment',
            index=models.Index(fields=['user', 'status'], name='payments_pa_user_st_idx'),
        ),
        migrations.AddIndex(
            model_name='payment',
            index=models.Index(fields=['vote_attempt'], name='payments_pa_vote_at_idx'),
        ),
    ]
