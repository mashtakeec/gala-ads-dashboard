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
            row["ads_color"] = "var(--good)" if ads.get(name, 0) > 0 else "var(--dim)"


def apply_ads(data, ads):
    """
    Map Google Ads figures onto the page.

    Merges field-by-field so human-authored copy survives:
      - kpi.*.note_* is only replaced when the fetch supplies one
      - kpi.completed is left alone (that number is a booking count, not an
        Ads metric)
      - daily rows keep their hand-written cvd / cvdEn annotations, matched
        by date. Those annotations are analysis ("✅成約1・🟡開始1"), not data.
    """
    # --- KPIs: update values, keep any note the fetch didn't supply ---
    for key, incoming in ads["kpi"].items():
        target = data.setdefault("kpi", {}).setdefault(key, {})
        for k, v in incoming.items():
            target[k] = v

    data["delivery"] = {**data.get("delivery", {}), **ads["delivery"]}

    # --- daily: preserve human annotations per date ---
    old_notes = {}
    for r in data.get("daily", []):
        # Old rows may predate the 'date' field; fall back to the display date.
        k = r.get("date") or r.get("d")
        if r.get("cvd") or r.get("cvdEn"):
            old_notes[k] = (r.get("cvd"), r.get("cvdEn"))

    for r in ads["daily"]:
        note = old_notes.get(r["date"]) or old_notes.get(r["d"])
        if note:
            if note[0]:
                r["cvd"] = note[0]
            if note[1]:
                r["cvdEn"] = note[1]
    data["daily"] = ads["daily"]
    data["daily_total"] = ads["daily_total"]

    # --- search terms: replace rows, keep the section's label/range copy ---
    st = data.setdefault("search_terms", {})
    st["rows"] = ads["search_terms_rows"]


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

            ads = fetch_ads(start_date=CAMPAIGN_START, end_date=end_date)
            apply_ads(data, ads)
            set_source(data, "google_ads", "ok", end_date)
            print(f"[ads] ok — spend={ads['kpi']['spend']['value']} cv={ads['kpi']['ad_cv']['value']}")
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
            data.get("meta", {}).get("sources", {}).get("google_ads", {}).get("as_of"),
            note="hand-entered; awaiting Google Ads developer token",
        )
        print("[ads] skipped — no developer token yet, leaving manual figures")

    # ---------- meta ----------
    meta = data.setdefault("meta", {})
    meta["generated_at"] = now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta["generated_by"] = "github-actions"
    meta["run_status"] = "failed" if len(failures) >= 2 else ("partial" if failures else "ok")

    hdr = data.setdefault("header", {})
    hdr["updated"] = now.strftime("%Y/%m/%d %H:%M")

    # The header period is a claim about the figures shown on the page, so it
    # may only advance once the sources those figures come from have actually
    # reached end_date. If Ads is still hand-entered, advancing would assert
    # coverage the KPIs do not have.
    #
    # Only these two feed displayed numbers. TableCheck is deliberately
    # excluded: it is a reservation cross-check, and it stays 'manual' until
    # Booking v1 access arrives — gating on it would freeze the period forever.
    PERIOD_SOURCES = ("ga4", "google_ads")
    srcs = meta.get("sources", {})
    if all(srcs.get(n, {}).get("status") == "ok" for n in PERIOD_SOURCES):
        hdr["period"] = fmt_period(CAMPAIGN_START, end_date)

    save(data)
    print(f"wrote {DATA_PATH} — run_status={meta['run_status']}")

    # Non-zero only tells CI "something is wrong"; the file is already
    # written and publishable either way.
    return 0


if __name__ == "__main__":
    sys.exit(main())
