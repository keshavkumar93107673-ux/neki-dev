"""
turso_compat.py -- sqlite3-compatible connection layer for Neki (DEVELOPMENT copy).

database.py keeps calling get_connection() and using cursors, rows and exceptions exactly as
before. This module decides what that connection really is:

  backend "sqlite" (default): a plain sqlite3 connection, identical to the original code.
  backend "turso"           : a Turso Cloud connection (turso_serverless client) wrapped so that
                              Neki's existing code works unchanged.

What the wrapper adds, and why (each item was checked against real Turso test results):
  * Rows: rows support row["name"], row[0], keys(), dict(row), like sqlite3.Row.
    (Verified: the client honours conn.row_factory = f(cursor, row) and exposes cursor.description,
     including for PRAGMA table_info.)
  * Exceptions: turso_serverless errors are re-raised as the matching sqlite3 exception class, so
    `except sqlite3.IntegrityError` in database.py keeps working. (Verified: the client raises
    turso_serverless.dbapi.IntegrityError, which is NOT a sqlite3.Error.)
  * Transactions: cursor.execute("BEGIN IMMEDIATE"), commit() and rollback() are passed straight
    through. (Verified: BEGIN IMMEDIATE works first or after a SELECT, rollback discards, and a
    second BEGIN IMMEDIATE waits for the first.)
  * Speed: measured on a real database, one statement cost ~880 ms and a new connection ~870 ms
    more. So connections are reused (a small pool), closing is done in the background, and
    schema creation/migration at startup is skipped when it has already been done.
    (ASSUMPTIONS, not yet verified on real Turso: that pooled connections stay valid for a few
    seconds, and that connect/close are the slow steps. The timing panel measures both.)

Settings (environment variable, or Streamlit Secrets):
  NEKI_DB_BACKEND   | [database] backend     = "sqlite" | "turso"       (default sqlite)
  NEKI_TURSO_URL    | [turso]    url
  NEKI_TURSO_TOKEN  | [turso]    auth_token
  NEKI_DB_POOL      | [database] pool        = true | false              (default true)
  NEKI_DB_POOL_IDLE | [database] pool_idle_seconds                       (default 5)
  NEKI_DB_TIMING    | [debug]    db_timing   = true | false              (default false)
Nothing secret is ever printed.
"""
import hashlib
import inspect
import os
import re
import sqlite3
import threading
import time
from collections import deque
from datetime import date, datetime

_LOCK = threading.Lock()


# ------------------------------------------------------------------ settings
def _secret(section, key):
    try:
        import streamlit as st
        return st.secrets[section][key]
    except Exception:
        return None


def _setting(env, section, key, default=None):
    v = os.environ.get(env)
    if v not in (None, ""):
        return v
    v = _secret(section, key)
    return default if v in (None, "") else v


def _flag(env, section, key, default):
    v = _setting(env, section, key, None)
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def backend():
    return str(_setting("NEKI_DB_BACKEND", "database", "backend", "sqlite")).strip().lower()


def pool_enabled():
    return _flag("NEKI_DB_POOL", "database", "pool", True)


def pool_idle_seconds():
    try:
        return float(_setting("NEKI_DB_POOL_IDLE", "database", "pool_idle_seconds", 5))
    except Exception:
        return 5.0


def timing_enabled():
    return _flag("NEKI_DB_TIMING", "debug", "db_timing", False)


POOL_MAX = 4


# ------------------------------------------------------------------ rows
class NekiRow(tuple):
    """Behaves like sqlite3.Row: row[0], row["name"] (case-insensitive), keys(), iteration over
    values, len(), dict(row)."""

    def __new__(cls, cols, vals):
        obj = super().__new__(cls, vals)
        obj._cols = list(cols)
        obj._idx = {str(c).lower(): i for i, c in enumerate(obj._cols)}
        return obj

    def __getitem__(self, k):
        if isinstance(k, str):
            try:
                return tuple.__getitem__(self, self._idx[k.lower()])
            except KeyError:
                raise IndexError("No item with that key") from None   # same as sqlite3.Row
        return tuple.__getitem__(self, k)

    def keys(self):
        return list(self._cols)


def _row_factory(cursor, row):
    return NekiRow([d[0] for d in cursor.description], row)


# ------------------------------------------------------------------ errors and parameters
def _translate(exc):
    """turso_serverless errors -> the matching sqlite3 class. Anything else is left alone."""
    if isinstance(exc, sqlite3.Error):
        return exc
    if not str(type(exc).__module__ or "").startswith("turso_serverless"):
        return exc
    names = [c.__name__ for c in type(exc).__mro__]
    for name, cls in (("IntegrityError", sqlite3.IntegrityError), ("OperationalError", sqlite3.OperationalError),
                      ("ProgrammingError", sqlite3.ProgrammingError), ("DatabaseError", sqlite3.DatabaseError),
                      ("Error", sqlite3.Error)):
        if name in names:
            return cls(str(exc))
    return exc


def _adapt(params):
    """Same conversions sqlite3 applies on its own (the Turso client only accepts plain values)."""
    if not params:
        return params
    out = []
    for v in params:
        if isinstance(v, bool):
            v = int(v)
        elif isinstance(v, datetime):
            v = v.isoformat(" ")
        elif isinstance(v, date):
            v = v.isoformat()
        out.append(v)
    return tuple(out)


def _is_read(sql):
    head = sql.lstrip()[:7].upper()
    return head.startswith(("SELECT", "PRAGMA", "WITH"))


# ------------------------------------------------------------------ statistics (for the timing panel)
class _Stats:
    def __init__(self):
        self.lock = threading.Lock()
        self.reset_unlocked()

    def reset_unlocked(self):
        self.c = {"statements": 0, "statement_ms": 0.0, "connects": 0, "connect_ms": 0.0, "closes": 0,
                  "close_ms": 0.0, "commits": 0, "commit_ms": 0.0, "pool_hits": 0, "pool_misses": 0,
                  "stale_retries": 0, "errors": 0}
        self.recent = deque(maxlen=400)

    def add(self, kind, ms, sql=""):
        with self.lock:
            key = {"statement": "statement", "connect": "connect", "close": "close", "commit": "commit"}.get(kind)
            if key:
                self.c[key + ("s" if key != "statement" else "s")] += 1
                self.c[key + "_ms"] += ms
            self.recent.append((kind, ms, sql[:80]))

    def bump(self, name):
        with self.lock:
            self.c[name] += 1

    def snapshot_and_reset(self):
        with self.lock:
            snap = (dict(self.c), list(self.recent))
            self.reset_unlocked()
            return snap


STATS = _Stats()
_CUMULATIVE = {"statements": 0, "statement_ms": 0.0, "connects": 0, "connect_ms": 0.0, "runs": 0}


# ------------------------------------------------------------------ Turso connection wrapper
_POOL = []          # idle wrapped connections, most recent last
_WORKING_URL = []   # remembers which URL form worked


def _host_of(url):
    u = url.split("://", 1)[-1].split("?", 1)[0].split("/", 1)[0]
    return u


def _url_candidates(url):
    host = _host_of(url)
    return list(dict.fromkeys([url, f"https://{host}", f"libsql://{host}", f"turso://{host}"]))


def _open_raw():
    url = _setting("NEKI_TURSO_URL", "turso", "url")
    token = _setting("NEKI_TURSO_TOKEN", "turso", "auth_token")
    if not url or not token:
        raise RuntimeError("Turso backend selected but [turso] url / auth_token are missing in Streamlit Secrets.")
    url, token = str(url).strip().strip('"'), str(token).strip().strip('"')
    try:
        import turso_serverless
    except Exception as e:
        raise RuntimeError("turso_serverless is not installed (add it to requirements.txt): " + type(e).__name__) from None
    cands = _WORKING_URL + [u for u in _url_candidates(url) if u not in _WORKING_URL]
    last = None
    for u in cands:
        t0 = time.perf_counter()
        try:
            raw = turso_serverless.connect(u, auth_token=token)
            STATS.add("connect", (time.perf_counter() - t0) * 1000)
            if not _WORKING_URL:
                _WORKING_URL.append(u)
            raw.row_factory = _row_factory
            return raw
        except Exception as e:
            last = e
    raise RuntimeError(f"Could not connect to Turso at {_host_of(url)}: {type(last).__name__}: "
                       f"{str(last).replace(token, '***')[:200]}") from None


def _close_in_background(raw, rollback=False):
    def work():
        t0 = time.perf_counter()
        if rollback:                 # never leave an abandoned write transaction holding the database
            try:
                raw.rollback()
            except Exception:
                pass
        try:
            raw.close()
        except Exception:
            pass
        STATS.add("close", (time.perf_counter() - t0) * 1000)
    threading.Thread(target=work, daemon=True).start()


class TursoConnection:
    """The object database.py receives from get_connection() when the backend is Turso."""

    def __init__(self, raw, reused=False):
        self._raw = raw
        self._dirty = False          # a write / transaction may be open
        self._closed = False
        self._reused = reused
        self._first = True           # no statement run yet on this checkout
        self._last_used = time.perf_counter()

    # sqlite3 API surface used by Neki ----------------------------------------------------------
    @property
    def row_factory(self):
        return _row_factory

    @row_factory.setter
    def row_factory(self, value):    # rows are always NekiRow
        pass

    def cursor(self):
        return _Cursor(self)

    def execute(self, sql, params=()):
        return self.cursor().execute(sql, params)

    def commit(self):
        t0 = time.perf_counter()
        try:
            self._raw.commit()
        except Exception as e:
            STATS.bump("errors")
            t = _translate(e)
            raise (t if t is not e else e) from None
        self._dirty = False
        self._last_used = time.perf_counter()
        STATS.add("commit", (self._last_used - t0) * 1000)

    def rollback(self):
        try:
            self._raw.rollback()
        except Exception as e:
            STATS.bump("errors")
            t = _translate(e)
            raise (t if t is not e else e) from None
        self._dirty = False
        self._last_used = time.perf_counter()

    def close(self):
        if self._closed:
            return
        self._closed = True
        # A connection with an open write/transaction is never reused; it is closed in the background.
        if (not self._dirty) and pool_enabled():
            with _LOCK:
                if len(_POOL) < POOL_MAX:
                    self._last_used = time.perf_counter()
                    _POOL.append(self)
                    return
        _close_in_background(self._raw, rollback=self._dirty)

    # internals ---------------------------------------------------------------------------------
    def _reopen_for_use(self):
        self._closed = False
        self._reused = True
        self._first = True
        self._dirty = False

    def _replace_raw(self):
        old = self._raw
        self._raw = _open_raw()
        _close_in_background(old)
        self._reused = False

    def _run(self, cur, sql, params):
        p = _adapt(params)
        read = _is_read(sql)
        if not read:
            self._dirty = True
        t0 = time.perf_counter()
        try:
            try:
                cur._cur.execute(sql, p) if p else cur._cur.execute(sql)
            except Exception as e:
                if (self._reused and self._first and not isinstance(e, sqlite3.Error)
                        and not isinstance(_translate(e), (sqlite3.IntegrityError, sqlite3.ProgrammingError))):
                    # The FIRST statement on a reused pooled connection failed with a connection-type error
                    # (not a constraint/SQL error): the connection went stale. Replace it and retry once.
                    # (A write is retried too; the only risk is a write that executed but whose reply was
                    #  lost -- very unlikely on a first statement after idle. Pool can be disabled in Secrets.)
                    STATS.bump("stale_retries")
                    self._replace_raw()
                    cur._cur = self._raw.cursor()
                    cur._cur.execute(sql, p) if p else cur._cur.execute(sql)
                else:
                    raise
        except Exception as e:
            STATS.bump("errors")
            t = _translate(e)
            raise (t if t is not e else e) from None
        self._first = False
        self._last_used = time.perf_counter()
        STATS.add("statement", (self._last_used - t0) * 1000, sql)


class _Cursor:
    """Thin proxy around the Turso cursor: times statements and translates errors."""

    def __init__(self, conn):
        self._conn = conn
        self._cur = conn._raw.cursor()

    def execute(self, sql, params=()):
        self._conn._run(self, sql, params)
        return self

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def fetchmany(self, size=None):
        return self._cur.fetchmany(size) if size is not None else self._cur.fetchmany()

    def __iter__(self):
        return iter(self._cur.fetchall())

    @property
    def description(self):
        return self._cur.description

    @property
    def lastrowid(self):
        return self._cur.lastrowid

    @property
    def rowcount(self):
        return self._cur.rowcount

    def close(self):
        pass


def _connect_turso():
    if pool_enabled():
        ttl = pool_idle_seconds()
        now = time.perf_counter()
        with _LOCK:
            while _POOL:
                c = _POOL.pop()
                if now - c._last_used <= ttl:
                    STATS.bump("pool_hits")
                    c._reopen_for_use()
                    return c
                # too old: drop it silently (no network call on the user's request path)
    STATS.bump("pool_misses")
    return TursoConnection(_open_raw())


# ------------------------------------------------------------------ public API
def connect(sqlite_path):
    """What database.get_connection() returns."""
    if backend() == "turso":
        return _connect_turso()
    connection = sqlite3.connect(sqlite_path)       # original behaviour, byte for byte
    connection.row_factory = sqlite3.Row
    return connection


def init_schema(create_tables, migrate_database, get_connection):
    """Replaces the two import-time calls at the bottom of database.py.
    SQLite: runs both, exactly as before.
    Turso : create_tables() + migrate_database() cost ~48 statements (~45 s at the measured speed),
            so they run only when the hash of their source code differs from the one stored in the
            database (table _neki_meta). Changing either function automatically re-runs them."""
    if backend() != "turso":
        create_tables()
        migrate_database()
        return "ran (sqlite)"
    try:
        src = inspect.getsource(create_tables) + inspect.getsource(migrate_database)
        schema_hash = hashlib.sha256(src.encode("utf-8")).hexdigest()[:16]
    except Exception:
        schema_hash = None
    if schema_hash:
        try:
            conn = get_connection()
            try:
                row = conn.execute("SELECT value FROM _neki_meta WHERE key = ?", ("schema_hash",)).fetchone()
            finally:
                conn.close()
            if row and row[0] == schema_hash:
                return "skipped (schema hash matches)"
        except Exception:
            pass                                    # table missing -> fall through and build the schema
    create_tables()
    migrate_database()
    if schema_hash:
        conn = get_connection()
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS _neki_meta (key TEXT PRIMARY KEY, value TEXT)")
            conn.execute("DELETE FROM _neki_meta WHERE key = ?", ("schema_hash",))
            conn.execute("INSERT INTO _neki_meta (key, value) VALUES (?, ?)", ("schema_hash", schema_hash))
            conn.commit()
        finally:
            conn.close()
    return "ran (turso)"


def render_timing_panel():
    """DEV ONLY. Call near the top of app.py. Shows what the PREVIOUS script run cost in database
    time (so it also covers screens that stop early). Does nothing unless db_timing is enabled."""
    if not timing_enabled():
        return
    import streamlit as st
    counters, recent = STATS.snapshot_and_reset()
    _CUMULATIVE["runs"] += 1
    for k in ("statements", "statement_ms", "connects", "connect_ms"):
        _CUMULATIVE[k] += counters[k]
    with st.sidebar.expander("🛠 Database timing (dev)", expanded=False):
        st.caption(f"backend: {backend()} · pool: {'on' if pool_enabled() else 'off'} "
                   f"(idle {pool_idle_seconds():g}s) · runs seen: {_CUMULATIVE['runs']}")
        st.markdown(
            f"**Previous script run** — {counters['statements']} statements, "
            f"{counters['statement_ms'] / 1000:.1f} s · commits {counters['commits']} "
            f"({counters['commit_ms'] / 1000:.1f} s) · new connections {counters['connects']} "
            f"({counters['connect_ms'] / 1000:.1f} s) · pool hits {counters['pool_hits']} / "
            f"misses {counters['pool_misses']} · stale retries {counters['stale_retries']} · "
            f"errors {counters['errors']} · background closes {counters['closes']} "
            f"({counters['close_ms'] / 1000:.1f} s, not waited for)")
        slow = sorted(recent, key=lambda r: -r[1])[:8]
        if slow:
            st.dataframe([{"kind": k, "ms": round(ms), "sql": s} for k, ms, s in slow], hide_index=True)
        st.caption("Totals since this process started: "
                   f"{_CUMULATIVE['statements']} statements, {_CUMULATIVE['statement_ms'] / 1000:.1f} s; "
                   f"{_CUMULATIVE['connects']} connections, {_CUMULATIVE['connect_ms'] / 1000:.1f} s.")
