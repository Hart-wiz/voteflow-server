# VoteFlow Backend Handoff Guide

This document is designed for the backend developer (or AI agent) building the **VoteFlow Django REST API**. The frontend is fully built and expects the exact API contracts, authentication flows, and data structures outlined below.

## 1. Architecture Overview
- **Framework:** Django with Django REST Framework (DRF).
- **Authentication:** JWT (JSON Web Tokens) using `djangorestframework-simplejwt`.
- **Base API Path:** All endpoints must be prefixed with `/api/v1/` (or matching `NEXT_PUBLIC_API_URL`).
- **Response Format:** Standard JSON. For lists, use DRF's standard pagination format:
  ```json
  {
    "count": 100,
    "next": "http://api.../?page=2",
    "previous": null,
    "results": [...]
  }
  ```

---

## 2. Database Models (Expected Schema)

### `User` (Custom User Model)
- `id` (UUID)
- `name` (String)
- `email` (String, Unique)
- `password` (Hashed)
- `avatarUrl` (URL, optional)
- `role` (Enum: `'user'`, `'creator'`, `'admin'`)
- `createdAt` (Datetime)

### `Poll`
- `id` (UUID)
- `slug` (String, Unique, SlugField)
- `title` (String)
- `organizer` (String - could be FK to User.name)
- `category` (String)
- `description` (Text)
- `image` (URL / ImageField - used as the poll's banner image)
- `status` (Enum: `'active'`, `'ending_soon'`, `'closed'`, `'draft'`, `'new'`)
- `endsAt` (Datetime - ISO 8601 string expected by frontend)
- `isPaid` (Boolean)
- `pricePerVote` (Decimal, optional)
- `tags` (Array of Strings / M2M to Tag model)
- `votesCount` (Integer, dynamically calculated total votes across all contestants)

### `Contestant`
- `id` (UUID)
- `poll` (FK to Poll, related_name='contestants')
- `name` (String)
- `author` (String)
- `description` (Text)
- `image` (URL / ImageField)
- `votes` (Integer, default=0 - or dynamically calculated)

### `Transaction` (Wallet History)
- `id` (UUID)
- `user` (FK to User)
- `date` (Datetime)
- `description` (String)
- `amount` (Decimal - positive for credits/earnings, negative for debits/withdrawals)
- `status` (Enum: `'completed'`, `'pending'`, `'failed'`)
- `type` (Enum: `'earning'`, `'withdrawal'`, `'refund'`)

### `Vote` (Log)
- `id` (UUID)
- `poll` (FK to Poll)
- `contestant` (FK to Contestant)
- `voter_email` or `user` (FK to User, optional)
- `quantity` (Integer, default=1)
- `payment_ref` (String, optional, for paid polls)
- `createdAt` (Datetime)

---

## 3. API Endpoints & Contracts

### Authentication (`/auth/`)
*Frontend uses `lib/api/auth.ts`.*

- `POST /auth/login/`
  - **Payload:** `{ "email": "...", "password": "..." }`
  - **Response:** `{ "user": { ...UserObj }, "tokens": { "access": "...", "refresh": "..." } }`
- `POST /auth/register/`
  - **Payload:** `{ "name": "...", "email": "...", "password": "..." }`
  - **Response:** `{ "user": { ...UserObj }, "tokens": { "access": "...", "refresh": "..." } }`
- `POST /auth/logout/`
  - **Payload:** `{ "refresh": "..." }` (Blacklists the refresh token)
- `POST /auth/token/refresh/`
  - **Payload:** `{ "refresh": "..." }`
  - **Response:** `{ "access": "...", "refresh": "..." }`
- `GET /auth/me/` (Requires Auth)
  - **Response:** `{ ...UserObj }`
- `PATCH /auth/me/` (Requires Auth)
  - **Payload:** Partial User object.

### Polls (`/polls/`)
*Frontend uses `lib/api/polls.ts`.*

- `GET /polls/`
  - **Query Params:** `search`, `category`, `status`, `ordering`
  - **Response:** Paginated list of `Poll` objects. (Frontend expects `contestants` array nested inside the poll, or at least `votesCount`).
- `GET /polls/my-polls/` (Requires Auth, Creator/Admin only)
  - **Response:** Paginated list of `Poll` objects owned by the authenticated user.
- `GET /polls/<slug>/`
  - **Response:** Full `Poll` object including nested `contestants` array.
- `POST /polls/` (Requires Auth, accepts `multipart/form-data`)
  - **Payload:** Poll object data (supports uploading a banner `image` file).
  - **Nested Contestants:** Optionally include contestants during creation by passing a `contestants` JSON string, or as form-data arrays (e.g., `contestants[0][name]=...`).
- `PATCH /polls/<slug>/` (Requires Auth, Organizer only, accepts `multipart/form-data`)
  - **Payload:** Partial Poll object data.
- `DELETE /polls/<slug>/` (Requires Auth, Organizer only)
- `POST /polls/<slug>/contestants/` (Requires Auth, Organizer or Admin only, accepts `multipart/form-data`)
  - **Payload:** Contestant object data (`name`, `author`, `description`, `image` file).
  - **Behavior:** Adds a new contestant/nominee to an existing poll.

### Voting (`/polls/<slug>/vote/`)
- `POST /polls/<slug>/vote/`
  - **Payload:** 
    ```json
    {
      "contestant_id": "uuid",
      "quantity": 1,
      "email": "voter@example.com",
      "payment_ref": "paystack_txn_ref_123" // Only sent if poll.isPaid == true
    }
    ```
  - **Behavior (CRITICAL):**
    1. If `poll.isPaid` is true, the backend **must** call the Paystack API using `payment_ref` to verify the transaction was successful and matches `quantity * poll.pricePerVote`.
    2. Increment the `votes` count for the contestant by `quantity`.
    3. If paid, create a `Transaction` (type: earning) for the poll's organizer, increasing their wallet balance.
  - **Response:** `{ "success": true, "message": "Vote cast successfully" }`

- `GET /polls/<slug>/results/`
  - **Response:** Array of `Contestant` objects sorted by votes.

### Wallet (`/wallet/`)
*Frontend uses `lib/api/wallet.ts`.*

- `GET /wallet/` (Requires Auth)
  - **Response:** 
    ```json
    {
      "availableBalance": 5000.00,
      "pendingEarnings": 250.00,
      "lifetimeEarnings": 12000.00,
      "transactions": [ ... Array of recent Transaction objects ... ]
    }
    ```
- `GET /wallet/transactions/?page=1` (Requires Auth)
  - **Response:** Paginated `Transaction` objects.
- `POST /wallet/withdraw/` (Requires Auth)
  - **Payload:** `{ "amount": 1000, "bank_code": "058", "account_number": "0123456789" }`
  - **Behavior:** Deduct from `availableBalance`, create a pending `Transaction` (type: withdrawal), and optionally trigger Paystack Transfers API.
  - **Response:** `{ "success": true, "reference": "wth_123", "message": "Withdrawal queued" }`

---

## 4. Frontend Types Mapping
If you want to perfectly match the frontend's expectations, review the `lib/types.ts` file in the frontend repository. It contains the exact TypeScript interfaces the frontend uses to parse your JSON responses.

## 5. Fraud Prevention & Security
- **CORS:** Ensure `CORS_ALLOWED_ORIGINS` includes the frontend URL (e.g., `http://localhost:3000`).
- **Free Voting:** Implement IP/Device fingerprinting or require verified emails to prevent free-vote spamming.
- **Paid Voting:** Never trust the frontend for payment completion. Always verify the `payment_ref` server-to-server with Paystack before granting the votes.
