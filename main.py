from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
import os
from dotenv import load_dotenv

from app.database import engine, get_db, Base
from app.models import URL, Click
from app.base62 import encode
from app.cache import redis_client

load_dotenv()

# Create all tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="URL Shortener")

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")

class ShortenRequest(BaseModel):
    long_url: str

@app.post("/shorten")
def shorten_url(request: ShortenRequest, db: Session = Depends(get_db)):
    # Step 1 — create the URL row (short_code empty for now)
    new_url = URL(long_url=request.long_url)
    db.add(new_url)
    db.commit()
    db.refresh(new_url)

    # Step 2 — now we have an ID, generate the short code
    short_code = encode(new_url.id)
    new_url.short_code = short_code
    db.commit()

    return {
        "short_url": f"{BASE_URL}/{short_code}",
        "short_code": short_code,
        "long_url": request.long_url
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
def redirect_to_url(short_code: str, request: Request, db: Session = Depends(get_db)):
    # Step 1 — check Redis cache first
    cached_url = redis_client.get(short_code)
    if cached_url:
        log_click(db, short_code, request)
        return RedirectResponse(url=cached_url)

    # Step 2 — not in cache, check database
    url = db.query(URL).filter(URL.short_code == short_code).first()
    if not url:
        raise HTTPException(status_code=404, detail="Short URL not found")

    # Step 3 — store in cache for next time
    redis_client.set(short_code, url.long_url)

    # Step 4 — log the click
    log_click(db, short_code, request)

    return RedirectResponse(url=url.long_url)


def log_click(db: Session, short_code: str, request: Request):
    url = db.query(URL).filter(URL.short_code == short_code).first()
    if url:
        click = Click(
            url_id=url.id,
            user_agent=request.headers.get("user-agent"),
            ip_address=request.client.host
        )
        db.add(click)
        db.commit()