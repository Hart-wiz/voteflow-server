# VoteFlow Backend Project Documentation

This document serves as a handoff and status guide for AI agents and developers working on the VoteFlow Django REST API backend. It outlines the architectural decisions, the recently completed refactoring, the current state of the codebase, and the immediate next steps.

---

## 1. Architecture & Current State

The backend has been completely refactored to explicitly match the frontend's expected API contracts (defined in `backend.md`), utilizing `djangorestframework`, `djangorestframework-simplejwt`, and explicit `camelCase` response fields.

### App Structure
- **`config` (Project Root):** Contains the Django settings. Handles JWT configuration, database connection (`python-decouple`), CORS, and explicitly configures standard DRF parsers/renderers.
- **`accounts` (Auth & Users):** Handles User authentication using a custom UUID-based User model. Replaced the boolean permission flags with a distinct `role` Enum (`'user'`, `'creator'`, `'admin'`). Endpoints cover login, registration, token refresh, and user profile management (`/auth/me/`).
- **`polls` (Polls & Contestants):** Replaces the previous disjointed apps. The `Contestant` model has been merged into this app since the frontend treats contestants as nested resources of a poll. It features a `PollViewSet` providing CRUD, public/private list filtering, and custom actions for casting votes and retrieving results.
- **`voting` (Internal Service & Audit):** Retained purely for data modeling (`Vote` and `VoteAuditLog`) and internal service logic (`voting/services.py`). It no longer exposes direct API endpoints; instead, voting requests are routed through the `polls` app (`POST /api/v1/polls/<slug>/vote/`).
- **`payments` (Wallet & Transactions):** Consolidated the previous `payments` and `withdrawals` apps into a single cohesive wallet system. Includes the `Wallet`, Paystack `Payment` initialization records, and a unified `Transaction` model (handling earnings, withdrawals, and refunds). Features a webhook endpoint for secure, server-to-server Paystack payment verification.

### Database
- **Engine:** PostgreSQL (`psycopg2-binary`).
- **State:** The database has been recently dropped, recreated, and migrated to adopt the new UUID primary keys and model restructuring.

---

## 2. Completed Tasks

A major rebuild of the backend was just completed and verified. Here is what is done:
1. **Dependencies & Settings:** Cleaned up `requirements.txt`, added `django-filter` and `python-decouple`. Updated `settings.py` for JWT blacklisting and CORS.
2. **Auth Flow:** Built full endpoints for `/api/v1/auth/` (register, login, logout, me, refresh) with explicit `camelCase` field mapping (e.g., `avatarUrl`, `createdAt`) in `accounts/serializers.py`.
3. **Polls & Voting:** 
   - Merged `Contestant` into `polls.models`.
   - Built nested serializers to match frontend data expectations.
   - Built the `POST /polls/<slug>/vote/` endpoint with rate limiting, duplicate vote prevention, Paystack verification (for paid polls), atomic vote incrementing (using `F()`), and audit logging.
4. **Payments & Wallets:**
   - Unified transactions into the `Transaction` model.
   - Built the `/wallet/` overview and transaction endpoints.
   - Implemented Paystack payment initialization and webhook handling (with HMAC signature verification).
5. **App Consolidation:** Safely deleted the `contestants` and `withdrawals` Django apps.
6. **Data Reset:** Wiped old migrations, regenerated fresh migrations for the new schema, flushed the Postgres database, and applied migrations.
7. **Smoke Testing:** Ran an automated smoke test suite which verified that user registration (`201 Created`), authentication, user profile fetching, poll listing, and wallet data retrieval all work correctly and return the expected `camelCase` JSON payloads.

---

## 3. Where We Stopped

The backend is fully functional regarding the required endpoints and data structures. The development server boots successfully, and API endpoints are responsive. The fundamental data models, views, and routing are locked in.

**Current Active Tasks / Unfinished Business:**
- **Withdrawal Paystack Transfers API:** *[COMPLETED]* The server-to-server trigger for Paystack Transfers API in `payments/views.py` (`WithdrawView`) and the webhook handling for `transfer.success`/`failed` have been fully implemented.
- **Testing:** While manual smoke testing via Python scripts was completed, comprehensive automated unit tests (e.g., testing the Paystack webhook securely, testing complex voting scenarios) have not been extensively written.

---

## 4. Next Steps for Developers / AI Agents

If you are picking up this project, you should:

1. **Review the `.env` Configuration:** Ensure your `.env` has a valid `PAYSTACK_SECRET_KEY` before testing paid votes.
2. **Implement Paystack Transfers:** *(Completed)* The `WithdrawView` and `paystack_webhook` now handle Paystack Transfers for immediate disbursement of funds.
3. **Create Superuser & Populate Data:** Use `python manage.py createsuperuser` and the Django Admin to seed initial data, categories, or featured polls for frontend testing.
4. **Connect the Frontend:** The frontend app can now be pointed to `http://localhost:8000/api/v1/`. Run both servers and verify the integration end-to-end.
5. **Unit Testing:** Write Django tests (in `tests.py` for each app) to cover the core models and critical paths (specifically the atomic voting transactions).
