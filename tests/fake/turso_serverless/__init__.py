"""TEST STAND-IN for the turso_serverless client. NOT the real client and NOT a Turso server.
It reproduces the behaviours that were verified on real Turso (see turso_compat.py) and is
deliberately STRICTER than sqlite where real Turso differs:
  * foreign keys enforced, * only int/float/str/bytes/None parameters, * own exception classes
  * that are not sqlite3.Error subclasses, * row_factory(cursor,row) honoured, * cursor.description.
Env: FAKE_TURSO_FILE (sqlite file backing the 'remote' db), FAKE_TURSO_LATENCY_MS,
     FAKE_TURSO_DIE_AFTER_COMMIT=1 (a connection fails on its first use after a commit, like a stale pooled stream), FAKE_TURSO_LOG (path)."""
import os, sqlite3, time
from .dbapi import Error, DatabaseError, IntegrityError, OperationalError, ProgrammingError

_OK = (int, float, str, bytes, type(None))
_LOGFILE = os.environ.get("FAKE_TURSO_LOG")


def _log(msg):
    if _LOGFILE:
        with open(_LOGFILE, "a") as f:
            f.write(msg + "\n")


def _lat():
    ms = float(os.environ.get("FAKE_TURSO_LATENCY_MS", "0") or 0)
    if ms:
        time.sleep(ms / 1000)


def _map(e):
    if isinstance(e, sqlite3.IntegrityError):
        return IntegrityError(str(e))
    if isinstance(e, sqlite3.OperationalError):
        return OperationalError(str(e))
    if isinstance(e, sqlite3.ProgrammingError):
        return ProgrammingError(str(e))
    return DatabaseError(str(e))


class Cursor:
    def __init__(self, conn):
        self._c = conn
        self._cur = conn._db.cursor()
        self._rows = []
        self.description = None
        self.lastrowid = None
        self.rowcount = -1

    def execute(self, sql, params=()):
        c = self._c
        if c._closed:
            raise ProgrammingError("connection closed")
        if os.environ.get("FAKE_TURSO_DIE_AFTER_COMMIT") and c._committed:
            raise OperationalError("stream expired")
        for p in params or ():
            if not isinstance(p, _OK) or isinstance(p, bool):
                raise ProgrammingError(f"unsupported parameter type {type(p).__name__}")
        _lat()
        _log("EXEC " + " ".join(sql.split())[:90])
        try:
            self._cur.execute(sql, tuple(params or ()))
        except sqlite3.Error as e:
            raise _map(e) from None
        c._last = time.time()
        self.description = self._cur.description
        self.lastrowid = self._cur.lastrowid
        self.rowcount = self._cur.rowcount
        raw = self._cur.fetchall() if self.description else []
        f = c.row_factory
        self._rows = [f(self, r) if f else r for r in raw]
        return self

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def fetchall(self):
        r, self._rows = self._rows, []
        return r

    def fetchmany(self, size=1):
        r, self._rows = self._rows[:size], self._rows[size:]
        return r

    def close(self):
        pass


class Connection:
    def __init__(self, url, token):
        self._db = sqlite3.connect(os.environ["FAKE_TURSO_FILE"], timeout=30, check_same_thread=False)
        self._db.execute("PRAGMA foreign_keys = ON")
        self.row_factory = None
        self._committed = False
        self._closed = False
        self._last = time.time()

    def cursor(self):
        return Cursor(self)

    def execute(self, sql, params=()):
        return self.cursor().execute(sql, params)

    def commit(self):
        _lat()
        try:
            self._db.commit()
            self._committed = True
        except sqlite3.Error as e:
            raise _map(e) from None

    def rollback(self):
        self._db.rollback()

    def close(self):
        _lat()
        self._closed = True
        self._db.close()


def connect(url, auth_token=None, **kw):
    if not auth_token:
        raise OperationalError("missing token")
    _log("CONNECT")
    _lat()
    return Connection(url, auth_token)
