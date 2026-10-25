"""
import_to_turso.py -- one-time copy of Neki's SQLite data into the Turso DEVELOPMENT database.

Run it on your own PC, from the folder that contains database.py:

    py import_to_turso.py --source neighbourhelp.db --dev-host <your-dev-db-host>.turso.io

What it does (it never writes to --source; it only reads it):
  1. Reads the Turso URL + token from .streamlit/secrets.toml ([turso] url, auth_token) or from the
     environment variables NEKI_TURSO_URL / NEKI_TURSO_TOKEN.   (The token is never printed or saved.)
  2. Refuses to continue unless --dev-host exactly equals the host in that URL (stops you importing into
     the wrong database by accident).
  3. Checks the source: PRAGMA integrity_check, PRAGMA foreign_key_check, SHA-256 (optionally compared with
     --expect-sha256), then makes a timestamped backup copy in ./backups/.
  4. Builds the Neki schema in Turso (database.py), refuses if any Neki table already has rows
     (unless --wipe-dev, which empties the DEV tables first).
  5. Copies every table, parent tables first, keeping the original ids, password hashes, timestamps etc.,
     and restores the AUTOINCREMENT counters.
  6. Verifies row counts, a per-table checksum of every row, and PRAGMA foreign_key_check on Turso.
  7. Writes import_report.txt.   Exit code 0 only if everything matched.
"""
import argparse, hashlib, os, shutil, sqlite3, sys, time
from datetime import datetime
from pathlib import Path


def load_settings():
    url, token = os.environ.get("NEKI_TURSO_URL"), os.environ.get("NEKI_TURSO_TOKEN")
    sec = Path(".streamlit") / "secrets.toml"
    if (not url or not token) and sec.exists():
        try:
            import tomllib
        except ImportError:
            sys.exit("Python 3.11+ is needed to read secrets.toml (or set NEKI_TURSO_URL / NEKI_TURSO_TOKEN).")
        data = tomllib.loads(sec.read_text(encoding="utf-8"))
        t = data.get("turso", {})
        url, token = url or t.get("url"), token or t.get("auth_token")
    if not url or not token:
        sys.exit("No Turso settings: fill [turso] url and auth_token in .streamlit/secrets.toml (NOT committed to GitHub).")
    return str(url).strip(), str(token).strip()


def host_of(url):
    return url.split("://", 1)[-1].split("?", 1)[0].split("/", 1)[0].strip().lower()


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def tables_of(conn):
    return [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '\\_neki%' ESCAPE '\\' ORDER BY name")]


def fk_parents(conn, table):
    return {r[2] for r in conn.execute(f"PRAGMA foreign_key_list({table})").fetchall() if r[2] != table}


def fk_order(conn, tables):
    order, left = [], set(tables)
    while left:
        ready = sorted(t for t in left if (fk_parents(conn, t) & set(tables)) <= set(order))
        if not ready:
            raise SystemExit("Circular foreign keys between: " + ", ".join(sorted(left)))
        order += ready
        left -= set(ready)
    return order


def table_digest(conn, table, cols):
    h, n = hashlib.sha256(), 0
    q = f'SELECT {", ".join(cols)} FROM {table} ORDER BY id'
    for row in conn.execute(q):
        h.update(repr(tuple(row)).encode("utf-8"))
        n += 1
    return n, h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="neighbourhelp.db")
    ap.add_argument("--dev-host", required=True, help="host of the DEV Turso database, e.g. neki-dev-yourname.aws-ap-south-1.turso.io")
    ap.add_argument("--expect-sha256", default=None)
    ap.add_argument("--wipe-dev", action="store_true", help="empty the DEV tables first (only ever the dev database)")
    ap.add_argument("--chunk", type=int, default=10, help="rows per INSERT statement")
    a = ap.parse_args()
    report = []

    def say(msg=""):
        print(msg)
        report.append(msg)

    url, token = load_settings()
    if host_of(url) != a.dev_host.strip().lower().replace("libsql://", "").replace("https://", ""):
        sys.exit(f"STOP: --dev-host ({a.dev_host}) does not match the host in your Turso URL ({host_of(url)}). Nothing was changed.")
    src = Path(a.source)
    if not src.exists():
        sys.exit(f"Source file not found: {src}")

    say(f"Neki import to Turso DEV  -  {datetime.now():%Y-%m-%d %H:%M:%S}")
    say(f"Target host : {host_of(url)}")
    say(f"Source      : {src.resolve()}  ({src.stat().st_size} bytes)")
    digest = sha256_file(src)
    say(f"Source SHA-256: {digest}")
    if a.expect_sha256 and a.expect_sha256.lower() != digest:
        sys.exit("STOP: source SHA-256 differs from --expect-sha256. Nothing was changed.")

    s = sqlite3.connect(f"file:{src.resolve().as_posix()}?mode=ro", uri=True)
    ic = s.execute("PRAGMA integrity_check").fetchall()
    say(f"Source integrity_check: {ic[0][0] if len(ic) == 1 else ic}")
    fkv = s.execute("PRAGMA foreign_key_check").fetchall()
    say(f"Source foreign_key_check violations: {len(fkv)}")
    if ic[0][0] != "ok" or fkv:
        sys.exit("STOP: source database is not clean (see above). Nothing was changed.")

    Path("backups").mkdir(exist_ok=True)
    backup = Path("backups") / f"{src.stem}_{datetime.now():%Y%m%d_%H%M%S}.db"
    b = sqlite3.connect(backup)
    s.backup(b)
    b.close()
    say(f"Backup copy : {backup}  (SHA-256 {sha256_file(backup)[:16]}...)")

    # ---- target: build the schema through Neki's own code ---------------------------------------
    os.environ["NEKI_DB_BACKEND"] = "turso"
    os.environ["NEKI_TURSO_URL"], os.environ["NEKI_TURSO_TOKEN"] = url, token
    os.environ["NEKI_DB_POOL"] = "true"
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    t0 = time.time()
    import database as db                       # runs create_tables / migrate_database on Turso
    say(f"Schema ready on Turso ({time.time() - t0:.0f} s)")
    t = db.get_connection()

    src_tables = tables_of(s)
    dst_tables = tables_of(t)
    missing = [x for x in src_tables if x not in dst_tables]
    if missing:
        sys.exit("STOP: tables missing in Turso after schema build: " + ", ".join(missing))
    order = fk_order(t, [x for x in src_tables])
    say("Copy order: " + " -> ".join(order))

    nonempty = {x: t.execute(f"SELECT COUNT(*) FROM {x}").fetchone()[0] for x in order}
    nonempty = {k: v for k, v in nonempty.items() if v}
    if nonempty and not a.wipe_dev:
        sys.exit(f"STOP: the Turso database already contains data {nonempty}. Re-run with --wipe-dev only if this is the DEV database.")
    if nonempty:
        say("--wipe-dev: emptying DEV tables " + ", ".join(reversed(order)))
        for x in reversed(order):
            t.execute(f"DELETE FROM {x}")
        t.commit()

    # ---- copy -----------------------------------------------------------------------------------------
    problems = []
    for x in order:
        scols = [r[1] for r in s.execute(f"PRAGMA table_info({x})")]
        dcols = [r[1] for r in t.execute(f"PRAGMA table_info({x})").fetchall()]
        # Columns that exist in your real database but that database.py no longer creates (older versions of
        # Neki added them). They are added to the Turso table first so NO data is dropped.
        for cid, cname, ctype, notnull, dflt, pk in s.execute(f"PRAGMA table_info({x})").fetchall():
            if cname in dcols:
                continue
            ddl = f"ALTER TABLE {x} ADD COLUMN {cname} {ctype or ''}" + (f" DEFAULT {dflt}" if dflt is not None else "")
            try:
                t.execute(ddl)
                t.commit()
                dcols.append(cname)
                say(f"  note: added legacy column {x}.{cname} {ctype} (present in your data, not created by database.py)")
            except Exception as e:
                problems.append(f"{x}.{cname}: could not add column ({type(e).__name__}: {e})")
                say(f"  PROBLEM: {problems[-1]}")
        lost = [c for c in scols if c not in dcols]
        if lost:
            problems.append(f"{x}: source columns missing in Turso: {lost}")
            say(f"  PROBLEM: {problems[-1]} - table skipped")
            continue
        rows = s.execute(f'SELECT {", ".join(scols)} FROM {x} ORDER BY id').fetchall()
        ph = "(" + ", ".join("?" * len(scols)) + ")"
        t0 = time.time()
        for i in range(0, len(rows), a.chunk):
            part = rows[i:i + a.chunk]
            params = [v for r in part for v in r]
            try:
                t.execute(f'INSERT INTO {x} ({", ".join(scols)}) VALUES ' + ", ".join([ph] * len(part)), params)
            except Exception as e:
                t.rollback()
                sys.exit(f"STOP: inserting into {x} (source rows {i + 1}-{i + len(part)}, ids {part[0][0]}..{part[-1][0]}) failed: "
                         f"{type(e).__name__}: {e}. The Turso DEV database is partly filled - re-run with --wipe-dev after fixing.")
        t.commit()
        say(f"  copied {x:24} {len(rows):5} rows  ({time.time() - t0:.1f} s)")

    # ---- AUTOINCREMENT counters ---------------------------------------------------------------------------
    try:
        for name, seq in s.execute("SELECT name, seq FROM sqlite_sequence").fetchall():
            if name not in order:
                continue
            cur = t.execute("SELECT seq FROM sqlite_sequence WHERE name = ?", (name,)).fetchone()
            if cur is None:
                t.execute("INSERT INTO sqlite_sequence (name, seq) VALUES (?, ?)", (name, seq))
            elif cur[0] < seq:
                t.execute("UPDATE sqlite_sequence SET seq = ? WHERE name = ?", (seq, name))
        t.commit()
        say("AUTOINCREMENT counters restored")
    except Exception as e:
        say(f"WARNING: could not restore AUTOINCREMENT counters ({type(e).__name__}); ids already copied are kept, "
            f"but a deleted highest id could be re-used by new rows.")

    # ---- verify ---------------------------------------------------------------------------------------------------
    say("")
    say("Verification (source vs Turso):")
    for x in order:
        cols = [r[1] for r in s.execute(f"PRAGMA table_info({x})")]
        n1, h1 = table_digest(s, x, cols)
        n2, h2 = table_digest(t, x, cols)
        ok = (n1 == n2 and h1 == h2)
        say(f"  {x:24} rows {n1:5} vs {n2:5}   checksum {'MATCH' if ok else 'DIFFERENT'}")
        if not ok:
            problems.append(f"{x}: counts {n1}/{n2} or checksum differ")
    fk2 = t.execute("PRAGMA foreign_key_check").fetchall()
    say(f"  Turso foreign_key_check violations: {len(fk2)}")
    if fk2:
        problems.append("foreign_key_check violations on Turso")
    t.close()
    say("")
    say("RESULT: " + ("ALL TABLES MATCH - import verified." if not problems else "PROBLEMS: " + "; ".join(problems)))
    Path("import_report.txt").write_text("\n".join(report), encoding="utf-8")
    time.sleep(0.5)
    sys.exit(0 if not problems else 1)


if __name__ == "__main__":
    main()
