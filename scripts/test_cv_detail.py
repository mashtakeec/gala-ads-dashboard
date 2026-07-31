"""
Offline check for fetch_cv_detail: no credentials, no network.

Feeds the module a hand-built GA4 response that reproduces the 7/17-27 window
we already reconciled by hand (6 events, 4 people, one booking double-fired)
plus a later day, and asserts the derived table says what a human said it said.
If this passes, the automated table is trustworthy on known ground.

Run: python scripts/test_cv_detail.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fetch_cv_detail as M


class _V:
    def __init__(self, v): self.value = v


class _Row:
    def __init__(self, dims, n):
        self.dimension_values = [_V(d) for d in dims]
        self.metric_values = [_V(str(n))]


class _Resp:
    def __init__(self, rows): self.rows = rows


LP = "https://book.gala-resort.jp/"
SIGNIN = "https://www.tablecheck.com/en/users/sign_in"
CONFIRM = "https://www.tablecheck.com/reservations/FUCQX2"

# dateHour x eventName x pageLocation  (report A)
ROWS_A = [
    (["2026071823", "vip_booking_start", LP], 1),
    (["2026071900", "vip_booking_start", LP], 1),
    (["2026072419", "form_submit", SIGNIN], 1),
    (["2026072419", "reserve_success", CONFIRM], 2),
    (["2026072422", "vip_booking_start", LP], 1),
]

# dateHour x eventName x sessionGoogleAdsQuery  (report B)
# Note the TableCheck-domain events are absent — that is the real behaviour
# this design exists to survive.
ROWS_B = [
    (["2026071823", "vip_booking_start", "the pink osaka"], 1),
    (["2026071900", "vip_booking_start", "nightclub gala resort"], 1),
    (["2026072422", "vip_booking_start", "nightclub gala resort"], 1),
]


def fake_run(client, prop, start, end, dims):
    src = ROWS_A if "pageLocation" in dims else ROWS_B
    return _Resp([_Row(d, n) for d, n in src])


def main():
    M._client = lambda: object()
    M._run = fake_run

    out = M.fetch(
        property_id="X",
        start_date="2026-07-17",
        end_date="2026-07-27",
        ads_hint={"2026-07-24": ["nightclub gala resort"]},
    )

    s = out["summary"]
    rows = out["conversions"]
    fail = []

    def check(label, got, want):
        if got != want:
            fail.append(f"  {label}: got {got!r}, want {want!r}")

    check("events", s["events"], 6)
    check("bookings", s["bookings"], 1)
    check("near_misses", s["near_misses"], 3)
    check("rows", len(rows), 5)
    check("footer n", out["conversions_total"]["n"], "6")
    check("footer outcome", out["conversions_total"]["out_ja"], "✅2 ／ 🔵1 ／ 🟡3")

    booking = [r for r in rows if r["event"] == "reserve_success"][0]
    check("booking keyword recovered from Ads", booking["kw"], "nightclub gala resort")
    check("booking where", booking["where_ja"], "TableCheck 予約確定ページ")
    check("booking double-fire", booking["n"], "2")

    signin = [r for r in rows if r["event"] == "form_submit"][0]
    check("sign-in is the booker's own step", signin["out_ja"], "成約者の途中工程")

    drops = [r for r in rows if r["icon"] == "🟡"]
    check("three drops", len(drops), 3)
    check("first drop keyword", drops[0]["kw"], "the pink osaka")

    # Every row must carry the fields index.html reads, or the page renders
    # "undefined" instead of erroring — the worst possible failure mode.
    for i, r in enumerate(rows):
        for k in ("when", "kw", "icon", "out_color", "out_ja", "out_en", "n", "cls"):
            if k not in r:
                fail.append(f"  row {i} ({r.get('event')}) missing field {k!r}")
        if not (r.get("where") or (r.get("where_ja") and r.get("where_en"))):
            fail.append(f"  row {i} has no usable 'where'")
        if not (r.get("what_ja") or r.get("what_bold")):
            fail.append(f"  row {i} has no usable 'what'")

    if fail:
        print("FAIL")
        print("\n".join(fail))
        return 1

    print("PASS — 6 events / 4 people / 1 booking, reproduced from GA4 rows alone")
    print("  footer:", out["conversions_total"]["what_ja"], "|", out["conversions_total"]["out_ja"])
    print("  cv_queries:", [(q["term"], q["n"]) for q in out["cv_queries"]])
    return 0


if __name__ == "__main__":
    sys.exit(main())
