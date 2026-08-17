"""
Local actions (Google Business Profile / Maps) for the GALA ads dashboard.

Why this is its own section, and its own file:

`metrics.conversions` — the figure every KPI on this dashboard is built from —
counts only conversion actions that are Primary *and* sit inside a conversion
goal the campaign has actually selected. The Google-hosted local actions that
appeared after the location asset was linked on 2026-08-10 (Directions, Other
engagements, Menu views, Website visits, Orders) live in goals no campaign
uses, so their absence from that figure is correct, not a bug.

They are still worth reporting — they are the only read we have on the Business
Profile. But a route-planning tap is not a VIP reservation, and the moment the
two are summed the dashboard overstates performance several-fold. So they are
fetched separately, rendered in their own table, and shown next to a column
that states how many of them reached the bidding CV count (expected: zero).

Read-only. One API operation.
"""

import json
import os
from datetime import date

from fetch_ads import _client

# Categories that are local by definition, whatever Google named the action.
LOCAL_CATEGORIES = {"GET_DIRECTIONS", "STORE_VISIT", "STORE_SALE"}

# Google names these actions in English regardless of account language.
LOCAL_LABELS = {
    "directions": ("ルート・乗換案内", "Directions"),
    "other engagements": ("その他のエンゲージメント", "Other engagements"),
    "menu views": ("メニュー閲覧", "Menu views"),
    "website visits": ("ウェブサイト訪問", "Website visits"),
    "orders": ("注文（決済手続きの開始）", "Orders"),
    "calls": ("電話（マップ経由）", "Calls from Maps"),
    "bookings": ("予約（マップ経由）", "Bookings from Maps"),
}


def _is_local(name, category):
    return name.lower().startswith("local actions") or category in LOCAL_CATEGORIES


def _label(name):
    """'Local actions - Directions' -> ('ルート・乗換案内', 'Directions')."""
    suffix = name.split("-", 1)[1].strip() if "-" in name else name
    return LOCAL_LABELS.get(suffix.lower(), (suffix, suffix))


def fetch(start_date=None, end_date=None, customer_id=None):
    """
    Returns:
      rows            local actions, each {name, category, label_ja, label_en,
                      all, counted}, biggest first
      total_all       sum of all_conversions across local actions
      total_counted   how many of those reached metrics.conversions — the
                      number the KPI panel shows. Anything above 0 means a
                      local action has entered bidding and should be reviewed.
      account_all / account_counted   the same two totals across every action,
                      so the local share is readable without a second query.
    """
    customer_id = (
        customer_id or os.environ.get("GOOGLE_ADS_CUSTOMER_ID", "2138197168")
    ).replace("-", "")
    start_date = start_date or os.environ.get("CAMPAIGN_START", "2026-07-17")
    end_date = end_date or str(date.today())

    svc = _client().get_service("GoogleAdsService")

    # Segmenting by conversion action makes delivery metrics invalid, so this
    # query asks for nothing but the two conversion counts.
    q = f"""
        SELECT segments.conversion_action_name,
               segments.conversion_action_category,
               metrics.all_conversions,
               metrics.conversions
        FROM customer
        WHERE segments.date BETWEEN '{start_date}' AND '{end_date}'
    """

    agg = {}
    for row in svc.search(customer_id=customer_id, query=q):
        name = row.segments.conversion_action_name
        cat = getattr(
            row.segments.conversion_action_category,
            "name",
            str(row.segments.conversion_action_category),
        )
        e = agg.setdefault(
            name, {"name": name, "category": cat, "all": 0.0, "counted": 0.0}
        )
        e["all"] += row.metrics.all_conversions
        e["counted"] += row.metrics.conversions

    local, other = [], []
    for e in agg.values():
        e["all"] = round(e["all"])
        e["counted"] = round(e["counted"])
        # An action with no activity in the window is noise, not a zero worth
        # printing — unlike a calendar day, it has no fixed slot in the table.
        if not e["all"] and not e["counted"]:
            continue
        if _is_local(e["name"], e["category"]):
            e["label_ja"], e["label_en"] = _label(e["name"])
            local.append(e)
        else:
            other.append(e)

    local.sort(key=lambda r: -r["all"])
    other.sort(key=lambda r: -r["all"])

    return {
        "rows": local,
        "total_all": sum(r["all"] for r in local),
        "total_counted": sum(r["counted"] for r in local),
        "account_all": sum(r["all"] for r in local + other),
        "account_counted": sum(r["counted"] for r in local + other),
        "range": {"from": start_date, "to": end_date},
    }


if __name__ == "__main__":
    print(json.dumps(fetch(), indent=2, ensure_ascii=False))
