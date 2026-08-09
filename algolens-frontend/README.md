# AlgoLens Frontend

Self-contained Vite/React frontend service for AlgoLens.

## Development

```bash
npm ci
npm run dev
```

The dev server runs on `http://localhost:3000`.

## Environment

Copy `.env.example` to `.env` for local overrides.

- `VITE_API_URL`: backend API base URL, defaults to `http://localhost:5000`
- `VITE_DEV_MODE`: set to `1` to auto-authenticate through `/auth/dev-login`; the backend must also run with `DEV_MODE=1`

## Validation

```bash
npm run build
npm test
```
