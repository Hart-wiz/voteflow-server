import os
import django
import requests
from datetime import timedelta
from django.utils import timezone
from django.core.files.base import ContentFile

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from accounts.models import User
from polls.models import Poll, Contestant

def fetch_and_save_image(instance, field_name, url, filename):
    """Fetches an image from a URL and saves it to the instance's ImageField if it's empty."""
    field = getattr(instance, field_name)
    if not field:
        try:
            print(f"Downloading default image for {filename}...")
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                field.save(filename, ContentFile(response.content), save=True)
        except Exception as e:
            print(f"Failed to fetch image for {filename}: {e}")

def seed():
    # Create superuser
    admin, created = User.objects.get_or_create(
        email='admin@example.com',
        defaults={
            'name': 'Admin User',
            'role': User.Role.ADMIN,
            'is_staff': True,
            'is_superuser': True,
        }
    )
    if created:
        admin.set_password('password123')
        admin.save()
        print("Superuser created: admin@example.com / password123")

    # Create normal user/creator
    creator, created = User.objects.get_or_create(
        email='creator@example.com',
        defaults={'name': 'Creator User', 'role': User.Role.CREATOR}
    )
    if created:
        creator.set_password('password123')
        creator.save()
        print("Creator created: creator@example.com / password123")

    # Image URLs to use as defaults
    POLL_BANNER_URL = "https://res.cloudinary.com/demo/image/upload/v1312461204/sample.jpg"
    AVATAR_URL = "https://res.cloudinary.com/demo/image/upload/v1690000000/docs/models.jpg"

    # Update Poll 1 (Free)
    poll1, created = Poll.objects.get_or_create(
        title='Best Programming Language 2026',
        defaults={
            'creator': creator,
            'organizer': 'Global Tech Foundation',
            'category': 'Technology',
            'description': 'Vote for the best programming language of 2026.',
            'status': Poll.Status.ACTIVE,
            'ends_at': timezone.now() + timedelta(days=30),
            'tags': ['programming', 'tech'],
            'is_paid': False,
        }
    )
    fetch_and_save_image(poll1, 'image', POLL_BANNER_URL, 'tech_banner.jpg')
    
    if created:
        print("Created Poll:", poll1.title)
        c1 = Contestant.objects.create(poll=poll1, name='Python', author='Python Software Foundation', description='A versatile language.')
        fetch_and_save_image(c1, 'image', AVATAR_URL, 'python.jpg')
        
        c2 = Contestant.objects.create(poll=poll1, name='JavaScript', author='ECMA International', description='The language of the web.')
        fetch_and_save_image(c2, 'image', AVATAR_URL, 'js.jpg')
        
        c3 = Contestant.objects.create(poll=poll1, name='Rust', author='Rust Foundation', description='Safe and fast.')
        fetch_and_save_image(c3, 'image', AVATAR_URL, 'rust.jpg')

    # Create Poll 2 (Free)
    poll2, created = Poll.objects.get_or_create(
        title='Next Tech Innovation',
        defaults={
            'creator': admin,
            'organizer': 'Future Trends Magazine',
            'category': 'Innovation',
            'description': 'What will be the next big tech innovation?',
            'status': Poll.Status.ACTIVE,
            'ends_at': timezone.now() + timedelta(days=60),
            'tags': ['future', 'tech'],
        }
    )
    fetch_and_save_image(poll2, 'image', POLL_BANNER_URL, 'innovation_banner.jpg')
    
    if created:
        print("Created Poll:", poll2.title)
        c1 = Contestant.objects.create(poll=poll2, name='Quantum Computing')
        fetch_and_save_image(c1, 'image', AVATAR_URL, 'quantum.jpg')
        
        c2 = Contestant.objects.create(poll=poll2, name='AGI')
        fetch_and_save_image(c2, 'image', AVATAR_URL, 'agi.jpg')
        
        c3 = Contestant.objects.create(poll=poll2, name='Neural Interfaces')
        fetch_and_save_image(c3, 'image', AVATAR_URL, 'neural.jpg')

    # Create Poll 3 (Paid Poll)
    poll3, created = Poll.objects.get_or_create(
        title='Global Photography Awards 2026',
        defaults={
            'creator': creator,
            'organizer': 'World Photo Organization',
            'category': 'Art & Photography',
            'description': 'Vote for the best photograph of the year. This is a paid poll to support the artists! Each vote costs $2.50.',
            'status': Poll.Status.ACTIVE,
            'ends_at': timezone.now() + timedelta(days=15),
            'tags': ['art', 'photography', 'paid'],
            'is_paid': True,
            'price_per_vote': 2.50,
        }
    )
    fetch_and_save_image(poll3, 'image', POLL_BANNER_URL, 'photo_banner.jpg')
    
    if created:
        print("Created Paid Poll:", poll3.title)
        c1 = Contestant.objects.create(poll=poll3, name='Mountain Sunset', author='Jane Doe', description='A breathtaking sunset over the Rockies.')
        fetch_and_save_image(c1, 'image', AVATAR_URL, 'photo1.jpg')
        
        c2 = Contestant.objects.create(poll=poll3, name='Urban Jungle', author='John Smith', description='Cyberpunk aesthetic street photography.')
        fetch_and_save_image(c2, 'image', AVATAR_URL, 'photo2.jpg')
        
        c3 = Contestant.objects.create(poll=poll3, name='Ocean Depths', author='Maria Garcia', description='Close-up of a rare jellyfish.')
        fetch_and_save_image(c3, 'image', AVATAR_URL, 'photo3.jpg')

    print("Data seeded successfully with Cloudinary images.")

if __name__ == '__main__':
    seed()
