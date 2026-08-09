# Backend Architecture

AlgoLens is moving toward a layer-first DDD structure under `backend/algolens`.
The legacy `routes`, `services`, and `database.py` modules can remain as
compatibility shims while behavior is migrated.

## Layers

- `domain`: pure business rules and data concepts. It must not import Flask,
  psycopg2, JWT libraries, Werkzeug, environment variables, or HTTP concerns.
- `application`: use cases and abstract ports. It coordinates domain behavior
  through repository/session interfaces.
- `infrastructure`: implementations of ports using Postgres, Werkzeug, JWT,
  environment configuration, and other external services.
- `adapters`: Flask routes, request parsing, HTTP status mapping, and JSON
  response serialization.

## Dependency Direction

Dependencies point inward:

```text
adapters -> application -> domain
infrastructure -> application/domain
```

The domain layer is the stable core. New business rules should start there when
they are pure. Database queries belong in infrastructure repositories. Flask
request/response code belongs in HTTP adapters.
