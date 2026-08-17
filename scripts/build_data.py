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
    # The range label is a claim about the rows directly under it. It was a
    # literal ("7/22–27") and went on asserting that long after the rows had
    # moved on, so it is derived now.
    st["range_ja"] = f"クリックが付いた語・{_short_range(ads['range'])}"
    st["range_en"] = f"terms with clicks · {_short_range(ads['range'])}"


def _short_range(rng):
    """{'from':'2026-07-17','to':'2026-07-30'} -> '7/17–7/30'"""
    a = datetime.strptime(rng["from"], "%Y-%m-%d")
    b = datetime.strptime(rng["to"], "%Y-%m-%d")
    return f"{a.month}/{a.day}–{b.month}/{b.day}"


def apply_cv_detail(data, cv):
    """
    Replace the ad-conversion detail table and everything that describes it.

    This whole block used to be hand-maintained, which is why it froze at 7/27
    while the KPIs above it kept moving — the page showed 9 conversions and then
    explained 6. Every field here is derived, so it cannot drift again.

    data.json may carry a 'cv_overrides' list to re-attach knowledge GA4 does
    not have (booking numbers, exact minutes from TableCheck). Each entry is
    {"match": {"when": "7/24 19", "event": "reserve_success"}, "set": {...}}
    and is applied last. Overrides only decorate a row that still exists; they
    can never resurrect one the data no longer supports.
    """
    rows = cv["conversions"]

    for ov in data.get("cv_overrides", []):
        m = ov.get("match", {})
        for r in rows:
            if all(r.get(k) == v for k, v in m.items()):
                r.update(ov.get("set", {}))

    data["conversions"] = rows
    data["conversions_total"] = cv["conversions_total"]
    data["cv_queries"] = cv["cv_queries"]
    data["cv_inside"] = cv["cv_inside"]

    s = cv["summary"]
    rng = _short_range(cv["range"])
    data["conversions_head"] = {
        "sub_ja": f"{rng}・広告(google/cpc)由来の全{s['events']}件。"
                  "「どの言葉で検索した人が・いつ・どこで・どうなったか」（GA4＋Google広告 実測）",
        "sub_en": f"{rng} · all {s['events']} ad-driven conversions — which search term, "
                  "when, where, and what became of it (GA4 + Google Ads, verified)",
    }
    data["cv_inside_head"] = {
        "ja": f"「{s['events']}コンバージョン」の中身 — 成約{s['bookings']}件と、"
              f"残り{s['events'] - s['bookings']}件の正体",
        "en": f"Inside the \"{s['events']} conversions\" — {s['bookings']} booked, "
              f"and what the other {s['events'] - s['bookings']} really are",
    }

    # The KPI subtitle is the same claim in miniature. Derive it too.
    ad_cv = data.setdefault("kpi", {}).setdefault("ad_cv", {})
    ad_cv["note_ja"] = (f"うち<b>実予約{s['bookings']}件</b>・惜しい離脱{s['near_misses']}人")
    ad_cv["note_en"] = (f"<b>{s['bookings']} real booking(s)</b> · {s['near_misses']} near-miss(es)")


def mark_partial_day(data, end_date):
    """
    Flag the in-progress day.

    Deliberately a flag on the row, not a note in `cvd`: apply_ads() carries
    human cvd annotations forward by date, so a '集計中' written there would
    survive into tomorrow and label a finished night as still counting.
    A flag is recomputed from scratch every run and cannot go stale.
    """
    d = datetime.strptime(end_date, "%Y-%m-%d")
    for r in data.get("daily", []):
        if r.get("partial") and r.get("date") != end_date:
            del r["partial"]          # yesterday's night is over now
        if r.get("date") == end_date:
            r["partial"] = True

    hdr = data.setdefault("header", {})
    hdr["partial_ja"] = f"{d.month}/{d.day} は集計中"
    hdr["partial_en"] = f"{d.month}/{d.day} still counting"


def fmt_period(start, end):
    """'2026-07-17', '2026-07-28' -> '2026/07/17 – 07/28'"""
    s = datetime.strptime(start, "%Y-%m-%d")
    e = datetime.strptime(end, "%Y-%m-%d")
    return f"{s:%Y/%m/%d} – {e:%m/%d}"


def main():
    data = load()
    now = datetime.now(JST)
    # Include today. The window used to stop at yesterday, which meant the
    # 20:00 JST run reported a night that had already ended and today never
    # appeared until the following evening — the dashboard was structurally a
    # day behind. Today's figures are real but incomplete (the night is still
    # running, and GA4 can lag a few hours), so the last row is labelled
    # 集計中 rather than presented as final.
    end_date = str(now.date())
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
    ads = None
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

    # ---------- local actions (Google Business Profile / Maps) ----------
    # Added 2026-08-17, after the location asset was linked on 08-10. Rides on
    # the same Ads credential, so it only runs when the developer token is
    # present. It lands in its own key on purpose: these are not reservations
    # and not what bidding optimises for, and folding them into any CV figure
    # would overstate performance several-fold.
    if os.environ.get("GOOGLE_ADS_DEVELOPER_TOKEN"):
        try:
            from fetch_local_actions import fetch as fetch_local

            la = fetch_local(start_date=CAMPAIGN_START, end_date=end_date)
            data["local_actions"] = la
            set_source(data, "local_actions", "ok", end_date)
            print(f"[local_actions] ok — {la['total_all']} all-conv "
                  f"across {len(la['rows'])} action(s), "
                  f"{la['total_counted']} of them inside the bidding CV count")
        except Exception:
            failures.append("local_actions")
            set_source(data, "local_actions", "failed", None)
            print("[local_actions] FAILED", file=sys.stderr)
            traceback.print_exc()

    # ---------- conversion detail (GA4, with an Ads fallback for the keyword) ----------
    # Runs after Ads so it can borrow converting_terms_by_date. It degrades to
    # GA4-only if Ads failed: the rows are still correct, some keywords just
    # read (not set) instead of being recovered.
    try:
        from fetch_cv_detail import fetch as fetch_cv

        cv = fetch_cv(
            start_date=CAMPAIGN_START,
            end_date=end_date,
            ads_hint=(ads or {}).get("converting_terms_by_date"),
        )
        apply_cv_detail(data, cv)
        set_source(data, "cv_detail", "ok", end_date)
        print(f"[cv_detail] ok — {cv['summary']}")
    except Exception:
        failures.append("cv_detail")
        set_source(data, "cv_detail", "failed", None)
        print("[cv_detail] FAILED", file=sys.stderr)
        traceback.print_exc()

    # ---------- meta ----------
    meta = data.setdefault("meta", {})
    meta["generated_at"] = now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta["generated_by"] = "github-actions"
    meta["run_status"] = "failed" if len(failures) >= 2 else ("partial" if failures else "ok")
    # cv_detail rides on the GA4 credential, so a GA4 outage takes both. That
    # is one root cause, not two — don't let it read as a total failure.
    if set(failures) == {"ga4", "cv_detail"}:
        meta["run_status"] = "partial"

    hdr = data.setdefault("header", {})
    hdr["updated"] = now.strftime("%Y/%m/%d %H:%M")

    # The last day in the window is today, and today is not over. Say so, in
    # the two places a reader could otherwise mistake it for a finished night:
    # the period label and the final row of the daily table.
    mark_partial_day(data, end_date)

    # The header period is a claim about the figures shown on the page, so it
    # may only advance once the sources those figures come from have actually
    # reached end_date. If Ads is still hand-entered, advancing would assert
    # coverage the KPIs do not have.
    #
    # Only these two feed displayed numbers. TableCheck is deliberately
    # excluded: it is a reservation cross-check, and it stays 'manual' until
    # Booking v1 access arrives — gating on it would freeze the period forever.
    PERIOD_SOURCES = ("ga4", "google_ads", "cv_detail")
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
