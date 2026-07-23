# Computer Warrior analytics boundary

Computer Warrior uses two separate, privacy-limited analytics sources. Neither
source belongs in D1, so visitor measurement does not compete with account or
XP-sync capacity.

## 1. Public website visitors: Cloudflare Web Analytics

Cloudflare Web Analytics is the source for:

- daily unique visitors;
- page views;
- top public pages;
- referrers;
- country and device-type aggregates; and
- Core Web Vitals and page-load performance.

It is cookie-free and is not enabled merely by deploying this repository. The
owner must create the site in **Cloudflare Dashboard → Analytics & Logs → Web
Analytics**, copy the generated beacon snippet, and replace the
`CLOUDFLARE_WEB_ANALYTICS` marker near the end of:

- `public/index.html`; and
- `public/privacy/index.html`.

Use the exact Cloudflare-generated snippet. Do not invent or commit a fake site
token. The token identifies the Web Analytics site but is not an application
secret.

After deployment, verify:

1. Open the public landing page in a private browser window.
2. In browser developer tools, confirm `beacon.min.js` loads successfully.
3. Confirm one page view appears in Cloudflare Web Analytics after processing.
4. Visit `/privacy/` and confirm it appears as a separate path.
5. Confirm no analytics cookie is created.

Cloudflare Web Analytics is intentionally not used for custom product events.

## 2. Backend product events: Workers Analytics Engine

The beta Worker has an optional `ANALYTICS` binding to the
`computer_warrior_product` dataset. The binding is absent locally, and all
writes are guarded so analytics can never break registration, device creation,
sync, or leaderboard settings.

The current allowlist is:

- `account_registered`;
- `login_succeeded`;
- `device_registered`;
- `xp_sync_accepted`;
- `leaderboard_enabled`; and
- `leaderboard_disabled`.

Each point has this fixed schema:

| Field | Meaning |
| --- | --- |
| `index1` / `blob1` | allowlisted event name |
| `blob2` | `local`, `beta`, `production`, or `unknown` |
| `blob3` | schema version `product-v1` |
| `double1` | event count (`1`) |
| `double2` | optional anonymous numeric value; currently accepted batch XP |

No free-form analytics dimension is accepted. This is deliberate: it prevents
a future call site from accidentally placing private data into the dataset.

The analytics dataset must never contain:

- username or email;
- account ID or device ID;
- device label;
- session or authentication token;
- IP address or user-agent;
- typed content, raw keys, coordinates, applications, websites, or raw input
  events.

## Querying product analytics

The example queries in `analytics-queries.sql` are for the Cloudflare Analytics
Engine SQL API. Use an owner-held API token with **Account Analytics Read**
permission. Never store that API token in the Worker, browser, Git repository,
or desktop app.

The first useful product report should show, by day:

- new beta accounts;
- successful sign-ins;
- registered devices;
- accepted sync batches;
- aggregate accepted XP volume; and
- leaderboard opt-ins and opt-outs.

Do not describe account registrations as website visitors. Daily visitors come
from Web Analytics; product events come from Analytics Engine.

## Retention and later rollups

Analytics Engine is the short-window operational product source. Before public
launch, add a scheduled owner-side rollup that writes only daily totals to a
separate reporting table if long-term history beyond the platform retention
window is required. A rollup should write a few rows per day, not one D1 row per
page view.

Newsletter subscriptions and public accounts are not analytics events. They
need explicit consent, purpose-specific storage, unsubscribe/deletion flows,
and their own access controls before they are launched.
