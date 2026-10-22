# Poll to Contest Migration Guide

The backend keeps the existing `Poll`, `Contestant`, and `Vote` tables so old client URLs and historical votes remain available. The migration adds `Contest` records that preserve each legacy poll UUID and links them with `Contest.source_poll`. New contest creation also keeps a backing `Poll` record for the current client data model.

## Before connecting a real database

1. Create a PostgreSQL database and application role, then fill the database variables in `.env` as described in `SETUP.md`.
2. Take a restorable database backup before the first deployment migration.
3. Review the final migration plan with `python manage.py migrate --plan`.
4. Apply migrations to a staging copy first: `python manage.py migrate`.
5. Run `python scripts/verify_migration.py` against that staging database and review each result.
6. Exercise registration, organizer approval, contest creation, email verification, free voting, paid voting, and payment callbacks in staging.
7. Back up production, deploy the same code, apply migrations, then run the verification script again.

The migration chain first prepares vote identity and sequence fields, then creates UUID-preserving Contest rows, links legacy Poll records, assigns default VotingPolicy records, and promotes legacy poll creators to organizer roles. Votes remain tied to the original Poll and contestant rows. The vote immutability triggers are temporarily handled by the migration ordering; they are not disabled for normal application writes.

Rollback of the Poll-to-Contest data migration removes the Contest records created with matching Poll UUIDs, their default policies and dependent contest workflow rows, and only reverses organizer roles recorded by that migration. It preserves the original Poll, Contestant, and Vote records. If the new contest APIs have been used after deployment, take a backup and review dependent payment or workflow records before rolling back.

## API changes

- `GET /api/v1/polls/` remains available with `Deprecation`, `Sunset`, `Warning`, and successor `Link` headers. The configured sunset defaults to 30 days after application startup; set `API_SUNSET_AT` to a fixed UTC ISO timestamp for a release.
- New contest endpoints live under `/api/v1/contests/` and `/api/contests/`.
- Vote initiation, verification, payment, and commit endpoints live under `/api/v1/votes/` and `/api/v1/verification/`.
- Existing client Poll payloads continue to use the legacy Poll field names while the Contest API exposes lifecycle state, timezone, visibility, and policy data.

| Legacy Poll field | Contest API field |
| --- | --- |
| `status` | `state` (`DRAFT`, `SCHEDULED`, `LIVE`, `PAUSED`, `CLOSED`, `CANCELLED`, `ARCHIVED`, `SUSPENDED`) |
| `ends_at` | `end_time` (timezone-aware ISO-8601 datetime) |
| `price_per_vote` | `policy.price_per_vote` on creation and `price_per_vote` in contest responses |
| `creator` | `organizer_id` (UUID); organizer details stay under the user/auth APIs |
| poll slug path | contest slug path under `/api/v1/contests/{slug}/` |

The current client can keep using its existing token refresh flow. Send the access token as `Authorization: Bearer <access-token>`. New contest mutations require an approved `ORGANIZER` or `ADMIN`; ordinary registrations remain `USER` until an administrator approves an organizer request. Voting and verification routes require an authenticated user.

Example contest creation request:

```json
{
  "title": "Summer Music Awards",
  "timezone": "Africa/Lagos",
  "start_time": "2026-11-01T09:00:00+01:00",
  "end_time": "2026-11-02T18:00:00+01:00",
  "contestants": [{"name": "Artist A"}],
  "policy": {"price_per_vote": "100.00", "revenue_share_percentage": 80}
}
```

Keep the client and server release together during migration. The old poll routes should be removed only after client usage has moved to the Contest API and the sunset date has passed.
