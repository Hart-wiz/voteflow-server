# VoteFlow Server Setup

The server code is ready to connect to services, but this checkout has not been connected to a database or external provider. Migrations were checked and exercised only against disposable in-memory SQLite; none were applied to a persistent or user database. Follow these steps when you are ready to bring up a working environment.

## Required connections

1. **PostgreSQL** — Create a database and application user, then fill `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, and `DB_PORT` in `voteflow-server/.env`.
2. **Resend** — Create an API key and verify the sending domain. Set `RESEND_API_KEY` and `DEFAULT_FROM_EMAIL`. The default `onboarding@resend.dev` sender is for local experimentation; use a verified domain for real mail. Password reset codes, organizer approval notices, and vote notifications use this integration.
3. **Paystack** — Set the server side `PAYSTACK_SECRET_KEY`. Set `NEXT_PUBLIC_PAYSTACK_PUBLIC_KEY` in the client. Configure the Paystack webhook to call `https://YOUR_SERVER/api/v1/webhooks/paystack/`. The webhook signature uses the same server secret. Payments and poll prices are denominated in NGN; Paystack amounts are converted to kobo.
4. **Image storage** — For local development, uploads go into `voteflow-server/media/` when Cloudinary is not configured. For a deployed server, configure `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, and `CLOUDINARY_API_SECRET` so uploaded images persist outside the application filesystem.
5. **Client origin** — Set `FRONTEND_URL` to the exact browser origin, including scheme and port. The Django CORS configuration currently accepts this single origin.
6. **Redis and Celery** — Configure a reachable Redis service in `REDIS_URL`; use the same URL for `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND` unless you run separate services. Redis is needed for rate limits shared by multiple server workers. Celery Beat schedules vote-attempt expiry, contest auto-close, and suspicious-pattern checks.
7. **Identity provider (optional)** — Email verification uses Resend. If contests will require phone, NIN, voter-card, or fingerprint checks, connect a compliant HTTPS gateway and set `IDENTITY_PROVIDER_URL` and `IDENTITY_PROVIDER_API_KEY`. The gateway contract is documented in `voting/providers.py`; never send raw identity data to an untrusted endpoint.
8. **Poll API sunset (optional)** — Set `API_SUNSET_AT` to a fixed UTC ISO-8601 timestamp for the legacy Poll API `Sunset` header. If unset, the server uses 30 days after startup.

## Environment files

Copy each template and fill in local values:

```sh
cp voteflow-server/.env.example voteflow-server/.env
cp voteflow-client/.env.example voteflow-client/.env.local
```

`SECRET_KEY` must be a private random value. Set `DEBUG=False` and provide real `ALLOWED_HOSTS` for deployment. Keep `.env` and `.env.local` out of version control.

## Start the backend

This project pins Django and declares Python 3.14 in `pyproject.toml`.

```sh
cd voteflow-server
uv sync
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver 0.0.0.0:8000
```

Run these in separate processes for scheduled tasks:

```sh
uv run celery -A config worker --loglevel info
uv run celery -A config beat --loglevel info
```

The superuser manager assigns the admin role. Use `/admin/` to inspect records and uploaded development media. Organizer applicants appear in the client Admin Console after an admin account signs in.

## Start the client

```sh
cd voteflow-client
npm ci
npm run dev
```

Open `http://localhost:3000`. `NEXT_PUBLIC_API_URL` should point to the backend API root, including `/api/v1`; `NEXT_PUBLIC_PAYSTACK_PUBLIC_KEY` is required for paid voting. Free polls, account flows, wallet views, and notifications use the same API base URL.

## First-run notes

- Review `MIGRATION_GUIDE.md` and `python manage.py migrate --plan` before the first PostgreSQL migration. The `polls.0011` data migration links existing Poll records to UUID-preserving Contests and creates default policies.
- After migrating a staging copy, run `python scripts/verify_migration.py` before applying the same release to production.
- Django signals create a wallet for each new user, so run migrations before registering users.
- Organizer accounts must be approved before they can publish polls. Register with an organization name or submit a request from the Create Poll page, then approve it from the Admin Console.
- A Resend key is optional while `DEBUG=True`; email sends are logged as skipped until configured. In production, missing Resend configuration is an error for mail-dependent actions.
- Configure Paystack webhooks and transfer capability in the Paystack dashboard before relying on paid votes or withdrawals in production.
