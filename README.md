# GALA RESORT — Ads & Reservations Dashboard

Static, single-page dashboard that visualizes Google Ads and GA4 data for the **GALA RESORT** nightclub campaign targeting inbound tourists (EN/ES) in Osaka.

Deployed on **Vercel** — refreshed manually on request (not auto-live).

## Features

- **Bilingual UI** — Japanese / English toggle (top-right button)
- **KPI tiles** — Cost, Clicks, CTR, CPC, Ad conversions, Reservations
- **True-goal cards** — Reservation complete, Phone tap, WhatsApp tap
- **Ad group breakdown** — Performance table with visual bars
- **Top search keywords** — Actual search terms ranked by impressions
- **Booking funnel** — reserve_form → vip_booking_start → form_submit → reserve_success
- **Interpretation notes** — Explains what each metric really means to prevent misreading

## Tech stack

| Layer   | Tool              |
|---------|-------------------|
| Markup  | Single `index.html` (vanilla HTML + CSS) |
| Hosting | Vercel (static)   |
| Data    | Google Ads 213-819-7168 · GA4 383604323 |

No build step, no dependencies — just a static HTML file.

## Updating the data

1. Open `index.html`
2. Update the hardcoded numbers (KPIs, funnel counts, keyword list, dates)
3. Commit, push, and Vercel auto-deploys

## Local preview

Open `index.html` in any browser. No server needed.

## Project info

- **Client**: GALA RESORT (Osaka)
- **Maintained by**: MASHTAKE / AI-BOW
