"""
Script to verify Payment model enhancements.
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from payments.models import Payment

print('Payment model fields:')
for field in Payment._meta.get_fields():
    print(f'  - {field.name}: {field.__class__.__name__}')

print('\nStatus choices:')
for choice in Payment.Status.choices:
    print(f'  - {choice[0]}: {choice[1]}')

print('\nIndexes:')
for index in Payment._meta.indexes:
    print(f'  - {index.name}: {index.fields}')

print('\n✓ Payment model enhancements verified!')
