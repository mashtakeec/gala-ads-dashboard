"""
Build the ad-conversion detail table from GA4: keyword x hour x where x outcome.

This is the section the dashboard used to keep by hand, which is why it froze
at 7/27 while everything above it moved on. Nothing here is interpretation --
every field is derived from a GA4 row or a Google Ads row, so it can run nightly.

Two GA4 reports, deliberately:

  A. dateHour x eventName x pageLocation   -> the authoritative row set.
  B. dateHour x eventName x sessionGoogleAdsQuery -> the keyword, where GA4 has it.

They are separate because adding the Ads-query dimension silently DROPS rows
whose query is null -- which is exactly the TableCheck-domain events, i.e. the
completed bookings. Report A must stay query-free or the booking disappears.
The keyword is then joined back on (hour, event), falling back to Google Ads.

Read-only. Raising is fine: build_data.py catches it and marks the source
failed rather than republishing yesterday's table as if it were today's.
"""

import json
import os
import re
from datetime import date, datetime, timedelta

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Filter,
    FilterExpression,
    FilterExpressionList,
    Metric,
    RunReportRequest,
)
from google.oauth2 import service_account

SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]
ADS_SOURCE_MEDIUM = "google / cpc"
NOT_SET = {"(not set)", "", "(none)", "(direct)"}

# Every event Google Ads can count as a conversion for this account.
# Order controls display order within an hour.
CV_EVENTS = [
    "reserve_success",
    "form_submit",
    "vip_booking_start",
    "phone_tap",
    "whatsapp_tap",
]

RESERVATION_RE = re.compile(r"/reservations/([A-Za-z0-9]+)")


def _client():
    raw = os.environ.get("GOOGLE_SA_KEY")
    if not raw:
        raise RuntimeError("GOOGLE_SA_KEY is not set")
    creds = service_account.Credentials.from_service_account_info(
        json.loads(raw), scopes=SCOPES
    )
    return BetaAnalyticsDataClient(credentials=creds)


def _ads_only(extra=None):
    """sessionSourceMedium == 'google / cpc', optionally ANDed with more."""
    terms = [
        FilterExpression(
            filter=Filter(
                field_name="sessionSourceMedium",
                string_filter=Filter.StringFilter(value=ADS_SOURCE_MEDIUM),
            )
        )
    ]
    if extra:
        terms.extend(extra)
    return FilterExpression(and_group=FilterExpressionList(expressions=terms))


def _event_in_list():
    return FilterExpression(
        filter=Filter(
            field_name="eventName",
            in_list_filter=Filter.InListFilter(values=CV_EVENTS),
        )
    )


def _run(client, prop, start, end, dims):
    req = RunReportRequest(
        property=f"properties/{prop}",
        date_ranges=[DateRange(start_date=start, end_date=end)],
        dimensions=[Dimension(name=d) for d in dims],
        metrics=[Metric(name="eventCount")],
        dimension_filter=_ads_only([_event_in_list()]),
        limit=100000,
    )
    return client.run_report(req)


# ---------------------------------------------------------------- presentation


def _where(page_url):
    """
    Turn a page URL into the 'where it happened' cell.

    Returns (where_ja, where_en, tag, reservation_id_or_None).
    """
    u = page_url or ""
    short = re.sub(r"^https?://", "", u).split("?")[0].split("#")[0].rstrip("/")
    host = short.split("/")[0]

    if "tablecheck" in host:
        m = RESERVATION_RE.search(short)
        if m:
            return "TableCheck 予約確定ページ", "TableCheck confirmation page", short, m.group(1)
        if "sign_in" in short or "sign-in" in short:
            return "TableCheck サインイン", "TableCheck sign-in", short, None
        return "TableCheck", "TableCheck", short, None

    if "book.gala-resort" in host:
        return "VIP LP", "VIP LP", host, None

    return host or "—", host or "—", short, None


def _is_brand(term):
    t = (term or "").lower()
    return "gala" in t or "ガラ" in t or "ｶﾞﾗ" in t


def _hour_label(datehour):
    """'2026072419' -> ('7/24 19', '2026-07-24', 19)"""
    dt = datetime.strptime(datehour, "%Y%m%d%H")
    return f"{dt.month}/{dt.day} {dt.hour:02d}", dt.strftime("%Y-%m-%d"), dt.hour


# ---------------------------------------------------------------------- fetch


def fetch(property_id=None, start_date=None, end_date=None, ads_hint=None):
    """
    ads_hint: {"2026-07-24": ["nightclub gala resort"], ...}
        Converting search terms per date, from Google Ads. Used only when GA4
        has no query for a row -- which is the normal case for events that fire
        on the TableCheck domain. Applied only when the date has exactly one
        converting term, so it can never invent an attribution.

    Returns the sections this module owns:
        conversions / conversions_total / cv_queries / cv_inside
        summary {bookings, near_misses, events, terms}
        range
    """
    property_id = property_id or os.environ.get("GA4_PROPERTY_ID", "383604323")
    start_date = start_date or os.environ.get("CAMPAIGN_START", "2026-07-17")
    end_date = end_date or str(date.today() - timedelta(days=1))
    ads_hint = ads_hint or {}

    client = _client()

    # ---- A. rows (query-free, so TableCheck-domain events survive) ----
    raw = []
    resp = _run(client, property_id, start_date, end_date, ["dateHour", "eventName", "pageLocation"])
    for row in resp.rows:
        dh, ev, page = (v.value for v in row.dimension_values)
        raw.append({"dh": dh, "ev": ev, "page": page, "n": int(row.metric_values[0].value)})

    # ---- B. keyword map ----
    kw_by_hour_event = {}
    kw_by_hour = {}
    resp = _run(client, property_id, start_date, end_date, ["dateHour", "eventName", "sessionGoogleAdsQuery"])
    for row in resp.rows:
        dh, ev, q = (v.value for v in row.dimension_values)
        if q in NOT_SET:
            continue
        kw_by_hour_event.setdefault((dh, ev), q)
        kw_by_hour.setdefault(dh, q)

    def keyword_for(dh, ev, day):
        q = kw_by_hour_event.get((dh, ev))
        if q:
            return q, None, None
        q = kw_by_hour.get(dh)
        if q:
            return q, "※同時刻の広告セッションより", "※from the same hour's ad session"
        cands = ads_hint.get(day) or []
        if len(cands) == 1:
            return cands[0], "※Google広告で確定", "※confirmed in Google Ads"
        return "(not set)", None, None

    # ---- classify ----
    # A vip_booking_start in the same hour as a completed booking is the
    # booker's own step, not a drop. Anything else that starts and never
    # completes in that hour is a genuine near-miss.
    success_hours = {r["dh"] for r in raw if r["ev"] == "reserve_success"}

    rows = []
    bookings = set()
    near_misses = 0
    icon_count = {"✅": 0, "🔵": 0, "🟡": 0, "📞": 0, "💬": 0}
    what_count = {}
    terms = {}
    total_n = 0

    raw.sort(key=lambda r: (r["dh"], CV_EVENTS.index(r["ev"]) if r["ev"] in CV_EVENTS else 99))

    for r in raw:
        ev, dh, n = r["ev"], r["dh"], r["n"]
        when, day, _ = _hour_label(dh)
        w_ja, w_en, w_tag, res_id = _where(r["page"])
        kw, kw_tag_ja, kw_tag_en = keyword_for(dh, ev, day)
        total_n += n

        row = {
            "when": when,
            "hour": True,
            "date": day,
            "event": ev,
            "kw": kw,
            "where_ja": w_ja,
            "where_en": w_en,
            "where_tag": w_tag,
            "n": str(n),
        }
        if kw_tag_ja:
            row["kw_tag_ja"] = kw_tag_ja
            row["kw_tag_en"] = kw_tag_en

        if ev == "reserve_success":
            if res_id:
                bookings.add(res_id)
            else:
                bookings.add(dh)
            row.update(
                cls="peak", icon="✅",
                what_bold="予約完了", what_bold_en="Reservation completed",
                what_bold_color="var(--good)", what_tag="reserve_success",
                out_color="var(--good)", out_ja="成約", out_en="BOOKED",
            )
            if n > 1:
                row["what_tag_ja"] = f"・実質{1}予約({n}回発火)"
                row["what_tag_en"] = f" · 1 real booking ({n} fires)"
                row["out_tag_ja"] = "2件目以降は二重計測"
                row["out_tag_en"] = "extra fires = double-count"
            icon_count["✅"] += n
            what_count["完了"] = what_count.get("完了", 0) + n

        elif ev == "form_submit":
            row.update(
                cls="peak", icon="🔵",
                what_bold="連絡先", what_bold_en="Contact",
                what_tag="form_submit",
                what_tag_ja="＝予約フローのサインイン", what_tag_en=" = booking sign-in",
                out_color="var(--info)",
                out_ja="成約者の途中工程" if dh in success_hours else "サインイン到達",
                out_en="booker's mid-step" if dh in success_hours else "reached sign-in",
            )
            if dh in success_hours:
                row["out_tag_ja"] = "別客ではない"
                row["out_tag_en"] = "not a separate guest"
            icon_count["🔵"] += n
            what_count["サインイン"] = what_count.get("サインイン", 0) + n

        elif ev == "vip_booking_start":
            dropped = dh not in success_hours
            row.update(
                cls="zero" if dropped else "",
                icon="🟡" if dropped else "🔵",
                what_ja="予約開始", what_en="Booking started",
                what_tag="vip_booking_start",
                out_color="var(--warn)" if dropped else "var(--info)",
                out_ja="あと一歩・離脱" if dropped else "成約者の途中工程",
                out_en="near-miss, dropped" if dropped else "booker's mid-step",
                out_tag_ja="TableCheckで完了せず" if dropped else "別客ではない",
                out_tag_en="never completed" if dropped else "not a separate guest",
            )
            if dropped:
                near_misses += n
                icon_count["🟡"] += n
            else:
                icon_count["🔵"] += n
            what_count["開始"] = what_count.get("開始", 0) + n

        elif ev == "phone_tap":
            row.update(
                cls="", icon="📞",
                what_bold="電話タップ", what_bold_en="Phone tap", what_tag="phone_tap",
                out_color="var(--info)", out_ja="実通話は未計測", out_en="call not measured",
            )
            icon_count["📞"] += n
            what_count["電話"] = what_count.get("電話", 0) + n

        elif ev == "whatsapp_tap":
            row.update(
                cls="", icon="💬",
                what_bold="WhatsApp", what_bold_en="WhatsApp", what_tag="whatsapp_tap",
                out_color="var(--info)", out_ja="問い合わせ開始", out_en="inquiry started",
            )
            icon_count["💬"] += n
            what_count["WhatsApp"] = what_count.get("WhatsApp", 0) + n

        if kw not in NOT_SET:
            terms[kw] = terms.get(kw, 0) + n
        rows.append(row)

    # ---- footer ----
    n_terms = len(terms)
    brand = sum(1 for t in terms if _is_brand(t))
    if n_terms and brand == n_terms:
        kw_ja = f"計{n_terms}語（すべて指名検索）"
        kw_en = f"{n_terms} terms (all brand)"
    else:
        kw_ja = f"計{n_terms}語（指名{brand}・一般{n_terms - brand}）"
        kw_en = f"{n_terms} terms ({brand} brand / {n_terms - brand} generic)"

    order = ["完了", "サインイン", "開始", "電話", "WhatsApp"]
    order_en = {"完了": "completed", "サインイン": "sign-in", "開始": "starts",
                "電話": "phone", "WhatsApp": "WhatsApp"}
    what_ja = "・".join(f"{k}{what_count[k]}" for k in order if what_count.get(k))
    what_en = " · ".join(f"{what_count[k]} {order_en[k]}" for k in order if what_count.get(k))

    out_parts = [f"{i}{c}" for i, c in icon_count.items() if c]
    out_ja = " ／ ".join(out_parts)

    conversions_total = {
        "kw_ja": kw_ja, "kw_en": kw_en,
        "what_ja": what_ja or "—", "what_en": what_en or "—",
        "out_ja": out_ja or "—", "out_en": out_ja or "—",
        "n": str(total_n),
    }

    # ---- cv_queries: which terms produced conversions ----
    cv_queries = [
        {
            "term": t,
            "n": str(c),
            "pill_ja": "指名" if _is_brand(t) else "一般",
            "pill_en": "brand" if _is_brand(t) else "generic",
        }
        for t, c in sorted(terms.items(), key=lambda kv: -kv[1])
    ]

    # ---- cv_inside: the same rows, read as sentences ----
    cv_inside = []
    if bookings:
        cv_inside.append({
            "icon": "✅", "bold": True,
            "t_ja": f"成約 {len(bookings)}件", "t_en": f"{len(bookings)} BOOKED",
            "tag": "reserve_success",
            "v_ja": "TableCheck 予約確定ページまで到達",
            "v_en": "reached the TableCheck confirmation page",
        })
    for r in rows:
        if r["event"] == "vip_booking_start" and r["icon"] == "🟡":
            cv_inside.append({
                "icon": "🟡",
                "t_ja": "予約開始→離脱", "t_en": "booking-start → dropped",
                "tag_ja": f"{r['when']}時", "tag_en": f"{r['when']}h",
                "v_ja": f"「{r['kw']}」で来訪→予約ボタンまで→完了せず",
                "v_en": f"via \"{r['kw']}\" → reached booking button → never completed",
            })
    for r in rows:
        if r["event"] == "reserve_success" and int(r["n"]) > 1:
            cv_inside.append({
                "icon": "⚪",
                "t_ja": f"reserve_success の重複発火 {int(r['n']) - 1}件",
                "t_en": f"{int(r['n']) - 1} duplicate reserve_success fire(s)",
                "tag": r["when"],
                "v_ja": "同じ予約の二重計測。新しい客ではない",
                "v_en": "double-count of the same booking — not a new guest",
            })

    return {
        "conversions": rows,
        "conversions_total": conversions_total,
        "cv_queries": cv_queries,
        "cv_inside": cv_inside,
        "summary": {
            "bookings": len(bookings),
            "near_misses": near_misses,
            "events": total_n,
            "terms": n_terms,
        },
        "range": {"from": start_date, "to": end_date},
    }


if __name__ == "__main__":
    print(json.dumps(fetch(), indent=2, ensure_ascii=False))
