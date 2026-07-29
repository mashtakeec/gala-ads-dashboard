"""
Build data.json for the GALA ads dashboard.

Design rules (from 要件定義 v1.0):
  - MERGE, never overwrite. Sections this script cannot source are left
    exactly as they are, so human-written commentary survives every run.
  - A failed source is recorded as failed. It must never leave stale
    numbers looking current — index.html renders a warning from meta.
  - Partial success still publishes. Losing GA4 must not cost us the
    Ads data, and vice versa.
  - Exit 0 unless the file itself could not be written. A source outage
    is a normal, reportable state, not a crash.
"""

import json
import os
import sys
import traceback
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
DATA_PATH = os.environ.get("DATA_PATH", "data.json")
CAMPAIGN_START = os.environ.get("CAMPAIGN_START", "2026-07-17")


def load():
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


def save(data):
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def set_source(data, name, status, as_of=None, note=None):
    src = data.setdefault("meta", {}).setdefault("sources", {})
    entry = src.setdefault(name, {})
    entry["status"] = status
    entry["as_of"] = as_of
    if note:
        entry["note"] = note
    elif "note" in entry:
        del entry["note"]


def apply_ga4(data, ga4):
    """Map GA4 event counts onto the funnel and goals panels."""
    ev = ga4["events"]
    ads = ga4["events_ads"]

    # Funnel — all traffic
    for row in data.get("funnel", []):
        if row["ev"] in ev:
            row["v"] = str(ev[row["ev"]])

    # Goals A/B/C — all traffic / of which ads
    for row in data.get("goals", []):
        name = row["ev"]
        if name in ev:
            row["all"] = str(ev[name])
            row["ads"] = str(ads.get(name, 0))
            # Grey out a zero, colour a non-zero. Same rule the page used
            # when a human maintained it.
            row["ads_color"] = "var(--good)" if ads.get(name,
                                                        0) > 0 else "var(--dim)"


def fmt_period(start, end):
    """'2026-07-17', '2026-07-28' -> '2026/07/17 – 07/28'"""
    s = datetime.strptime(start, "%Y-%m-%d")
    e = datetime.strptime(end, "%Y-%m-%d")
    return f"{s:%Y/%m/%d} – {e:%m/%d}"


def main():
    data = load()
    now = datetime.now(JST)
    end_date = str((now - timedelta(days=1)).date())
    failures = []

    # ---------- GA4 ----------
    try:
        from fetch_ga4 import fetch as fetch_ga4

        ga4 = fetch_ga4(start_date=CAMPAIGN_START, end_date=end_date)
        apply_ga4(data, ga4)
        set_source(data, "ga4", "ok", ga4["range"]["to"])
        print(f"[ga4] ok — {ga4['events']}")
    except Exception:
        failures.append("ga4")
        set_source(data, "ga4", "failed", None)
        print("[ga4] FAILED", file=sys.stderr)
        traceback.print_exc()

    # ---------- Google Ads ----------
    # Not wired yet: no developer token. Left as 'manual' so the dashboard
    # does not flag it as broken — those numbers are still hand-entered and
    # are genuinely current as of whenever a human last touched them.
    if os.environ.get("GOOGLE_ADS_DEVELOPER_TOKEN"):
        try:
            from fetch_ads import fetch as fetch_ads

            ads = fetch_ads(end_date=end_date)
            data.update(ads)  # fetch_ads returns the sections it owns
            set_source(data, "google_ads", "ok", end_date)
            print("[ads] ok")
        except Exception:
            failures.append("google_ads")
            set_source(data, "google_ads", "failed", None)
            print("[ads] FAILED", file=sys.stderr)
            traceback.print_exc()
    else:
        # Honest labelling: these numbers are real but hand-entered, and their
        # as_of is whenever a human last edited them — not today.
        set_source(
            data, "google_ads", "manual",
            data.get("meta", {}).get("sources", {}).get(
                "google_ads", {}).get("as_of"),
            note="hand-entered; awaiting Google Ads developer token",
        )
        print("[ads] skipped — no developer token yet, leaving manual figures")

    # ---------- meta ----------
    meta = data.setdefault("meta", {})
    meta["generated_at"] = now.astimezone(
        timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta["generated_by"] = "github-actions"
    meta["run_status"] = "failed" if len(
        failures) >= 2 else ("partial" if failures else "ok")

    hdr = data.setdefault("header", {})
    hdr["updated"] = now.strftime("%Y/%m/%d %H:%M")

    # The header period is a claim about ALL the figures on the page, so it may
    # only advance when every source has actually reached end_date. While the
    # Ads numbers are hand-entered ('manual'), advancing it would assert
    # coverage the ad figures do not have — the page would silently claim a
    # period its own KPIs stop short of.
    all_current = not failures and all(
        s.get("status") == "ok" for s in meta.get("sources", {}).values()
    )
    if all_current:
        hdr["period"] = fmt_period(CAMPAIGN_START, end_date)

    save(data)
    print(f"wrote {DATA_PATH} — run_status={meta['run_status']}")

    # Non-zero only tells CI "something is wrong"; the file is already
    # written and publishable either way.
    return 0


if __name__ == "__main__":
    sys.exit(main())
