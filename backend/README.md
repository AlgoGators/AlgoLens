# AlgoLens Backend (Flask API)

See the root [`README.md`](../README.md) and [`DEPLOYMENT.md`](../DEPLOYMENT.md) for architecture and deployment. This file covers local backend setup only.

## Installation

```bash
cd backend
pip install -r requirements.txt
```

## Configuration

Create `backend/.env` (see `backend/.env.example`) with:

```env
DB_HOST=your-database-host
DB_PORT=5432
DB_USER=your-database-user
DB_PASSWORD=your-database-password
DB_NAME=your-database-name
JWT_SECRET_KEY=your-super-secret-jwt-key-change-this-to-something-random
FLASK_ENV=production
FLASK_DEBUG=False
PORT=5000
CORS_ORIGINS=https://yourdomain.com
```

`backend/.env` is gitignored — never commit real credentials.

## Database Schema

```sql
CREATE SCHEMA IF NOT EXISTS auth;

CREATE TABLE auth.users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255),
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    role VARCHAR(50) DEFAULT 'general_member',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

Users are pre-authorized by inserting a row with `email` set and `password_hash` left `NULL`/empty (see `add_user_email.py`); they then complete registration via `POST /auth/register`, which sets their password.

## Running

```bash
cd backend
python app.py
```

Runs at `http://localhost:5000`.

## API Endpoints

### `POST /auth/check-email`
Checks whether an email is pre-authorized and whether it has completed registration.

### `POST /auth/register`
Completes registration for a pre-authorized email. Body: `{ "email", "password", "first_name", "last_name" }`.

### `POST /auth/login`
Body: `{ "email", "password" }`. Returns `{ "token", "user" }`.

### `GET /auth/verify`
Verifies a JWT. Header: `Authorization: Bearer <token>`.

### `GET /portfolio/strategies`
Returns summary data for all strategies. Requires `Authorization: Bearer <token>`.

### `GET /portfolio/strategy/<strategy_id>`
Returns full detail for one strategy. Requires `Authorization: Bearer <token>`.

## Notes

- Passwords are hashed with `werkzeug.security.generate_password_hash()`.
- `add_user_email.py <email>` pre-authorizes an email for registration.
