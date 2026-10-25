"""Runs ONE pass of Neki's real database.py workflows and writes a normalised JSON result.
Usage: python scenario.py <backend: sqlite|turso> <db_copy> <out.json>
Run from run_workflow_tests.py (which compares the sqlite pass with the Turso-stand-in pass)."""
import json, os, re, sys, sqlite3, tempfile, shutil, time, warnings
warnings.simplefilter("ignore")
backend, src_db, out = sys.argv[1:4]
here = os.path.dirname(os.path.abspath(__file__)); root = os.path.dirname(here)
work = tempfile.mkdtemp(prefix="neki_" + backend + "_")
shutil.copy(src_db, os.path.join(work, "neighbourhelp.db"))
os.environ["NEKI_DB_BACKEND"] = backend
os.environ.setdefault("NEKI_DB_TIMING", "false")
if backend == "turso":
    os.environ["FAKE_TURSO_FILE"] = os.path.join(work, "remote.db")
    shutil.copy(src_db, os.environ["FAKE_TURSO_FILE"])
    os.environ["NEKI_TURSO_URL"] = "libsql://fake-dev-db.turso.io"
    os.environ["NEKI_TURSO_TOKEN"] = "fake-token"
    sys.path.insert(0, os.path.join(here, "fake"))
try:
    import bcrypt  # noqa
except ImportError:
    sys.path.insert(0, os.path.join(here, "stubs"))
sys.path.insert(0, root)
os.chdir(work)
t0 = time.time()
import database as db
import turso_compat
init_result = turso_compat.init_schema.__name__
R = []

TOK = re.compile(r"^[A-Za-z0-9_\-]{30,}$")
def norm(v):
    if isinstance(v, (sqlite3.Row,)) or hasattr(v, "keys") and not isinstance(v, dict):
        return {k: norm(v[k]) for k in v.keys()}
    if isinstance(v, dict): return {k: norm(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)): return [norm(x) for x in v]
    if isinstance(v, str):
        if v.startswith("$2") or re.fullmatch(r"[0-9a-f]{64}", v) or TOK.match(v): return "<secret>"
        if re.match(r"\d{4}-\d\d-\d\d[ T]\d\d:\d\d", v): return "<ts>"
        return v
    if isinstance(v, float): return round(v, 4)
    return v

def step(name, fn, *a, **k):
    try:
        res = fn(*a, **k); R.append((name, "ok", norm(res)))
        return res
    except Exception as e:
        R.append((name, "EXC " + type(e).__name__, str(e)[:120])); return None

def sql(q, p=()):
    c = db.get_connection()
    try: return [norm(r) for r in c.execute(q, p).fetchall()]
    finally: c.close()

# --- accounts ----------------------------------------------------------------------------------
users = {}
for key, em in (("req", "t.req@example.com"), ("hlp", "t.hlp@example.com"), ("rep", "t.rep@example.com")):
    r = step("register " + key, db.register_user, key.title() + " Test", em, "Passw0rd!x", "Patna", "+91990000000" + str(len(users)))
    users[key] = db.get_user_by_email(em)["id"]; 
    tok = r[1] if r and r[0] else None
    step("verify email " + key, db.verify_email_token, tok)
step("register duplicate", db.register_user, "Dup", "t.req@example.com", "x", "Patna", "1")
step("login ok", lambda: db.verify_login("t.req@example.com", "Passw0rd!x"))
step("login wrong pw", lambda: db.verify_login("t.req@example.com", "nope"))
step("login unknown", lambda: db.verify_login("ghost@example.com", "nope"))
step("by id", db.get_user_by_id, users["req"])
step("update user", db.update_user, users["req"], "Req Renamed", "Gaya", "+919900000001")
otp = db.create_phone_otp(users["hlp"], "+919811111111"); R.append(("create otp", "ok", len(otp)))
step("otp wrong", db.verify_phone_otp, users["hlp"], "000000")
step("otp right", db.verify_phone_otp, users["hlp"], otp)
step("phone status", db.get_phone_verification_status, users["hlp"])
tok = step("reset token", db.create_password_reset_token, "t.rep@example.com")
step("reset valid?", db.is_password_reset_token_valid, tok)
step("reset do", db.reset_password_with_token, tok, "NewPassw0rd!")
step("reset reuse", db.reset_password_with_token, tok, "Other!")
step("login new pw", lambda: db.verify_login("t.rep@example.com", "NewPassw0rd!"))
# --- sessions / skills ---------------------------------------------------------------------------
st = step("create session", db.create_login_session, users["req"])
step("session user", db.get_user_from_session, st)
step("delete session", db.delete_login_session, st)
step("session gone", db.get_user_from_session, st)
step("skill add", db.add_user_skill, users["hlp"], "Plumbing")
step("skill dup same case", db.add_user_skill, users["hlp"], "Plumbing")
step("skill dup other case", db.add_user_skill, users["hlp"], "plumbing")
step("skill list", db.get_user_skills, users["hlp"])
sk = db.get_user_skills(users["hlp"])
step("skill delete", db.delete_user_skill, users["hlp"], sk[0]["id"] if sk else 0)
# --- requests --------------------------------------------------------------------------------------
rid = step("create request", db.create_help_request, users["req"], "Fix tap", "Leaking tap", "Plumbing", "Patna", "Free", None, 25.6, 85.1)
rid2 = step("create request 2", db.create_help_request, users["req"], "Groceries", "Need milk", "Groceries", "Patna", "Paid", 100, None, None)
step("my requests", db.get_user_requests, users["req"])
step("open requests (helper)", db.get_open_requests, users["hlp"])
step("search", db.search_help_requests, "tap", users["hlp"])
step("community activity", db.get_recent_community_activity, 5)
step("remove own (other user)", db.remove_own_request, rid2 if isinstance(rid2, int) else 0, users["hlp"])
step("remove own", db.remove_own_request, rid2 if isinstance(rid2, int) else 0, users["req"])
RID = db.get_user_requests(users["req"])
RID = [r["id"] for r in RID if r["title"] == "Fix tap"][0]
step("accept", db.accept_help_request, RID, users["hlp"])
step("accept again", db.accept_help_request, RID, users["rep"])
step("approve", db.approve_helper, RID, users["req"])
step("accepted list", db.get_accepted_requests, users["hlp"])
step("journey view", db.get_journey_request, RID, users["hlp"])
step("journey start", db.update_journey_status, RID, users["hlp"], "In Progress")
step("journey location", db.update_journey_location, RID, users["hlp"], 25.61, 85.12)
step("journey arrived", db.update_journey_status, RID, users["hlp"], "Arrived")
step("msg send req", db.send_request_message, RID, users["req"], "Hello helper")
step("msg send hlp", db.send_request_message, RID, users["hlp"], "On my way")
step("msg outsider", db.send_request_message, RID, users["rep"], "intruder")
step("msgs", db.get_request_messages, RID, users["req"])
step("connected profile", db.get_connected_profile, RID, users["req"])
step("match profile", db.get_match_profile, RID, users["hlp"])
step("helped count before", db.get_people_helped_count, users["hlp"])
step("help provided", db.mark_help_provided, RID, users["hlp"])
step("confirm completed", db.confirm_help_completed, RID, users["req"])
step("rate", db.submit_rating, RID, users["req"], users["hlp"], 5, "Great")
step("rate twice", db.submit_rating, RID, users["req"], users["hlp"], 1, "again")
step("has rated", db.has_user_rated, RID, users["req"])
step("trust", db.update_trust_score, users["hlp"])
step("rating stats", db.get_user_rating_stats, users["hlp"])
step("reviews", db.get_received_reviews, users["hlp"], 10)
step("helped count after", db.get_people_helped_count, users["hlp"])
step("dashboard req", db.get_dashboard_stats, users["req"])
step("dashboard hlp", db.get_dashboard_stats, users["hlp"])
# decline path on a separate request
rid3 = step("create request 3", db.create_help_request, users["req"], "Carry box", "Heavy", "Moving", "Patna", "Free", None, None, None)
step("accept 3", db.accept_help_request, rid3, users["rep"])
step("decline 3", db.decline_helper, rid3, users["req"])
step("accept 3 again", db.accept_help_request, rid3, users["rep"])
# --- notifications ---------------------------------------------------------------------------------
step("notify", db.create_notification, users["req"], "info", "Hi", "Test message", RID)
step("notifs", db.get_notifications, users["req"], 50)
step("unread", db.get_unread_notification_count, users["req"])
step("unread ratings", db.get_unread_rating_count, users["hlp"])
step("mark rating notifs", db.mark_rating_notifications_read, users["hlp"])
nid = (db.get_notifications(users["req"], 50) or [{"id": 0}])[0]["id"]
step("mark one", db.mark_notification_read, nid, users["req"])
step("mark all", db.mark_all_notifications_read, users["req"])
step("unread after", db.get_unread_notification_count, users["req"])
# --- reports / admin ---------------------------------------------------------------------------------
admin = sql("SELECT id FROM users WHERE role = 'Admin' ORDER BY id LIMIT 1")
admin_id = admin[0]["id"] if admin else None
R.append(("admin id found", "ok", admin_id is not None))
step("report profile", db.create_report, users["rep"], users["hlp"], None, "Rude", "Profile")
step("report profile dup", db.create_report, users["rep"], users["hlp"], None, "Rude", "Profile")
step("report request", db.create_report, users["rep"], None, RID, "Spam", "Request")
step("admin stats", db.get_admin_statistics)
step("admin requests", db.get_admin_requests)
step("admin users", db.get_admin_users)
step("admin reports", db.get_admin_reports)
reps = db.get_admin_reports() or []
mine = [r for r in reps if r["reason"] in ("Rude", "Spam")]
if mine:
    step("report action suspend", db.take_admin_report_action, mine[0]["id"], "Suspend 24 hours", "test")
    step("report resolve", db.resolve_admin_report, mine[-1]["id"], "ok", "None")
    step("report action remove", db.take_admin_report_action, mine[-1]["id"], "Remove Request", "spam")
step("restore request", db.restore_admin_request, RID)
step("suspend", db.suspend_user, users["rep"], 2, "test")
step("restore user", db.restore_user, users["rep"])
step("ban", db.ban_user, users["rep"], "test")
step("restore user 2", db.restore_user, users["rep"])
step("login after restore", lambda: db.verify_login("t.rep@example.com", "NewPassw0rd!"))
step("remove admin req", db.remove_admin_request, RID, "test", admin_id)
step("restore admin req", db.restore_admin_request, RID)
# --- final database state (everything the workflows touched) ------------------------------------------
state = {}
for t in ("users", "help_requests", "ratings", "reports", "notifications", "request_messages", "user_sessions",
          "password_reset_tokens", "user_skills"):
    state[t] = sql(f"SELECT * FROM {t} ORDER BY id")
final = {"steps": R, "state": state}
json.dump(final, open(out, "w"), indent=1, sort_keys=True, default=str)
print(backend, "steps:", len(R), "exceptions:", sum(1 for s in R if s[1].startswith("EXC")), "seconds: %.1f" % (time.time() - t0))
