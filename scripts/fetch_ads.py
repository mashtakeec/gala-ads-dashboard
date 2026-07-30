"""
Fetch Google Ads delivery + conversion figures for the GALA ads dashboard.

Read-only. Uses a service-account credential (supported without Workspace
domain-wide delegation since 2024-11-27) and Explorer access, which allows
~2,880 operations/day — this module uses 2.

Returns only the sections it owns. Human-written interpretation (the
conversion detail table, the "inside the 6 conversions" list, all callout
copy) is never touched — build_data.py merges, it does not overwrite.
"""

import json
import os
from datetime import date, datetime, timedelta

from google.ads.googleads.client import GoogleAdsClient
from google.oauth2 import service_account

SCOPES = ["https://www.googleapis.com/auth/adwords"]
API_VERSION = "v24"

WD_JA = ["月", "火", "水", "木", "金", "土", "日"]
WD_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
# For a nightclub, Thu–Sun is the commercial week. Drives the ③ filter.
WEEKEND_IDX = {3, 4, 5, 6}


def _client():
    raw = os.environ.get("GOOGLE_SA_KEY")
    token = os.environ.get("GOOGLE_ADS_DEVELOPER_TOKEN")
    if not raw:
        raise RuntimeError("GOOGLE_SA_KEY is not set")
    if not token:
        raise RuntimeError("GOOGLE_ADS_DEVELOPER_TOKEN is not set")
    creds = service_account.Credentials.from_service_account_info(
        json.loads(raw), scopes=SCOPES
    )
    # login_customer_id is deliberately omitted: the service account is added
    # directly to the GALA account, so the manager layer is not traversed.
    return GoogleAdsClient(
        credentials=creds, developer_token=token, version=API_VERSION
    )


def _yen(micros):
    """Ads returns money in micros (1/1,000,000 of the account currency)."""
    return round(micros / 1_000_000)


def _fmt_yen(v):
    return f"¥{v:,}"


def fetch(start_date=None, end_date=None, customer_id=None):
    """
    Returns the sections this module owns:
      kpi.spend / kpi.ad_cv / kpi.cost_per_cv
      delivery
      daily (raw rows — build_data.py preserves human cvd annotations)
      daily_total
      search_terms.rows
    """
    customer_id = (customer_id or os.environ.get("GOOGLE_ADS_CUSTOMER_ID", "2138197168")).replace("-", "")
    start_date = start_date or os.environ.get("CAMPAIGN_START", "2026-07-17")
    end_date = end_date or str(date.today() - timedelta(days=1))

    client = _client()
    svc = client.get_service("GoogleAdsService")

    # ---- 0. daily budget ----
    # Read the live budget rather than hardcoding it. Budgets get changed in the
    # Ads UI and a stale literal here would quietly misreport the plan.
    # Shared budgets are counted once, hence the dict keyed by resource name.
    budget_q = """
        SELECT campaign.name,
               campaign_budget.resource_name,
               campaign_budget.amount_micros
        FROM campaign
        WHERE campaign.status = 'ENABLED'
    """
    budgets = {}
    for row in svc.search(customer_id=customer_id, query=budget_q):
        budgets[row.campaign_budget.resource_name] = _yen(
            row.campaign_budget.amount_micros
        )
    daily_budget = sum(budgets.values()) if budgets else None

    # ---- 1. daily performance ----
    daily_q = f"""
        SELECT segments.date,
               metrics.impressions,
               metrics.clicks,
               metrics.cost_micros,
               metrics.conversions
        FROM customer
        WHERE segments.date BETWEEN '{start_date}' AND '{end_date}'
        ORDER BY segments.date
    """
    by_date = {}
    for row in svc.search(customer_id=customer_id, query=daily_q):
        by_date[row.segments.date] = {
            "impr": int(row.metrics.impressions),
            "clk": int(row.metrics.clicks),
            "cost": _yen(row.metrics.cost_micros),
            "cv": round(row.metrics.conversions),
        }

    # Fill every date in the window. A day with no delivery is a real zero and
    # must appear as a row — the Mon–Wed zeros are meaningful (schedule), not
    # missing data.
    daily = []
    d0 = datetime.strptime(start_date, "%Y-%m-%d").date()
    d1 = datetime.strptime(end_date, "%Y-%m-%d").date()
    tot_impr = tot_clk = tot_cost = tot_cv = 0

    cur = d0
    while cur <= d1:
        key = str(cur)
        m = by_date.get(key, {"impr": 0, "clk": 0, "cost": 0, "cv": 0})
        wd = cur.weekday()
        impr, clk, cost, cv = m["impr"], m["clk"], m["cost"], m["cv"]

        row = {
            "d": cur.strftime("%m/%d"),
            "date": key,                       # kept for merge matching
            "wd": WD_JA[wd],
            "wdEn": WD_EN[wd],
            "impr": impr,
            "clk": clk,
            "ctr": f"{clk / impr * 100:.2f}%" if impr else "—",
            "cost": _fmt_yen(cost),
            "cpc": _fmt_yen(round(cost / clk)) if clk else "—",
            "cv": cv,
            "type": "weekend" if wd in WEEKEND_IDX else "week",
        }
        if impr == 0:
            row["zero"] = True
        daily.append(row)

        tot_impr += impr
        tot_clk += clk
        tot_cost += cost
        tot_cv += cv
        cur += timedelta(days=1)

    # Mark the top-2 spend nights as peak, matching how the page reads today.
    for r in sorted(daily, key=lambda r: -int(r["cost"].replace("¥", "").replace(",", "")))[:2]:
        if r["cost"] != "¥0":
            r["peak"] = True

    # ---- 2. search terms ----
    st_q = f"""
        SELECT search_term_view.search_term,
               metrics.clicks,
               metrics.cost_micros,
               metrics.conversions
        FROM search_term_view
        WHERE segments.date BETWEEN '{start_date}' AND '{end_date}'
          AND metrics.clicks > 0
        ORDER BY metrics.clicks DESC
    """
    terms = []
    for row in svc.search(customer_id=customer_id, query=st_q):
        cv = round(row.metrics.conversions)
        t = {
            "term": row.search_term_view.search_term,
            "clicks": str(int(row.metrics.clicks)),
            "cost": _fmt_yen(_yen(row.metrics.cost_micros)),
            "cv": f"{cv} ✅" if cv else "0",
        }
        if cv:
            t["cls"] = "peak"
            t["bold"] = True
            t["cv_color"] = "var(--good)"
        terms.append(t)

    ctr = f"{tot_clk / tot_impr * 100:.2f}%" if tot_impr else "—"
    cpc = _fmt_yen(round(tot_cost / tot_clk)) if tot_clk else "—"
    days = (d1 - d0).days + 1

    if daily_budget:
        note_ja = f"{days}日間・日予算{_fmt_yen(daily_budget)}"
        note_en = f"{days} days · {_fmt_yen(daily_budget)}/day"
    else:
        # No enabled campaign to read a budget from — say so rather than
        # inventing a figure.
        note_ja = f"{days}日間"
        note_en = f"{days} days"

    return {
        "kpi": {
            "spend": {
                "value": _fmt_yen(tot_cost),
                "note_ja": note_ja,
                "note_en": note_en,
            },
            "ad_cv": {"value": str(tot_cv)},
            "cost_per_cv": {
                "value": _fmt_yen(round(tot_cost / tot_cv)) if tot_cv else "—",
                "note_ja": "費用 ÷ 広告CV",
                "note_en": "spend ÷ ad CV",
            },
        },
        "delivery": {
            "impressions": f"{tot_impr:,}",
            "clicks": f"{tot_clk:,}",
            "ctr": ctr,
            "cpc": cpc,
        },
        "daily": daily,
        "daily_total": {
            "impr": f"{tot_impr:,}",
            "clk": f"{tot_clk:,}",
            "ctr": ctr,
            "cost": _fmt_yen(tot_cost),
            "cpc": cpc,
            "cv": str(tot_cv),
        },
        "search_terms_rows": terms,
        "range": {"from": start_date, "to": end_date},
    }


if __name__ == "__main__":
    print(json.dumps(fetch(), indent=2, ensure_ascii=False))
