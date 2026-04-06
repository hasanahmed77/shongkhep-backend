# Shongkhep Backend

FastAPI backend for the Shongkhep app with RSS ingestion.

## Architecture

- `FastAPI` for HTTP APIs
- `SQLAlchemy 2.0` async ORM for Postgres access
- `Celery + Redis` for ingestion jobs
- modular layers for `api`, `services`, `repositories`, `models`, and `workers`
- future-ready `users` and `user_preferences` tables for auth and personalization
- RSS ingestion for BD publishers like Prothom Alo
- summaries generated from the first 59 words of the RSS article text

## Local setup

1. Start infrastructure:

```bash
docker compose up -d
```

2. Create a virtualenv and install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

3. Copy env file:

```bash
cp .env.example .env
```

4. Run the API:

```bash
uvicorn app.main:app --reload
```

For Expo Go on a real device, start the API on your LAN-visible interface:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Then point Expo to:

```bash
EXPO_PUBLIC_API_BASE_URL=http://192.168.0.176:8000/api/v1
```

5. Run the worker:

```bash
celery -A app.workers.celery_app.celery_app worker --loglevel=info
```

6. Generate and apply migrations:

```bash
alembic revision --autogenerate -m "initial schema"
alembic upgrade head
```

7. Seed demo data:

```bash
python -m app.db.seed
```

Default BD RSS source:

```bash
RSS_FEED_URLS_EN=["https://en.prothomalo.com/stories.rss"]
RSS_FEED_URLS_BN=["https://www.prothomalo.com/feed"]
```

## API surface

- `GET /api/v1/health`
- `GET /api/v1/news/en`
- `POST /api/v1/news/sync`
- `GET /api/v1/users/me/preferences`

## Long-term plan

- add JWT auth provider integration to `users`
- add ranking pipeline and embeddings with `pgvector`
- add more BD publisher feeds and per-source category mapping
# shongkhep-backend
# shongkhep-backend
