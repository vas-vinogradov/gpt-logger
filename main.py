from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from googleapiclient.discovery import build
from google.auth import default
from google.oauth2 import service_account

app = FastAPI()

SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
SHEET_NAME = os.environ.get("SHEET_NAME", "Sheet1")
API_KEY = os.environ.get("API_KEY", "")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

WRITE_RANGE = f"{SHEET_NAME}!A:E"
READ_RANGE = f"{SHEET_NAME}!A:E"


def sheets_service():
    credentials, _ = default(scopes=SCOPES)
    return build("sheets", "v4", credentials=credentials)


def append_row(row: list[Any]) -> None:
    service = sheets_service()
    body = {"values": [row]}
    service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=WRITE_RANGE,
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body=body,
    ).execute()


def get_all_rows() -> list[list[str]]:
    service = sheets_service()   
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=READ_RANGE,
    ).execute()
    return result.get("values", [])


def parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None

    # Accept either ISO timestamps or sheet-style datetimes like 3/7/2026 9:00:00
    for fmt in (
        None,  # ISO
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
    ):
        try:
            if fmt is None:
                dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            else:
                dt = datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def rows_to_events(rows: list[list[str]]) -> list[dict[str, Any]]:
    if not rows:
        return []

    # Assume first row is header if it looks like one
    start_idx = 1 if rows[0][:5] == ["Timestamp", "Event", "Value", "Units", "Notes"] else 0

    events: list[dict[str, Any]] = []
    for row in rows[start_idx:]:
        padded = row + [""] * (5 - len(row))
        ts, event, value, units, notes = padded[:5]

        try:
            numeric_value: float | str = float(value) if value != "" else ""
        except ValueError:
            numeric_value = value

        events.append(
            {
                "timestamp": ts,
                "dt": parse_timestamp(ts),
                "event": event,
                "value": numeric_value,
                "units": units,
                "notes": notes,
            }
        )
    return events


@app.get("/")
def root():
    return {"ok": True, "service": "roadmap80-logger"}


@app.post("/event")
def log_event(payload: dict, x_api_key: str | None = Header(default=None)):
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="unauthorized")

    event = payload.get("event")
    if not event:
        raise HTTPException(status_code=400, detail="missing event")

    timestamp = payload.get("timestamp") or datetime.now(timezone.utc).isoformat()
    value = payload.get("value", "")
    units = payload.get("units", "")
    notes = payload.get("notes", "")

    row = [timestamp, event, value, units, notes]
    append_row(row)
    return {"ok": True}


@app.get("/summary/today")
def summary_today():
    now = datetime.now(timezone.utc)
    events = rows_to_events(get_all_rows())

    today_events = [e for e in events if e["dt"] and e["dt"].date() == now.date()]

    totals = defaultdict(float)
    counts = defaultdict(int)

    for e in today_events:
        counts[e["event"]] += 1
        if isinstance(e["value"], (int, float)):
            totals[f'{e["event"]}:{e["units"]}'] += float(e["value"])

    return {
        "date": str(now.date()),
        "count": len(today_events),
        "events_by_type": dict(counts),
        "totals": dict(totals),
        "events": today_events,
    }


@app.get("/summary/week")
def summary_week():
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=7)

    events = rows_to_events(get_all_rows())
    week_events = [e for e in events if e["dt"] and e["dt"] >= start]

    totals = defaultdict(float)
    counts = defaultdict(int)

    for e in week_events:
        counts[e["event"]] += 1
        if isinstance(e["value"], (int, float)):
            totals[f'{e["event"]}:{e["units"]}'] += float(e["value"])

    return {
        "from": start.isoformat(),
        "to": now.isoformat(),
        "count": len(week_events),
        "events_by_type": dict(counts),
        "totals": dict(totals),
        "events": week_events,
    }

@app.get("/test")
def test_read():
    service = sheets_service()
    sheet = service.spreadsheets()

    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!A1:E5"
    ).execute()

    return result

@app.get("/health")
def health():
    return {"ok": True}