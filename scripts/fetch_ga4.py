"""
Fetch GA4 event counts for the GALA ads dashboard.

Read-only. Returns a plain dict; it never touches data.json itself
(build_data.py owns that). Raising here is fine — the caller catches it
and marks the GA4 source as failed rather than publishing stale numbers
as if they were current.
"""

import json
import os
from datetime import date, timedelta

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Metric,
    RunReportRequest,
)
from google.oauth2 import service_account

SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]

# Events the dashboard cares about. Everything else is ignored.
EVENTS = [
    "reserve_form",
    "reserve_review",
    "reserve_success",
    "phone_tap",
    "whatsapp_tap",
    "vip_booking_start",
    "form_submit",
]

# What counts as "came from the ad". GA4 writes this as "google / cpc".
ADS_SOURCE_MEDIUM = "google / cpc"


def _client():
    raw = os.environ.get("GOOGLE_SA_KEY")
    if not raw:
        raise RuntimeError("GOOGLE_SA_KEY is not set")
    info = json.loads(raw)
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return BetaAnalyticsDataClient(credentials=creds)


def _run(client, property_id, start, end, dimensions):
    req = RunReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(start_date=start, end_date=end)],
        dimensions=[Dimension(name=d) for d in dimensions],
        metrics=[Metric(name="eventCount")],
        limit=100000,
    )
    return client.run_report(req)


def fetch(property_id=None, start_date=None, end_date=None):
    """
    Returns:
      {
        "range": {"from": "2026-07-17", "to": "2026-07-28"},
        "events":     {"reserve_form": 418, ...},   # all traffic
        "events_ads": {"reserve_form": 12,  ...},   # google / cpc only
      }
    Events with no rows are reported as 0, not omitted — a real zero and a
    missing key mean different things downstream.
    """
    property_id = property_id or os.environ.get("GA4_PROPERTY_ID", "383604323")
    start_date = start_date or os.environ.get("CAMPAIGN_START", "2026-07-17")
    # GA4's own day boundary; yesterday is the last fully-closed day.
    end_date = end_date or str(date.today() - timedelta(days=1))

    client = _client()

    totals = {e: 0 for e in EVENTS}
    ads = {e: 0 for e in EVENTS}

    # All traffic
    resp = _run(client, property_id, start_date, end_date, ["eventName"])
    for row in resp.rows:
        name = row.dimension_values[0].value
        if name in totals:
            totals[name] = int(row.metric_values[0].value)

    # Ads only
    resp = _run(
        client, property_id, start_date, end_date, ["eventName", "sessionSourceMedium"]
    )
    for row in resp.rows:
        name = row.dimension_values[0].value
        src = row.dimension_values[1].value
        if name in ads and src == ADS_SOURCE_MEDIUM:
            ads[name] += int(row.metric_values[0].value)

    return {
        "range": {"from": start_date, "to": end_date},
        "events": totals,
        "events_ads": ads,
    }


if __name__ == "__main__":
    print(json.dumps(fetch(), indent=2, ensure_ascii=False))
