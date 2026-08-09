# AlgoLens Backend

## Running

```bash
cd backend
pip install -r requirements.txt
python app.py
```

The server listens on `http://localhost:5000` by default.

## Structure

New backend code should live under `backend/algolens`:

```text
algolens/
  domain/          pure rules and models
  application/     use cases and ports
  infrastructure/  Postgres, JWT, Werkzeug, config, and other implementations
  adapters/        Flask routes and JSON serializers
```

Legacy `routes/`, `services/`, and `database.py` modules remain as compatibility
entrypoints while the refactor settles. See `backend/docs/architecture.md` for
dependency rules.

## Auth

JWTs are delivered as httpOnly cookies. Login and registration responses include
the `user` object but do not include a body token. The SPA restores sessions with
`GET /auth/verify`, which authenticates via the cookie.

Production startup requires:

```bash
JWT_SECRET_KEY=...
CORS_ORIGINS=https://your-frontend.example
```

In development, `DEV_MODE=1` enables `POST /auth/dev-login` when
`FLASK_ENV` is not `production`.

## Public Endpoints

- `POST /auth/login`
- `GET /auth/verify`
- `POST /auth/logout`
- `POST /auth/check-email`
- `POST /auth/register`
- `POST /auth/dev-login` in local dev mode only
- `GET /portfolio/strategies`
- `GET /portfolio/strategy/<strategy_id>`
- `GET /health`
