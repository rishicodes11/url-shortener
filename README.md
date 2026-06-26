# URL Shortener

Paste a long URL, get a short one. Built with FastAPI, PostgreSQL, and Redis.

---

## Features

- Short code generation using base62 encoding
- Custom vanity codes
- Link expiry
- Click analytics (total clicks, daily trends, device breakdown)
- Redis caching for fast redirects
- Rate limiting
- Docker support

## Quick Start

```bash
git clone https://github.com/rishicodes11/url-shortener
cd url-shortener
cp .env.example .env
docker compose up --build
```

## Environment Variables

```
DATABASE_URL=postgresql://shortener:shortener123@postgres:5432/urlshortener
REDIS_URL=redis://redis:6379
BASE_URL=http://localhost:8000
```

## API

| Method | Endpoint | Description |
|---|---|---|
| POST | /shorten | Shorten a URL |
| GET | /{short_code} | Redirect to original URL |
| GET | /stats/{short_code} | View click analytics |

## Tech Stack

FastAPI · PostgreSQL · Redis · Docker