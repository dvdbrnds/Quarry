# HoundDog Deployment Guide

Complete these steps in order. Each step depends on the one before it.

---

## Step 1: DNS Record

- [ ] Create a DNS A record pointing to your Coolify server:
  - **Name:** `hounddog.moravian.edu` (or your chosen subdomain)
  - **Type:** A
  - **Value:** Your Coolify server's IP address
  - **TTL:** 300
- [ ] If internal/DMZ only, add to your internal DNS server
- [ ] If public-facing, add to your public DNS provider
- [ ] Verify propagation: `ping hounddog.moravian.edu`

---

## Step 2: Create PostgreSQL Database in Coolify

- [ ] Open Coolify dashboard
- [ ] Go to **Projects** in the left sidebar
- [ ] Open your project (or create one: click **+ Add** at the top)
- [ ] Inside your project environment, click **+ New** to add a resource
- [ ] Select **PostgreSQL** from the database options
- [ ] Configure the database:
  - [ ] Set Postgres User to `hounddog`
  - [ ] Set a strong Postgres Password (**save this — you need it in Step 5**)
  - [ ] Set Postgres Database to `hounddog`
- [ ] Click **Start** to deploy the database
- [ ] Once running, go to the database resource page
- [ ] Find the **Internal URL** in the database's General Configuration section
  - It will look like: `postgresql://hounddog:<password>@<container-name>:5432/hounddog`
- [ ] **Copy and save this URL** — you need it for Step 5

---

## Step 3: Create HoundDog Application in Coolify

- [ ] In the same project environment, click **+ New** to add another resource
- [ ] Select **Public Repository** (or connect via GitHub App if you've set that up)
- [ ] Enter Repository URL: `https://github.com/dvdbrnds/Quarry`
- [ ] Set **Branch** to `main`
- [ ] Set **Build Pack** to `Dockerfile`
- [ ] Set **Base Directory** to `/hounddog`
  - This tells Coolify to use only the `hounddog/` subdirectory from the monorepo
- [ ] Click **Continue**
- [ ] On the application configuration page:
  - [ ] Set **Domains** (FQDN) to `https://hounddog.moravian.edu`
  - [ ] Set **Ports Exposes** to `3200`
    - This is the port nginx listens on inside the container
- [ ] **Do NOT deploy yet** — set environment variables first (Step 5)

---

## Step 4: Create Okta Application

### A) Create the App

- [ ] Open your Okta Admin Console
- [ ] Go to **Applications** → **Create App Integration**
- [ ] Sign-in method: **OIDC – OpenID Connect**
- [ ] Application type: **Web Application**
- [ ] Click **Next**

### B) Configure the App

- [ ] Set App integration name to **HoundDog**
- [ ] Grant type: **Authorization Code** (default, leave checked)
- [ ] Add Sign-in redirect URIs:
  - [ ] `https://hounddog.moravian.edu/auth/callback`
  - [ ] `http://localhost:5173/auth/callback`
- [ ] Add Sign-out redirect URIs:
  - [ ] `https://hounddog.moravian.edu`
  - [ ] `http://localhost:5173`
- [ ] Set Controlled access: **Limit access to selected groups** (or "Allow everyone")
- [ ] Click **Save**

### C) Record These Values (needed for Step 5)

- [ ] Copy the **Client ID** (shown on the General tab)
- [ ] Copy the **Client Secret** (shown on the General tab)
- [ ] Note your **Okta Domain** (e.g., `moravian.okta.com` — visible in your browser URL bar)

### D) Create Okta Groups

- [ ] Go to **Directory** → **Groups** → **Add Group**
- [ ] Create group: `hounddog_admin`
- [ ] Create group: `hounddog_supervisor`
- [ ] Create group: `hounddog_finance`
- [ ] Create group: `hounddog_officer`
- [ ] Add yourself to `hounddog_admin`
- [ ] Assign other users to appropriate groups

### E) Assign Groups to the App

- [ ] Go to **Applications** → **HoundDog** → **Assignments** tab
- [ ] Click **Assign** → **Assign to Groups**
- [ ] Assign `hounddog_admin`
- [ ] Assign `hounddog_supervisor`
- [ ] Assign `hounddog_finance`
- [ ] Assign `hounddog_officer`

### F) Add Groups Claim to the Token

- [ ] Go to **Security** → **API** → **Authorization Servers**
- [ ] Click **default**
- [ ] Go to the **Claims** tab
- [ ] Click **Add Claim**
- [ ] Set:
  - **Name:** `groups`
  - **Include in token type:** ID Token → Always
  - **Value type:** Groups
  - **Filter:** Matches regex → `.*`
  - **Include in scope:** Leave default (any scope)
- [ ] Click **Create**

---

## Step 5: Set Environment Variables in Coolify

Go to your HoundDog application in Coolify → **Environment Variables** tab.

### Required (app will not start without these)

- [ ] `HOUNDDOG_DATABASE_URL`
  - Take the Internal URL from Step 2 and change `postgresql://` to `postgresql+asyncpg://`
  - Example: `postgresql+asyncpg://hounddog:<password>@<container-name>:5432/hounddog`
- [ ] `HOUNDDOG_SECRET_KEY`
  - Generate with: `openssl rand -hex 32`
  - Paste the output
- [ ] `HOUNDDOG_DEBUG`
  - Set to `false`
- [ ] `HOUNDDOG_CORS_ORIGINS`
  - Set to `["https://hounddog.moravian.edu"]`

### Okta SSO (from Step 4)

- [ ] `HOUNDDOG_OKTA_DOMAIN`
  - Your Okta domain, e.g.: `moravian.okta.com`
  - No `https://`, no trailing slash
- [ ] `HOUNDDOG_OKTA_CLIENT_ID`
  - The Client ID from Step 4C
- [ ] `HOUNDDOG_OKTA_CLIENT_SECRET`
  - The Client Secret from Step 4C
- [ ] `HOUNDDOG_OKTA_AUDIENCE`
  - Usually the same as the Client ID
  - Or use a custom audience if configured in Okta's Authorization Server

### Stripe (skip for now, add later)

- [ ] `HOUNDDOG_STRIPE_SECRET_KEY` — leave blank
- [ ] `HOUNDDOG_STRIPE_WEBHOOK_SECRET` — leave blank
- [ ] `HOUNDDOG_STRIPE_PUBLISHABLE_KEY` — leave blank

---

## Step 6: Persistent Storage & Backups

- [ ] **App uploads** (ticket violation photos): Go to HoundDog app → **Persistent Storage** tab → Add volume:
  - **Name:** `hounddog-uploads`
  - **Destination Path:** `/app/uploads`
- [ ] **Database backups** (optional but recommended): Go to your PostgreSQL resource → **Backups** tab → configure scheduled backups (local or S3)
- [ ] Database data volume is managed automatically by Coolify — no action needed

---

## Step 7: Deploy

- [ ] Go to your HoundDog application in Coolify
- [ ] Click **Deploy**
- [ ] Watch the deployment logs for:
  - [ ] `Building docker image completed.`
  - [ ] `New container started.`
  - [ ] Healthcheck passes (status: `healthy`)
- [ ] If the healthcheck fails, click **Show Debug Logs** to see container output
- [ ] Visit `https://hounddog.moravian.edu`
- [ ] Confirm you are redirected to the Okta login page
- [ ] Log in with your Moravian credentials
- [ ] Confirm you land on the HoundDog dashboard with your email and role badge in the top-right corner

---

## Step 8: Verify

- [ ] **Dashboard** — loads with pipeline stats and live activity feed
- [ ] **Permits** — shows table with Import CSV, Export CSV, + New Permit buttons
- [ ] **Lots** — shows parking lot list
- [ ] **Tickets** — shows ticket table with search and status filter
- [ ] **Finance** — shows revenue reports and bursar import (only for `admin` or `finance` roles)
- [ ] **`/pay`** — accessible without any login (public student payment portal)
- [ ] **`/docs`** — Swagger API documentation loads

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
| Healthcheck fails / `Connection refused` on port 8000 | `HOUNDDOG_DATABASE_URL` is wrong or PostgreSQL hasn't started. Check the Internal URL on the database resource page. Make sure you used `postgresql+asyncpg://` not `postgresql://`. |
| `Application startup failed` in container logs | Same as above — database connection issue. The app retries 10 times (30s total) then exits. |
| `Token verification failed` | `HOUNDDOG_OKTA_DOMAIN` or `HOUNDDOG_OKTA_CLIENT_ID` is wrong. Or the groups claim wasn't added in Step 4F. |
| Okta returns `400 Bad Request` after redirect | The Sign-in redirect URI in Okta doesn't match your actual domain. Go to Applications → HoundDog → General and fix the URI. |
| Finance pages return `403 Forbidden` | Your user isn't in the `hounddog_admin` or `hounddog_finance` Okta group. Check Directory → Groups in Okta. |
| `/pay` page asks for login | Should never happen — `/pay` bypasses auth entirely. Verify the URL is exactly `/pay`, not `/payments` or `/finance`. |
| SSL certificate not working | Coolify auto-provisions via Let's Encrypt. Ensure your DNS A record resolves to the Coolify server IP and port 80/443 are open. |
