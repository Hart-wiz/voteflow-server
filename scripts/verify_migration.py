#!/usr/bin/env python3
"""Check Poll-to-Contest migration invariants against the configured database."""

import os
import sys
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import django

django.setup()

from django.db.models import F, Sum

from accounts.models import User
from polls.models import Contest, Contestant, Poll
from voting.models import Vote


def verify_contest_count():
    unmapped = Poll.objects.exclude(contest_record__isnull=False).count()
    if unmapped:
        raise AssertionError(f"{unmapped} legacy Poll rows have no linked Contest.")
    return Poll.objects.count()


def verify_foreign_keys():
    contestant_mismatches = Vote.objects.exclude(
        contestant__poll_id=F("poll_id")
    ).count()
    identity_mismatches = Vote.objects.filter(
        voter_identity__isnull=False
    ).exclude(
        voter_identity__contest__source_poll_id=F("poll_id")
    ).count()
    if contestant_mismatches or identity_mismatches:
        raise AssertionError(
            f"Vote relation errors: {contestant_mismatches} contestant, "
            f"{identity_mismatches} voter identity."
        )
    return 0


def verify_vote_counts():
    mismatches = []
    totals = Vote.objects.values("contestant_id").annotate(total=Sum("vote_quantity"))
    for item in totals.iterator():
        actual = Contestant.objects.filter(pk=item["contestant_id"]).values_list(
            "votes", flat=True
        ).first()
        if actual != item["total"]:
            mismatches.append((item["contestant_id"], actual, item["total"]))
            if len(mismatches) == 5:
                break
    if mismatches:
        raise AssertionError(f"Contestant vote totals do not match Vote rows: {mismatches}")
    return totals.count()


def verify_user_roles():
    unpromoted = User.objects.filter(role=User.Role.USER, polls__isnull=False).distinct().count()
    if unpromoted:
        raise AssertionError(f"{unpromoted} legacy poll creators still have the USER role.")
    return User.objects.filter(role=User.Role.ORGANIZER, polls__isnull=False).distinct().count()


def verify_no_null_violations():
    invalid = Vote.objects.filter(vote_number__lt=1).count()
    missing_device = Vote.objects.filter(device_identifier="").count()
    missing_ip_hash = Vote.objects.filter(ip_hash="").count()
    if invalid or missing_device or missing_ip_hash:
        raise AssertionError(
            "Vote field violations: "
            f"{invalid} vote numbers, {missing_device} device identifiers, "
            f"{missing_ip_hash} IP hashes."
        )
    return 0


CHECKS = (
    ("contest count", verify_contest_count),
    ("foreign keys", verify_foreign_keys),
    ("vote counts", verify_vote_counts),
    ("user roles", verify_user_roles),
    ("required vote fields", verify_no_null_violations),
)


def main():
    try:
        for label, check in CHECKS:
            result = check()
            print(f"PASS {label}: {result}")
    except Exception as exc:
        print(f"FAIL migration verification: {exc}", file=sys.stderr)
        return 1
    print("Migration verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
