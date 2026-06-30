from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from .models import Poll, Contestant

User = get_user_model()

class PollViewSetTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(email='test@example.com', name='Test User', password='password123')
        self.poll = Poll.objects.create(
            title="Test Poll",
            slug="test-poll",
            description="A test poll",
            creator=self.user,
            status=Poll.Status.ACTIVE,
            category="Others"
        )
        self.contestant = Contestant.objects.create(
            name="Contestant 1",
            poll=self.poll
        )

    def test_list_polls(self):
        response = self.client.get(reverse('polls:poll-list'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['title'], "Test Poll")

    def test_vote_free_poll(self):
        url = reverse('polls:poll-vote', kwargs={'slug': self.poll.slug})
        data = {
            "contestant_id": str(self.contestant.id),
            "quantity": 1,
            "email": "voter@example.com"
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        
        # Verify the vote was recorded
        self.contestant.refresh_from_db()
        self.assertEqual(self.contestant.votes, 1)

    def test_vote_rate_limit(self):
        # Cast 3 votes quickly (the limit is 3 per 10 seconds)
        url = reverse('polls:poll-vote', kwargs={'slug': self.poll.slug})
        data = {"contestant_id": str(self.contestant.id), "quantity": 1, "email": "voter@example.com"}
        
        for _ in range(3):
            res = self.client.post(url, data, format='json', REMOTE_ADDR="127.0.0.1")
            self.assertEqual(res.status_code, status.HTTP_200_OK)
            
        # The 4th vote should be rate-limited
        res_limited = self.client.post(url, data, format='json', REMOTE_ADDR="127.0.0.1")
        self.assertEqual(res_limited.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_create_poll_with_nested_contestants(self):
        self.client.force_authenticate(user=self.user)
        url = reverse('polls:poll-list')
        import json
        
        data = {
            "title": "New Nested Poll",
            "category": "Tech",
            "description": "Nested poll test",
            "status": "active",
            "contestants": json.dumps([
                {"name": "Dev A", "author": "Alice"},
                {"name": "Dev B", "author": "Bob"}
            ])
        }
        
        response = self.client.post(url, data, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        poll = Poll.objects.get(id=response.data['id'])
        self.assertEqual(poll.contestants.count(), 2)
        names = [c.name for c in poll.contestants.all()]
        self.assertIn("Dev A", names)
        self.assertIn("Dev B", names)
        
        # Test the add_contestant endpoint
        add_url = reverse('polls:poll-add-contestant', kwargs={'slug': poll.slug})
        add_data = {"name": "Dev C", "author": "Charlie"}
        add_response = self.client.post(add_url, add_data, format='json')
        self.assertEqual(add_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(poll.contestants.count(), 3)

    def test_create_poll_with_form_data_array_contestants(self):
        self.client.force_authenticate(user=self.user)
        url = reverse('polls:poll-list')
        
        data = {
            "title": "Form Data Array Poll",
            "category": "Tech",
            "description": "Form data array test",
            "status": "active",
            "contestants[0][name]": "Dev X",
            "contestants[0][author]": "Xavier",
            "contestants[1][name]": "Dev Y",
            "contestants[1][author]": "Yara",
        }
        
        response = self.client.post(url, data, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        poll = Poll.objects.get(id=response.data['id'])
        self.assertEqual(poll.contestants.count(), 2)
        names = [c.name for c in poll.contestants.all()]
        self.assertIn("Dev X", names)
        self.assertIn("Dev Y", names)

