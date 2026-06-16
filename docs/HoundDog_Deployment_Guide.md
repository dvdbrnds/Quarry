# HoundDog Deployment Guide

Complete these steps in order. Each step depends on the one before it.

---

## Step 1: DNS Record

- [ ] Create an A record pointing to your Coolify server:
  - **Name:** `hounddog.moravian.edu` (or your chosen subdomain)
  - **Type:** A
  - **Value:** `10.232.1.50` (your Coolify server IP)
  - **TTL:** 300
- [ ] If internal/DMZ only, add to internal DNS. If public-facing, add to public DNS
- [ ] Wait for propagation (internal DNS is usually instant)
- [ ] Set this domain on the HoundDog app in Coolify under the "Domains" or "FQDN" field
- [ ] Coolify will auto-provision SSL via Let's Encrypt once DNS resolves

---

## Step 2: Create PostgreSQL Database in Coolify

- [ ] Open Coolify (`http://10.232.1.50:8000`)
- [ ] Go to your HoundDog project
- [ ] Click "+ New" → select "PostgreSQL"
- [ ] Set Postgres User to `hounddog`
- [ ] Set a strong Postgres Password (save it — you need it in Step 4)
- [ ] Set Postgres DB to `hounddog`
- [ ] Click Deploy
- [ ] Once running, find the **Internal Connection URL** on the database resource page
  - It will look like: `postgresql://hounddog:<password>@<internal-host>:5432/hounddog`
- [ ] **Save this URL** — you need it for Step 4

---

## Step 3: Create Okta Application

### A) Create the App

- [ ] Open Okta Admin Console
- [ ] Go to Applications → Create App Integration
- [ ] Sign-in method: **OIDC – OpenID Connect**
- [ ] Application type: **Web Application**
- [ ] Click Next

### B) Configure the App

- [ ] Set App integration name to **HoundDog**
- [ ] Grant type: **Authorization Code** (default, leave checked)
- [ ] Add Sign-in redirect URIs:
  - [ ] `https://hounddog.moravian.edu/auth/callback`
  - [ ] `http://localhost:5173/auth/callback`
- [ ] Add Sign-out redirect URIs:
  - [ ] `https://hounddog.moravian.edu`
  - [ ] `http://localhost:5173`
- [ ] Set Controlled access: "Limit access to selected groups" (or "Allow everyone")
- [ ] Click Save

### C) Record These Values (needed for Step 4)

- [ ] Copy the **Client ID** (General tab)
- [ ] Copy the **Client Secret** (General tab)
- [ ] Note your **Okta Domain** (e.g., `moravian.okta.com`)

### D) Create Okta Groups

- [ ] Go to Directory → Groups → Add Group
- [ ] Create group: `hounddog_admin`
- [ ] Create group: `hounddog_supervisor`
- [ ] Create group: `hounddog_finance`
- [ ] Create group: `hounddog_officer`
- [ ] Add yourself to `hounddog_admin`
- [ ] Assign other users to appropriate groups

### E) Assign Groups to the App

- [ ] Go to Applications → HoundDog → Assignments tab
- [ ] Click Assign → Assign to Groups
- [ ] Assign `hounddog_admin`
- [ ] Assign `hounddog_supervisor`
- [ ] Assign `hounddog_finance`
- [ ] Assign `hounddog_officer`

### F) Add Groups Claim to the Token

- [ ] Go to Security → API → Authorization Servers
- [ ] Click "default"
- [ ] Go to the "Claims" tab
- [ ] Click "Add Claim"
- [ ] Set Name to `groups`
- [ ] Set "Include in" to **ID Token** → **Always**
- [ ] Set Value type to **Groups**
- [ ] Set Filter to **Matches regex** → `.*`
- [ ] Leave "Include in scope" as default
- [ ] Click Create

---

## Step 4: Set Environment Variables in Coolify

Go to your HoundDog app in Coolify → Environment Variables.

### Required (app will not start without these)

- [ ] `HOUNDDOG_DATABASE_URL`
  - Use the URL from Step 2, but change `postgresql://` to `postgresql+asyncpg://`
  - Example: `postgresql+asyncpg://hounddog:<password>@<internal-host>:5432/hounddog`
- [ ] `HOUNDDOG_SECRET_KEY`
  - Generate with: `openssl rand -hex 32`
  - Paste the output
- [ ] `HOUNDDOG_DEBUG`
  - Set to `false`
- [ ] `HOUNDDOG_CORS_ORIGINS`
  - Set to `["https://hounddog.moravian.edu"]`

### Okta SSO (from Step 3)

- [ ] `HOUNDDOG_OKTA_DOMAIN`
  - Your Okta domain, e.g.: `moravian.okta.com`
  - No `https://`, no trailing slash
- [ ] `HOUNDDOG_OKTA_CLIENT_ID`
  - The Client ID from Step 3C
- [ ] `HOUNDDOG_OKTA_CLIENT_SECRET`
  - The Client Secret from Step 3C
- [ ] `HOUNDDOG_OKTA_AUDIENCE`
  - Usually the same as the Client ID
  - Or use a custom audience if configured in Okta's Authorization Server

### Stripe (skip for now, add later)

- [ ] `HOUNDDOG_STRIPE_SECRET_KEY` — leave blank
- [ ] `HOUNDDOG_STRIPE_WEBHOOK_SECRET` — leave blank
- [ ] `HOUNDDOG_STRIPE_PUBLISHABLE_KEY` — leave blank

---

## Step 5: Deploy in Coolify

- [ ] Go to your HoundDog app in Coolify
- [ ] Click Redeploy (or push a commit to trigger auto-deploy)
- [ ] Watch the logs for:
  - [ ] `Database connected and tables created.`
  - [ ] `Application startup complete.`
- [ ] Visit `https://hounddog.moravian.edu`
- [ ] Confirm you are redirected to Okta login
- [ ] Log in with your Moravian credentials
- [ ] Confirm you land on the dashboard with your email and role in the top-right

---

## Step 6: Verify Role-Based Access

- [ ] Dashboard, Permits, Lots, Tickets — visible to ALL roles
- [ ] Finance page (bursar import, revenue, export) — only `admin` or `finance` roles
- [ ] `/pay` page — accessible without any login (student payment portal)
- [ ] `/docs` — Swagger API documentation loads

---

## Quick Reference — Role to Group Mapping

| Okta Group Name | HoundDog Role | Access Level |
|---|---|---|
| `hounddog_admin` | admin | Everything |
| `hounddog_supervisor` | supervisor | Dashboard + operations |
| `hounddog_finance` | finance | Finance + bursar import |
| `hounddog_officer` | officer | Dashboard + basic views |
| (no group / default) | officer | Dashboard + basic views |

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Application startup failed" / Connection refused | `HOUNDDOG_DATABASE_URL` is wrong or PostgreSQL hasn't started. Check the internal hostname. |
| "Token verification failed" | `HOUNDDOG_OKTA_DOMAIN` or `HOUNDDOG_OKTA_CLIENT_ID` is wrong, or the groups claim wasn't added in Step 3F. |
| Okta returns "400 Bad Request" after redirect | The redirect URI in Okta doesn't match your actual domain. Update in Step 3B. |
| Finance pages return 403 | Your user isn't in the `hounddog_admin` or `hounddog_finance` group. Check Okta assignments. |
| `/pay` page asks for login | Should never happen — `/pay` bypasses auth. Check URL is exactly `/pay`. |
