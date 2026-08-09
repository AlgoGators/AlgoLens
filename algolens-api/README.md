# AlgoLens API

Flask backend for AlgoLens. The service is self-contained under
`algolens-api/`; the Python package is `algolens/`.

## Setup

```bash
cd algolens-api
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Fill in database credentials, `JWT_SECRET_KEY`, and production `CORS_ORIGINS` in
`.env`.

## Run

Development:

```bash
python app.py
```

Production WSGI target:

```bash
gunicorn --bind 0.0.0.0:5000 --workers 2 --threads 4 wsgi:app
```

## Test

```bash
python -m pytest tests -q
```

The tests are designed to run without a live database. Production fail-closed
checks run in subprocesses, and portfolio/registry tests stub database access.

## Architecture

The layer-first structure is documented in `docs/architecture.md`. Legacy
`routes/`, `services/`, `database.py`, and `app.py` modules remain as thin
compatibility shims.
