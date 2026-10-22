from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from polls.models import Contest, Contestant, ContestantMedia, Livestream, Poll
from polls.services import add_contestant_media, create_livestream, update_livestream_status


class ContestantMediaServiceTests(TestCase):
    def setUp(self):
        self.organizer = User.objects.create_user(
            email="organizer@example.com", name="Organizer", password="StrongPassword123!", role=User.Role.ORGANIZER
        )
        poll = Poll.objects.create(creator=self.organizer, title="Media Poll", slug="media-poll")
        self.contestant = Contestant.objects.create(poll=poll, name="Contestant")

    def _file(self, name="portrait.jpg", content=b"image"):
        return SimpleUploadedFile(name, content, content_type="application/octet-stream")

    @patch("polls.services.default_storage.url", return_value="https://cdn.example.test/image.jpg")
    @patch("polls.services.default_storage.save", return_value="contestants/image.jpg")
    def test_image_and_video_uploads_assign_order(self, save, url):
        image = add_contestant_media(
            self.contestant, self._file(), ContestantMedia.MediaType.IMAGE, "Portrait"
        )
        video = add_contestant_media(
            self.contestant, self._file("clip.mp4"), ContestantMedia.MediaType.VIDEO
        )
        self.assertEqual(image.display_order, 0)
        self.assertEqual(video.display_order, 1)
        self.assertEqual(image.file_url, "https://cdn.example.test/image.jpg")
        self.assertEqual(save.call_count, 2)

    def test_media_file_type_and_size_are_validated(self):
        with self.assertRaises(ValidationError):
            add_contestant_media(self.contestant, self._file("script.exe"), "IMAGE")
        with self.assertRaises(ValidationError):
            add_contestant_media(self.contestant, self._file("large.mp4", b"x" * (10 * 1024 * 1024 + 1)), "VIDEO")

    @patch("polls.services.default_storage.url", return_value="https://cdn.example.test/image.jpg")
    @patch("polls.services.default_storage.save", return_value="contestants/image.jpg")
    def test_eleven_media_items_are_rejected(self, save, url):
        for index in range(10):
            ContestantMedia.objects.create(
                contestant=self.contestant,
                media_type=ContestantMedia.MediaType.IMAGE,
                file_url=f"https://cdn.example.test/{index}.jpg",
                file_size_bytes=100,
                display_order=index,
            )
        with self.assertRaises(ValidationError):
            add_contestant_media(self.contestant, self._file(), ContestantMedia.MediaType.IMAGE)
        save.assert_not_called()


class LivestreamServiceTests(TestCase):
    def setUp(self):
        organizer = User.objects.create_user(
            email="organizer@example.com", name="Organizer", password="StrongPassword123!", role=User.Role.ORGANIZER
        )
        self.contest = Contest.objects.create(organizer=organizer, title="Stream", slug="stream-contest")

    def test_livestream_status_updates_timestamps(self):
        stream = create_livestream(
            self.contest,
            "https://stream.example.test/live",
            "custom",
            timezone.now() + timedelta(minutes=5),
            "private-key",
        )
        stream = update_livestream_status(stream, Livestream.Status.LIVE)
        self.assertIsNotNone(stream.actual_start_time)
        stream = update_livestream_status(stream, Livestream.Status.ENDED)
        self.assertIsNotNone(stream.ended_at)

    def test_active_stream_prevents_second_stream(self):
        create_livestream(
            self.contest,
            "https://stream.example.test/live",
            "custom",
            timezone.now(),
            "private-key",
        )
        with self.assertRaises(ValidationError):
            create_livestream(
                self.contest,
                "https://stream.example.test/second",
                "custom",
                timezone.now(),
                "second-key",
            )

    def test_ended_stream_cannot_be_changed_but_can_be_reused(self):
        stream = create_livestream(
            self.contest,
            "https://stream.example.test/live",
            "custom",
            timezone.now(),
            "private-key",
        )
        update_livestream_status(stream, Livestream.Status.ENDED)
        with self.assertRaises(ValidationError):
            update_livestream_status(stream, Livestream.Status.LIVE)
        replacement = create_livestream(
            self.contest,
            "https://stream.example.test/replay",
            "custom",
            timezone.now(),
            "new-key",
        )
        self.assertEqual(replacement.pk, stream.pk)
        self.assertEqual(replacement.status, Livestream.Status.SCHEDULED)
