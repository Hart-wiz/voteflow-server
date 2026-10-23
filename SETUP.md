# VoteFlow Server Setup

The server uses environment variables to connect to PostgreSQL and external providers. The migration checks performed for this repository used disposable in-memory SQLite; review the migration plan and your database backup before applying migrations to a persistent database.

## Required connections

1. **PostgreSQL** — Create a database and application user, then fill `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, and `DB_PORT` in `voteflow-server/.env`. Set `DB_SSLMODE=require` for Supabase connections.
2. **Resend** — Create an API key and verify the sending domain. Set `RESEND_API_KEY` and `DEFAULT_FROM_EMAIL`. The default `onboarding@resend.dev` sender is for local experimentation; use a verified domain for real mail. Password reset codes, organizer approval notices, and vote notifications use this integration.
3. **Paystack** — Set `PAYSTACK_SECRET_KEY` and `PAYSTACK_PUBLIC_KEY` in the server environment. Keep the secret key private. The public key is safe to expose and is returned by the paid-vote checkout endpoint for the embedded InlineJS popup. The browser submits only the Paystack reference; the server verifies the transaction and checks it against the saved poll, contestant, quantity, email, and amount before counting votes. Configure the Paystack webhook to call `https://YOUR_SERVER/api/v1/webhooks/paystack/`; its signature uses the server secret. Payments and poll prices are denominated in NGN; Paystack amounts are converted to kobo.
4. **Image storage** — For local development, uploads go into `voteflow-server/media/` when Cloudinary is not configured. For a deployed server, configure `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, and `CLOUDINARY_API_SECRET` so uploaded images persist outside the application filesystem.
5. **Client origin** — Set `FRONTEND_URL` to the exact browser origin, including scheme and port (for example, `https://voteflow-client.pages.dev` in production or `http://localhost:3000` locally). CORS and CSRF trust this origin. Django also allows the `voteflow-client.pages.dev` production origin and Cloudflare Pages preview subdomains by default; set `CLOUDFLARE_PAGES_DOMAIN` if your Pages project uses another `*.pages.dev` domain. If you use a custom production domain, set it as `FRONTEND_URL`. `ALLOWED_HOSTS` must contain the backend API host, not the client origin.
6. **Dragonfly and Celery** — Start a reachable Dragonfly service and set `DRAGONFLY_URL` to its Redis-protocol URL, such as `redis://localhost:6379/0` locally or `rediss://...` when the provider requires TLS. Django uses this service for shared cache/rate limits. Celery uses it for the broker and result backend by default; set `CELERY_BROKER_URL` or `CELERY_RESULT_BACKEND` only when using separate services. Run both a Celery worker and Celery Beat: the worker executes queued tasks, while Beat schedules vote-attempt expiry, contest auto-close, and suspicious-pattern checks. The Python `redis` package remains installed because Dragonfly uses the Redis protocol.
7. **Identity provider (optional)** — Email verification uses Resend. If contests will require phone, NIN, voter-card, or fingerprint checks, connect a compliant HTTPS gateway and set `IDENTITY_PROVIDER_URL` and `IDENTITY_PROVIDER_API_KEY`. The gateway contract is documented in `voting/providers.py`; never send raw identity data to an untrusted endpoint.
8. **Poll API sunset (optional)** — Set `API_SUNSET_AT` to a fixed UTC ISO-8601 timestamp for the legacy Poll API `Sunset` header. If unset, the server uses 30 days after startup.

## Environment files

Copy each template and fill in local values:

```sh
cp voteflow-server/.env.example voteflow-server/.env
cp voteflow-client/.env.example voteflow-client/.env.local
```

`SECRET_KEY` must be a private random value. Set `DEBUG=False` and provide real `ALLOWED_HOSTS` for deployment. Keep `.env` and `.env.local` out of version control.

### Supabase from an IPv4-only network

Supabase's direct `db.<project-ref>.supabase.co:5432` endpoint resolves to IPv6 unless the project has IPv4 connectivity enabled. If your network cannot reach IPv6, open the project's **Connect** dialog and copy the **Session pooler** settings. Use the exact values shown there:

- `DB_HOST`: the pooler hostname ending in `.pooler.supabase.com`
- `DB_PORT`: `5432` (session mode)
- `DB_NAME`: the database name from the connection details, usually `postgres`
- `DB_USER`: the pooler username from the connection details, usually `postgres.<project-ref>`
- `DB_PASSWORD`: the database password
- `DB_SSLMODE`: `require`

Use the pooler host and username exactly as shown in Supabase; they differ from the direct connection. Session mode is the IPv4-compatible option for a persistent Django backend and supports migration commands. Avoid the transaction pooler on port `6543` for this backend. Do not paste database passwords or full connection strings into chat or commit them to Git.

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

Start Dragonfly before the Django server and Celery processes. For local development, you can start it with Docker:

```sh
docker run -d --name voteflow-dragonfly -p 6379:6379 --ulimit memlock=-1 docker.dragonflydb.io/dragonflydb/dragonfly
```

The local `.env` uses `DRAGONFLY_URL=redis://localhost:6379/0`. For a hosted Dragonfly provider, replace it with the provider's connection URL and ensure the backend can reach that host and port. Remove legacy `REDIS_URL` and explicit `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` entries so those settings inherit Dragonfly.

The superuser manager assigns the admin role. Use `/admin/` to inspect records and uploaded development media. Organizer applicants appear in the client Admin Console after an admin account signs in.

## Start the client

```sh
cd voteflow-client
npm ci
npm run dev
```

Open `http://localhost:3000`. `NEXT_PUBLIC_API_URL` should point to the backend API root, including `/api/v1`. Paid voting loads Paystack InlineJS v2 and gets the public key, server-calculated amount, and unique reference from the backend checkout endpoint. Free polls, account flows, wallet views, and notifications use the same API base URL.

## First-run notes

- Review `MIGRATION_GUIDE.md` and `python manage.py migrate --plan` before the first PostgreSQL migration. The `polls.0011` data migration links existing Poll records to UUID-preserving Contests and creates default policies.
- After migrating a staging copy, run `python scripts/verify_migration.py` before applying the same release to production.
- Django signals create a wallet for each new user, so run migrations before registering users.
- Organizer accounts must be approved before they can publish polls. Register with an organization name or submit a request from the Create Poll page, then approve it from the Admin Console.
- A Resend key is optional while `DEBUG=True`; email sends are logged as skipped until configured. In production, missing Resend configuration is an error for mail-dependent actions.
- Configure Paystack webhooks and transfer capability in the Paystack dashboard before relying on paid votes or withdrawals in production.
