import os
import django
from django.core.files.base import ContentFile

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from polls.models import Poll
from accounts.models import User

def test_upload():
    print("Testing Cloudinary Upload...")
    
    # Minimal valid GIF (1x1 red pixel) to simulate an image upload
    gif_data = b'GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\x00\x00\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
    
    try:
        creator = User.objects.first()
        if not creator:
            print("No user found. Please run seed_data.py first.")
            return

        # Create a dummy poll
        poll = Poll(title='Cloudinary Test Poll', creator=creator)
        
        # This will trigger the Cloudinary storage backend using Django's FileField
        poll.image.save('test_image.gif', ContentFile(gif_data))
        poll.save()
        
        print("\n[SUCCESS] Upload Successful!")
        print("Cloudinary Image URL:", poll.image.url)
        
        # Clean up the test record
        poll.delete()
        print("Test poll record cleaned up.")
        
    except Exception as e:
        print("\n[ERROR] Upload Failed!")
        print("Error details:", str(e))
        print("\nPlease make sure you have added your valid CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, and CLOUDINARY_API_SECRET to the .env file.")

if __name__ == '__main__':
    test_upload()
