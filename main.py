from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import FastAPI, Depends, HTTPException, Request, BackgroundTasks
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
import os
from dotenv import load_dotenv

from app.database import engine, get_db, Base, SessionLocal
from app.models import URL, Click
from app.base62 import encode
from app.cache import redis_client
from datetime import datetime, timedelta, timezone

load_dotenv()

# Create all tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="URL Shortener")

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")


class ShortenRequest(BaseModel):
    long_url: str
    expires_in_days: int | None = None


@app.post("/shorten")
@limiter.limit("10/minute")
def shorten_url(request: Request, body: ShortenRequest, db: Session = Depends(get_db)):
    # Calculate expiry date if provided
    expires_at = None
    if body.expires_in_days:
        expires_at = datetime.now(timezone.utc) + timedelta(days=body.expires_in_days)

    # Step 1 — create the URL row
    new_url = URL(long_url=body.long_url, expires_at=expires_at)
    db.add(new_url)
    db.commit()
    db.refresh(new_url)

    # Step 2 — generate short code from ID
    short_code = encode(new_url.id)
    new_url.short_code = short_code
    db.commit()

    return {
        "short_url": f"{BASE_URL}/{short_code}",
        "short_code": short_code,
        "long_url": body.long_url,
        "expires_at": expires_at
    }

@app.get("/stats/{short_code}")
def get_stats(short_code: str, db: Session = Depends(get_db)):
    url = db.query(URL).filter(URL.short_code == short_code).first()
    if not url:
        raise HTTPException(status_code=404, detail="Short URL not found")

    clicks = db.query(Click).filter(Click.url_id == url.id).all()

    # Total clicks
    total_clicks = len(clicks)

    # Clicks by day
    clicks_by_day = {}
    for click in clicks:
        day = click.clicked_at.strftime("%Y-%m-%d")
        clicks_by_day[day] = clicks_by_day.get(day, 0) + 1

    # Device breakdown (simple — mobile vs desktop)
    devices = {"mobile": 0, "desktop": 0}
    for click in clicks:
        ua = (click.user_agent or "").lower()
        if "mobile" in ua or "android" in ua or "iphone" in ua:
            devices["mobile"] += 1
        else:
            devices["desktop"] += 1

    return {
        "short_code": short_code,
        "long_url": url.long_url,
        "created_at": url.created_at,
        "total_clicks": total_clicks,
        "clicks_by_day": clicks_by_day,
        "devices": devices
    }


@app.get("/{short_code}")
@limiter.limit("60/minute")
def redirect_to_url(short_code: str, request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    # Step 1 — check Redis cache first
    cached = redis_client.get(short_code)
    if cached:
        url_id, long_url = cached.split("|", 1)
        background_tasks.add_task(log_click, int(url_id), request.headers.get("user-agent"), request.client.host)
        return RedirectResponse(url=long_url)

    # Step 2 — cache miss, check database
    url = db.query(URL).filter(URL.short_code == short_code).first()
    if not url:
        raise HTTPException(status_code=404, detail="Short URL not found")

    # Step 3 — check if expired
    if url.expires_at and url.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="This short URL has expired")

    # Step 4 — store in cache with TTL matching expiry
    if url.expires_at:
        seconds_left = int((url.expires_at - datetime.now(timezone.utc)).total_seconds())
        redis_client.set(short_code, f"{url.id}|{url.long_url}", ex=seconds_left)
    else:
        redis_client.set(short_code, f"{url.id}|{url.long_url}")

    # Step 5 — log click in background
    background_tasks.add_task(log_click, url.id, request.headers.get("user-agent"), request.client.host)

    return RedirectResponse(url=url.long_url)


def log_click(url_id: int, user_agent: str, ip_address: str):
    db = SessionLocal()
    try:
        click = Click(url_id=url_id, user_agent=user_agent, ip_address=ip_address)
        db.add(click)
        db.commit()
    finally:
        db.close()