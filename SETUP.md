# Neki DEV – Turso persistence: setup, import, test

DEV only. Production (`neki-community`, repo `Neki`) is never touched. Nothing here is "ready for production" – see section 6.

## 1. What changed vs. your production code (only 3 small edits + 2 new files)
| File | Change |
|---|---|
| `database.py` | `get_connection()` now returns `turso_compat.connect(...)`; the two import-time calls `create_tables()` / `migrate_database()` became `turso_compat.init_schema(...)`. **No business logic touched.** |
| `app.py` | 5 lines after `load_neki_css()` that show the dev timing box (does nothing unless `db_timing = true`). |
| `requirements.txt` | + `turso_serverless` |
| `turso_compat.py` (new) | the adapter |
| `import_to_turso.py` (new) | one-time copy of your data (run on your PC) |
With `backend` unset (or `"sqlite"`) the code behaves exactly like today, so the same files also run locally on SQLite.

## 2. Turso (new DEV database – not your probe DB)
1. turso.tech dashboard → **Create database** → name `neki-dev` → pick the Mumbai/`aws-ap-south-1` location (or the nearest) → create.
2. Open it → copy the **URL** (`libsql://neki-dev-….turso.io`).
3. **Generate token** (read & write, no expiry or long expiry) → copy it. This is a *new* token; do not reuse the probe's.
Optional performance experiment later: create a second DB `neki-dev-us` in a US location and point a copy of the app at it.

## 3. GitHub (new private repo `neki-dev`)
1. github.com → New repository → `neki-dev` → **Private** → Create.
2. **Add file → Upload files** → drag in everything from this folder: `app.py database.py turso_compat.py landing_page.py email_config.py sms_config.py requirements.txt .gitignore assets gps_tracker journey_map tests SETUP.md import_to_turso.py`.
3. **DO NOT upload** `neighbourhelp.db`, `.streamlit/secrets.toml`, `backups/` (the web uploader ignores `.gitignore`, so just don't drag them).
   (`.streamlit/secrets.toml.example` has placeholders only and is safe.)

## 4. Import your data (on your PC, one time) – source = the `neighbourhelp.db` from GitHub main
1. Make a folder, e.g. `C:\neki-dev-import`, copy the repo files into it **and** put the GitHub `neighbourhelp.db` (SHA-256 below) next to `database.py`.
2. Create `.streamlit\secrets.toml` there from `secrets.toml.example` (real URL + token).
3. In a terminal in that folder:
   ```
   py -m pip install turso_serverless bcrypt
   py import_to_turso.py --dev-host neki-dev-XXXX.aws-ap-south-1.turso.io --expect-sha256 68caf3f0006ed40daa738b5e82377d250024e9a667aef53868a749432de3ebdc
   ```
   (Needs Python 3.11+. Older Python: set `NEKI_TURSO_URL` / `NEKI_TURSO_TOKEN` environment variables instead of the file.)
4. Expect `RESULT: ALL TABLES MATCH - import verified.` and `import_report.txt`. It makes a backup copy in `backups\`, never writes to the source, refuses a non-empty target (use `--wipe-dev` only on DEV).
   Real-Turso speed is unknown: the whole import is ~100 statements; at ~0.9 s each expect a few minutes.

## 5. Streamlit DEV app
1. share.streamlit.io → **Create app** → repo `neki-dev`, branch `main`, main file `app.py`, name e.g. `neki-dev`.
2. Advanced settings → Secrets → paste the `secrets.toml.example` block with the real URL/token. Deploy.
3. First start: the schema check runs once (~30 statements); later starts run 1 statement.
4. Open the sidebar box **Database timing (dev)** and run the regression checklist (section 7).

## 6. Verified vs. NOT verified
**Verified by real tests earlier (Turso v3 probe):** connect, `?` parameters, commit, rollback, tuple rows, `lastrowid`, `rowcount`, `cursor.description`, `row_factory` hook honoured, `BEGIN IMMEDIATE`, FK enforcement, IntegrityError class, ~0.9 s per statement.
**Verified in my sandbox, against a stand-in (NOT real Turso):** Neki's real `database.py` ran a 95-step workflow (register, verify, login, OTP, reset, sessions, skills, requests, accept/decline/approve, journey, messages, completion, ratings, trust score, notifications, reports, admin suspend/ban/restore/remove) and gave **identical results and identical final tables** on plain SQLite and on the stand-in (pool on/off, stale pooled connections, 20 ms latency; the stand-in enforces foreign keys and rejects non-primitive parameters, like real Turso). The importer was tested end-to-end against the stand-in using your GitHub DB: all 9 tables, row counts and per-row checksums matched; the second run refused; `--wipe-dev` worked; your source file's hash was unchanged. Re-running the workflow on the imported copy was identical too.
**NOT verified (needs your dev app):** real Turso behaviour of pooled/reused connections, background `close()`, real page latency, the real import speed, that Streamlit Cloud can reach Turso from its region, Python 3.14 behaviour of `turso_serverless` on Streamlit Cloud, the actual UI flows (I could not run Streamlit/the browser here), email/SMS sending.
**Known finding:** your data has 6 legacy columns that `database.py` no longer creates (`users.account_status/suspension_until/moderation_reason`, `help_requests.moderation_status/moderation_reason/moderated_at`, all unused defaults). The importer adds them so nothing is dropped.
**Performance expectation (from counts, not measured on Turso):** the workflow needed ~1.9 statements per function call. At 0.9 s/statement a page that calls 5 functions would take roughly 8–10 s. That is the main open risk; the pool/close tricks cannot remove statement latency itself. If the timing box confirms it, Plan B is local-read designs (embedded replica), which I have not tested.

## 7. Regression checklist (dev app, in this order)
1. App opens; sidebar timing box shows backend `turso`. Note statements/seconds for the first screen.
2. Log in with an existing account (password hashes were copied, so old passwords work). Reload: still logged in.
3. Register a new user → email/OTP flow → log in. Reset password.
4. Post a request; open Browse; search.
5. Second account: offer help → first account approves/declines → journey status, location, messages.
6. Mark provided → confirm completed → rate → check Trust Score and notifications badge.
7. Report a profile/request; admin: statistics, suspend/ban/restore, remove/restore request.
8. Add/delete a skill (try "plumbing" then "Plumbing").
9. **Persistence test (the whole point):** create a marker (e.g. a request titled "MARKER 1"), then Reboot app from Manage app, wait for it, and reload – the marker must still be there. Repeat after the app sleeps.
10. Tell me the statements/seconds per screen from the timing box.

## 8. SHA-256 of the migration source
GitHub `main` `neighbourhelp.db`: `68caf3f0006ed40daa738b5e82377d250024e9a667aef53868a749432de3ebdc` (110,592 bytes, integrity ok, 0 FK violations, 6 users / 26 requests / 21 ratings / 77 sessions / 59 notifications). The ZIP's outer 28 KB file is an empty schema; the ZIP's inner copy differs only by one later session row. Neither was changed.

## 9. Run the tests yourself
`py tests\run_workflow_tests.py path\to\COPY-of-neighbourhelp.db` (uses only the stand-in; never contacts Turso).
