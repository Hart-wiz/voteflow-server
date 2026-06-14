from django.db import models
from django.contrib.auth.models import AbstractUser


# Create your models here.
class User(AbstractUser):
    email = models.EmailField(unique=True)
    phone_number = models.CharField(max_length=20, blank=True, null=True)

    is_creator = models.BooleanField(default=False)
    is_voter = models.BooleanField(default=True)

    def __str__(self):
        return self.username