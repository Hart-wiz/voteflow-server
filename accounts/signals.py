from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from payments.models import Wallet


# Auto Create Wallet for Users
User = get_user_model()


@receiver(post_save, sender=User)
def create_wallet(sender, instance, created, **kwargs):
    if created:
        Wallet.objects.create(user=instance)