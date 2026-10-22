"""Scheduled contest maintenance tasks."""

from celery import shared_task

from .services import close_due_contests


@shared_task(name="polls.tasks.close_ended_contests")
def close_ended_contests():
    return close_due_contests()
