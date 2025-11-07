from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from sqlmodel import Session, select
from backend.models import Feed, Pee, Poop, PumpedMilk, PumpingSession, get_session, init_db
from backend.targets import to_ml_from_oz, to_oz_from_ml


RATE_LIMIT_DEFAULT = os.getenv("RATE_LIMIT", "60/minute")


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):  # type: ignore[override]
    return PlainTextResponse("Rate limit exceeded", status_code=429)


app = FastAPI(title="Baby Tracker")

# Rate limiting (per-IP)
limiter = Limiter(key_func=get_remote_address, default_limits=[RATE_LIMIT_DEFAULT])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

templates = Jinja2Templates(directory="backend/templates")


@app.on_event("startup")
def on_startup() -> None:
    # Ensure database tables exist
    init_db()


@app.get("/healthz", response_class=PlainTextResponse)
async def healthz() -> str:
    return "ok"


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    context: Dict[str, Any] = {
        "request": request,
    }
    return templates.TemplateResponse("index.html", context)


@app.get("/manage", response_class=HTMLResponse)
async def manage(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("manage.html", {"request": request})


def _kind_title(kind: str) -> str:
    if kind == "feeding":
        return "Feeding"
    if kind == "pee":
        return "Pee"
    if kind == "poop":
        return "Poop"
    if kind == "pumping":
        return "Pumping"
    return kind


@app.get("/manage/{kind}", response_class=HTMLResponse)
async def manage_list(
    request: Request,
    kind: str,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    kind = kind.strip().lower()
    rows: list[dict] = []

    if kind == "feeding":
        feed_rows = session.exec(select(Feed).order_by(Feed.timestamp_utc.desc())).all()
        for fr in feed_rows:
            ts = fr.timestamp_utc
            # Normalize to UTC if tzinfo missing
            if getattr(ts, "tzinfo", None) is None:
                ts = ts.replace(tzinfo=timezone.utc)
            # Send UTC ISO string - frontend will convert to local time
            ts_iso = ts.isoformat()
            text = f"{fr.amount_oz:.1f} oz ({fr.amount_ml:.0f} ml)"
            rows.append({"id": fr.id, "text": text, "timestamp_utc": ts_iso})
    elif kind == "pee":
        pee_rows = session.exec(select(Pee).order_by(Pee.timestamp_utc.desc())).all()
        for pr in pee_rows:
            ts = pr.timestamp_utc
            if getattr(ts, "tzinfo", None) is None:
                ts = ts.replace(tzinfo=timezone.utc)
            ts_iso = ts.isoformat()
            rows.append({"id": pr.id, "text": "", "timestamp_utc": ts_iso})
    elif kind == "poop":
        poop_rows = session.exec(select(Poop).order_by(Poop.timestamp_utc.desc())).all()
        for pr in poop_rows:
            ts = pr.timestamp_utc
            if getattr(ts, "tzinfo", None) is None:
                ts = ts.replace(tzinfo=timezone.utc)
            ts_iso = ts.isoformat()
            rows.append({"id": pr.id, "text": "", "timestamp_utc": ts_iso})
    elif kind == "pumping":
        sessions = session.exec(
            select(PumpingSession).order_by(PumpingSession.timestamp_utc.desc())
        ).all()
        ids: list[int] = [int(ps.id) for ps in sessions if ps.id is not None]
        totals_by_session: dict[int, tuple[float, float]] = {}
        if ids:
            milk_rows = session.exec(
                select(PumpedMilk).where(PumpedMilk.session_id.in_(ids))
            ).all()
            for mr in milk_rows:
                sid = int(mr.session_id)
                total_oz, total_ml = totals_by_session.get(sid, (0.0, 0.0))
                totals_by_session[sid] = (total_oz + float(mr.amount_oz), total_ml + float(mr.amount_ml))
        for ps in sessions:
            ts = ps.timestamp_utc
            if getattr(ts, "tzinfo", None) is None:
                ts = ts.replace(tzinfo=timezone.utc)
            ts_iso = ts.isoformat()
            mins = int(max(0, ps.duration_seconds) // 60)
            secs = int(max(0, ps.duration_seconds) % 60)
            total_oz, total_ml = totals_by_session.get(int(ps.id), (0.0, 0.0))  # type: ignore[arg-type]
            text = f"{mins}m {secs}s — {total_oz:.1f} oz ({total_ml:.0f} ml)"
            rows.append({"id": ps.id, "text": text, "timestamp_utc": ts_iso})
    else:
        return HTMLResponse("<div class='card'><p>Not found.</p></div>", status_code=404)

    context: Dict[str, Any] = {
        "request": request,
        "kind": kind,
        "kind_title": _kind_title(kind),
        "rows": rows,
    }
    return templates.TemplateResponse("manage_list.html", context)


@app.get("/manage/{kind}/{item_id}/edit", response_class=HTMLResponse)
async def manage_edit(
    request: Request,
    kind: str,
    item_id: int,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    kind = kind.strip().lower()
    obj = None
    
    if kind == "feeding":
        obj = session.get(Feed, item_id)
    elif kind == "pee":
        obj = session.get(Pee, item_id)
    elif kind == "poop":
        obj = session.get(Poop, item_id)
    elif kind == "pumping":
        obj = session.get(PumpingSession, item_id)
    else:
        return HTMLResponse("<div class='card'><p>Not found.</p></div>", status_code=404)
    
    if obj is None:
        return HTMLResponse("<div class='card'><p>Entry not found.</p></div>", status_code=404)
    
    # Get the timestamp as UTC ISO string
    ts = obj.timestamp_utc
    if getattr(ts, "tzinfo", None) is None:
        ts = ts.replace(tzinfo=timezone.utc)
    timestamp_utc_iso = ts.isoformat()
    
    # Create display text based on kind (without timestamp - JS will add it)
    if kind == "feeding":
        entry_details = f"{obj.amount_oz:.1f} oz ({obj.amount_ml:.0f} ml)"
    elif kind == "pumping":
        mins = int(max(0, obj.duration_seconds) // 60)
        secs = int(max(0, obj.duration_seconds) % 60)
        # Get total milk for this session
        milk_rows = session.exec(
            select(PumpedMilk).where(PumpedMilk.session_id == item_id)
        ).all()
        total_oz = sum((row.amount_oz for row in milk_rows), 0.0)
        total_ml = sum((row.amount_ml for row in milk_rows), 0.0)
        entry_details = f"{mins}m {secs}s — {total_oz:.1f} oz ({total_ml:.0f} ml)"
    else:
        entry_details = ""
    
    context: Dict[str, Any] = {
        "request": request,
        "kind": kind,
        "kind_title": _kind_title(kind),
        "item_id": item_id,
        "timestamp_utc_iso": timestamp_utc_iso,
        "entry_details": entry_details,
    }
    return templates.TemplateResponse("edit_time.html", context)


@app.post("/manage/{kind}/{item_id}/update")
async def manage_update(
    request: Request,
    kind: str,
    item_id: int,
    timestamp_utc: str = Form(...),
    session: Session = Depends(get_session),
):
    kind = kind.strip().lower()
    
    # Parse the UTC ISO timestamp from the form
    try:
        utc_dt = datetime.fromisoformat(timestamp_utc.replace("Z", "+00:00"))
    except Exception:
        return HTMLResponse("<div class='card'><p>Invalid time format.</p></div>", status_code=400)
    
    obj = None
    if kind == "feeding":
        obj = session.get(Feed, item_id)
    elif kind == "pee":
        obj = session.get(Pee, item_id)
    elif kind == "poop":
        obj = session.get(Poop, item_id)
    elif kind == "pumping":
        obj = session.get(PumpingSession, item_id)
    else:
        return HTMLResponse("<div class='card'><p>Not found.</p></div>", status_code=404)
    
    if obj is None:
        return HTMLResponse("<div class='card'><p>Entry not found.</p></div>", status_code=404)
    
    # Update the timestamp
    obj.timestamp_utc = utc_dt
    session.add(obj)
    session.commit()
    
    return RedirectResponse(url=f"/manage/{kind}", status_code=303)


@app.post("/manage/{kind}/{item_id}/delete")
async def manage_delete(
    request: Request,
    kind: str,
    item_id: int,
    session: Session = Depends(get_session),
):
    kind = kind.strip().lower()
    if kind == "feeding":
        obj = session.get(Feed, item_id)
        if obj is not None:
            session.delete(obj)
            session.commit()
        return RedirectResponse(url=f"/manage/{kind}", status_code=303)
    if kind == "pee":
        obj = session.get(Pee, item_id)
        if obj is not None:
            session.delete(obj)
            session.commit()
        return RedirectResponse(url=f"/manage/{kind}", status_code=303)
    if kind == "poop":
        obj = session.get(Poop, item_id)
        if obj is not None:
            session.delete(obj)
            session.commit()
        return RedirectResponse(url=f"/manage/{kind}", status_code=303)
    if kind == "pumping":
        # Delete associated milk entries first
        milk_rows = session.exec(
            select(PumpedMilk).where(PumpedMilk.session_id == item_id)
        ).all()
        for mr in milk_rows:
            session.delete(mr)
        obj = session.get(PumpingSession, item_id)
        if obj is not None:
            session.delete(obj)
        session.commit()
        return RedirectResponse(url=f"/manage/{kind}", status_code=303)
    return HTMLResponse("<div class='card'><p>Not found.</p></div>", status_code=404)


@app.get("/status", response_class=HTMLResponse)
async def status_page(
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)

    feed_rows = session.exec(select(Feed).where(Feed.timestamp_utc >= cutoff).order_by(Feed.timestamp_utc)).all()
    feed_count = len(feed_rows)
    total_oz = sum((row.amount_oz for row in feed_rows), 0.0)
    total_ml = sum((row.amount_ml for row in feed_rows), 0.0)
    avg_oz = (total_oz / feed_count) if feed_count > 0 else 0.0
    
    # Calculate average time between feeds
    avg_time_between_feeds_hours = None
    if feed_count > 1:
        timestamps = [
            row.timestamp_utc if getattr(row.timestamp_utc, "tzinfo", None) is not None
            else row.timestamp_utc.replace(tzinfo=timezone.utc)
            for row in feed_rows
        ]
        time_diffs = [
            (timestamps[i+1] - timestamps[i]).total_seconds() / 3600.0
            for i in range(len(timestamps) - 1)
        ]
        avg_time_between_feeds_hours = sum(time_diffs) / len(time_diffs) if time_diffs else None

    from backend.targets import targets_for_now

    ml_range, oz_range, age_d = targets_for_now(now)

    def feed_color() -> str:
        if feed_count == 0 or oz_range is None:
            return "muted"
        low = oz_range.low
        high = oz_range.high
        # Compare total intake in the past 24h against the daily target band
        if total_oz < low * 0.9 or total_oz > high * 1.1:
            return "status-red"
        if total_oz < low or total_oz > high:
            return "status-yellow"
        return "status-green"

    # sqlmodel's .count() on Result may not be available in all versions; fallback:
    try:
        pees_count = session.exec(select(Pee).where(Pee.timestamp_utc >= cutoff)).count()  # type: ignore[attr-defined]
    except Exception:
        pees_count = len(session.exec(select(Pee).where(Pee.timestamp_utc >= cutoff)).all())
    pees_color = "status-green" if pees_count >= 6 else "status-red"

    last_poop = session.exec(select(Poop).order_by(Poop.timestamp_utc.desc())).first()
    since_last_hours = None
    poop_color = "muted"
    if last_poop is not None:
        poop_ts = last_poop.timestamp_utc
        if getattr(poop_ts, "tzinfo", None) is None:
            poop_ts = poop_ts.replace(tzinfo=timezone.utc)
        delta_h = (now - poop_ts).total_seconds() / 3600.0
        since_last_hours = delta_h
        poop_color = "status-green"
        if delta_h > 48:
            poop_color = "status-red"
        elif delta_h > 24:
            poop_color = "status-yellow"

    # Pumping totals window (fixed to last 24h)
    pump_cutoff = cutoff

    pumping_sessions = session.exec(
        select(PumpingSession).where(PumpingSession.timestamp_utc >= pump_cutoff)
    ).all()
    total_pump_seconds = sum((max(0, int(ps.duration_seconds)) for ps in pumping_sessions), 0)
    session_ids: list[int] = [int(ps.id) for ps in pumping_sessions if ps.id is not None]
    total_pumped_oz = 0.0
    total_pumped_ml = 0.0
    if session_ids:
        milk_rows = session.exec(
            select(PumpedMilk).where(PumpedMilk.session_id.in_(session_ids))
        ).all()
        total_pumped_oz = sum((row.amount_oz for row in milk_rows), 0.0)
        total_pumped_ml = sum((row.amount_ml for row in milk_rows), 0.0)

    pump_hours = int(total_pump_seconds // 3600)
    pump_minutes = int((total_pump_seconds % 3600) // 60)

    context: Dict[str, Any] = {
        "request": request,
        "feeds": {
            "count": feed_count,
            "total_oz": total_oz,
            "total_ml": total_ml,
            "avg_oz": avg_oz,
            "avg_time_between_hours": avg_time_between_feeds_hours,
            "color": feed_color(),
        },
        "pees": {
            "count": pees_count,
            "color": pees_color,
        },
        "poops": {
            "since_last_hours": since_last_hours,
            "color": poop_color,
        },
        "targets": {
            "ml": ml_range,
            "oz": oz_range,
        },
        "age_days": age_d,
        "pumping": {
            "total_seconds": total_pump_seconds,
            "hours": pump_hours,
            "minutes": pump_minutes,
            "total_oz": total_pumped_oz,
            "total_ml": total_pumped_ml,
        },
    }
    return templates.TemplateResponse("status.html", context)


@app.get("/modal/feed", response_class=HTMLResponse)
async def modal_feed(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("modal_feed.html", {"request": request})


@app.get("/modal/pee", response_class=HTMLResponse)
async def modal_pee(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("modal_pee.html", {"request": request})


@app.get("/modal/poop", response_class=HTMLResponse)
async def modal_poop(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("modal_poop.html", {"request": request})


@app.get("/pumping", response_class=HTMLResponse)
async def pumping_page(request: Request) -> HTMLResponse:
    context: Dict[str, Any] = {
        "request": request,
        "target_seconds": 15 * 60,
    }
    return templates.TemplateResponse("pumping.html", context)


@app.post("/api/pumping_sessions", response_class=HTMLResponse)
async def create_pumping_session(
    request: Request,
    timestamp_utc: str = Form(...),
    duration_seconds: int = Form(...),
    extra_seconds: int = Form(0),
    milk_amount: list[float] = Form([]),
    milk_unit: list[str] = Form([]),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    # Parse timestamp
    try:
        ts = datetime.fromisoformat(timestamp_utc.replace("Z", "+00:00"))
    except Exception:
        return HTMLResponse("<div class='card'><p>Invalid time.</p></div>", status_code=400)

    if duration_seconds < 0:
        duration_seconds = 0
    if extra_seconds < 0:
        extra_seconds = 0

    pumping = PumpingSession(
        timestamp_utc=ts,
        duration_seconds=int(duration_seconds),
        extra_seconds=int(extra_seconds),
        target_seconds=15 * 60,
    )
    session.add(pumping)
    session.commit()
    session.refresh(pumping)

    # Normalize milk entries
    n = min(len(milk_amount), len(milk_unit))
    for i in range(n):
        amt = milk_amount[i]
        unit = (milk_unit[i] or "oz").strip().lower()
        if unit not in ("oz", "ml"):
            unit = "oz"
        if unit == "oz":
            amount_oz = float(amt)
            amount_ml = float(to_ml_from_oz(amount_oz))
        else:
            amount_ml = float(amt)
            amount_oz = float(to_oz_from_ml(amount_ml))
        entry = PumpedMilk(
            session_id=pumping.id,  # type: ignore[arg-type]
            amount_ml=amount_ml,
            amount_oz=amount_oz,
            unit=unit,
        )
        session.add(entry)

    session.commit()

    return RedirectResponse(url="/", status_code=303)


@app.post("/api/feeds", response_class=HTMLResponse)
async def create_feed(
    request: Request,
    timestamp_utc: str = Form(...),
    amount_oz: float | None = Form(None),
    amount_ml: float | None = Form(None),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    if amount_oz is None and amount_ml is None:
        return HTMLResponse("<div class='card'><p>Enter an amount.</p></div>", status_code=400)
    if amount_oz is not None and amount_ml is None:
        amount_ml = to_ml_from_oz(amount_oz)
    if amount_ml is not None and amount_oz is None:
        amount_oz = to_oz_from_ml(amount_ml)

    try:
        ts = datetime.fromisoformat(timestamp_utc.replace("Z", "+00:00"))
    except Exception:
        return HTMLResponse("<div class='card'><p>Invalid time.</p></div>", status_code=400)

    feed = Feed(timestamp_utc=ts, amount_ml=float(amount_ml), amount_oz=float(amount_oz))  # type: ignore[arg-type]
    session.add(feed)
    session.commit()
    return HTMLResponse("""
      <div class='card'>
        <p>Feed logged.</p>
        <div class='spacer'></div>
        <a class='button' href='#' onclick="document.getElementById('modals').innerHTML='';">Close</a>
      </div>
    """)


@app.post("/api/pees", response_class=HTMLResponse)
async def create_pee(
    request: Request,
    timestamp_utc: str = Form(...),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    try:
        ts = datetime.fromisoformat(timestamp_utc.replace("Z", "+00:00"))
    except Exception:
        return HTMLResponse("<div class='card'><p>Invalid time.</p></div>", status_code=400)
    pee = Pee(timestamp_utc=ts)
    session.add(pee)
    session.commit()
    return HTMLResponse("""
      <div class='card'>
        <p>Pee logged.</p>
        <div class='spacer'></div>
        <a class='button' href='#' onclick="document.getElementById('modals').innerHTML='';">Close</a>
      </div>
    """)


@app.post("/api/poops", response_class=HTMLResponse)
async def create_poop(
    request: Request,
    timestamp_utc: str = Form(...),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    try:
        ts = datetime.fromisoformat(timestamp_utc.replace("Z", "+00:00"))
    except Exception:
        return HTMLResponse("<div class='card'><p>Invalid time.</p></div>", status_code=400)
    poop = Poop(timestamp_utc=ts)
    session.add(poop)
    session.commit()
    return HTMLResponse("""
      <div class='card'>
        <p>Poop logged.</p>
        <div class='spacer'></div>
        <a class='button' href='#' onclick="document.getElementById('modals').innerHTML='';">Close</a>
      </div>
    """)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8080")), reload=True)


