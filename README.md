# Copado Support

Personal daily checklist with history, diary, day rollover, and multi-user auth — wrapped in a **Copado Support** app shell (navy sidebar + top bar) so the product can grow into a team workspace later.

**Working today:** My Tasks (personal checklist), Diary, History, **Team Queue**, **Dashboard**, notifications, auth, Admin console.  
**Roadmap (nav stubs):** Calendar / Reports / Settings.

## Features

- Copado-branded shell: sidebar navigation, top search, notifications, account menu
- **Team Queue** — shared support cases (`CS-####`) with status, assignee, priority, due date, comments
- **Dashboard** — total / mine / overdue / due today + status breakdown + upcoming due
- In-app **notifications** when you are assigned or someone comments on your cases
- Per-user checklist, diary, and history (server-synced via SQLite)
- Incomplete items roll over to the next day
- **Priorities** (low / medium / high), **due dates**, and **Work / Personal** lists
- Search across today, history, and diary
- Optional browser **reminders** for due / overdue items
- Light / dark theme toggle
- Admin password login + GitHub / Google OAuth (admin-controlled)
- Corporate Admin console: toggle providers, add/remove users, change Admin password
- Multi-tab sync with toast when remote state is newer; slower polling when the tab is hidden

## Roadmap

| Phase | Scope |
|-------|--------|
| **1** | App shell around checklist / diary / history |
| **2 (now)** | Shared Team Queue (status, assignee, priority, CS-####, comments) |
| **3 (now)** | Dashboard metrics + in-app notifications |
| **4** | Calendar, Teams, richer Admin (SLA, custom fields), Reports |

Admin console at `/admin` stays its own corporate UI; the shell links to it for admins.

## Users

| User | Login | Starting data |
|------|-------|---------------|
| **Admin** | Username/password (`admin` / `admin` by default) | Seeded from `data/checklist.json` |
| **apasupuleti@copado.com** | GitHub and/or Google (when enabled) | Same seed (deep copy) |

OAuth accounts must be **provisioned by Admin** first (User 1 is seeded). There is no open signup.

The **Admin** link appears in the sidebar and account menu only for the Admin account. Non-admins cannot open `/admin`.

## Admin console

Sign in as Admin → **Admin** in the sidebar → [http://localhost:8080/admin](http://localhost:8080/admin)

- **Authentication** — enable/disable Google and GitHub; change Admin password
- **Users** — add users by email, remove users (Admin cannot remove themselves)
- Optional: copy Admin checklist data when adding a user

Google login defaults to **off**; GitHub defaults to **on**.

### Change Admin password

1. Preferred: Admin console → Authentication → **Change Admin password** (min 8 characters)
2. Or set `ADMIN_PASSWORD` in `.env` **before first seed** (empty database). Changing `.env` later does not update an existing Admin hash — use the console form instead.

## Run locally

```bash
cd "/Users/anudeeppasupuleti/Documents/Copado Support - Anudeep"
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in OAuth keys + a strong SESSION_SECRET
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8080
```

Open **[http://localhost:8080](http://localhost:8080)**

- Login page: social buttons (if enabled) + **Admin account** username/password form
- Default Admin: `admin` / `admin`

## Tests

```bash
source .venv/bin/activate
pytest -q
```

## Environment

Copy [`.env.example`](.env.example). Important variables:

| Variable | Purpose |
|----------|---------|
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | Admin password on **first seed** only |
| `SESSION_SECRET` | Session cookie signing — use a long random string |
| `ENV` | Set to `production` to refuse weak `SESSION_SECRET` |
| `BASE_URL` | App URL for OAuth callbacks; `https://` enables secure cookies |
| `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` | GitHub OAuth |
| `USER1_EMAIL` / `USER1_GITHUB_LOGIN` | Seed User 1 + link GitHub login if email differs |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Google OAuth |

Production (or any non-localhost `https` `BASE_URL`) **refuses to start** if `SESSION_SECRET` is missing, a known placeholder, or shorter than 24 characters.

## GitHub login

1. [GitHub → OAuth Apps](https://github.com/settings/developers) → New OAuth App  
   - Homepage: `http://localhost:8080`  
   - Callback: `http://localhost:8080/auth/callback`
2. Set `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, and `USER1_GITHUB_LOGIN` in `.env`
3. Restart the server (GitHub is enabled by default in Admin)

## Google login

1. [Google Cloud Console](https://console.cloud.google.com/apis/credentials) → OAuth client (Web)  
   - Authorized redirect URI: `http://localhost:8080/auth/callback/google`
2. Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in `.env`
3. Restart the server
4. As Admin, turn **Google login** on

## Deploy

- Set a strong `SESSION_SECRET`, `ENV=production`, `BASE_URL`, `ADMIN_*`, provider keys, and `USER1_GITHUB_LOGIN`
- Start: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
- Register production callback URLs for GitHub and Google to match `BASE_URL`

### Render + PostgreSQL (recommended — data survives redeploys)

SQLite on Render Free is wiped on every deploy. Use Postgres instead:

1. In Render: **New → PostgreSQL** (Free is fine for testing; note free DBs may expire after ~30 days).
2. Open the Postgres service → copy **Internal Database URL** (or External if needed).
3. On your **Web Service** → **Environment**:
   - `DATABASE_URL` = that Postgres URL (paste as-is; `postgres://` is normalized automatically)
   - Keep `BASE_URL=https://teamcopa.onrender.com` (or your URL)
4. **Remove** any old `DATABASE_URL=sqlite:///…` from the web service.
5. Redeploy the web service. Tables are created on startup; Admin/users seed into Postgres.
6. Link the DB to the web service (Render “Connect” / same account region) so Internal URL resolves.

After that, Team Queue and checklists persist across deploys.

## Data

- **Local:** SQLite file `data/app.db` (default)
- **Production (Render):** PostgreSQL via `DATABASE_URL`
- Seed copies `data/checklist.json` into Admin and User 1 once (per database)
- After seed, each user’s checklist/diary/history is independent
- Export / Import JSON backups from the checklist UI (personal state)
- Admin full backup: `GET /api/admin/backup` (while logged in as Admin)

### Recover local + live into Postgres

**No Render Shell needed** (Shell is paid). Do **not** redeploy while trying to salvage Free SQLite — redeploy wipes it.

1. **Local (already safe)** under `data/backups/`, or:
   ```bash
   python scripts/dump_sqlite.py data/app.db -o data/backups/local-dump.json --source local
   ```
2. **Live via APIs** (uses Admin login; pulls users + Team Queue + Admin checklist):
   ```bash
   python scripts/pull_live_api.py \
     --base-url https://teamcopa.onrender.com \
     --admin-password 'YOUR_ADMIN_PASSWORD' \
     -o data/backups/live-api-dump.json
   ```
   If the script reports ~0 tasks / only seed users, live disk was already wiped.
3. **Each OAuth user’s checklist** (API can’t read other users’ state): on the live site, log in → **⋯ → Export**, save the JSON, then:
   ```bash
   python scripts/inject_checklist.py data/backups/live-api-dump.json ~/Downloads/checklist-….json \
     --email apasupuleti@copado.com
   ```
4. After Postgres is linked, merge into Render using the **External** Database URL:
   ```bash
   python scripts/restore_backup.py \
     data/backups/local-dump.json \
     data/backups/live-api-dump.json \
     --database-url 'postgresql://…'
   ```
   Users match by email; checklist state keeps the newer `updatedAt`; tasks merge by `case_number`.

Admin full backup for later (after Postgres is live): `GET /api/admin/backup` while logged in as Admin.