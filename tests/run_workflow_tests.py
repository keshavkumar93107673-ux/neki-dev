"""Differential regression test.  python tests/run_workflow_tests.py <path to a COPY of neighbourhelp.db>
Runs the same 95-step scenario of Neki's REAL database.py twice (plain SQLite vs. the Turso stand-in in
tests/fake) and requires identical results and identical final table contents.
LIMIT: the stand-in is not the real Turso service; this proves adapter/code compatibility, not network behaviour."""
import json, os, subprocess, sys, tempfile
here = os.path.dirname(os.path.abspath(__file__))
src = sys.argv[1]
variants = [("sqlite baseline", "sqlite", {}),
            ("turso, pool on", "turso", {}),
            ("turso, pool off", "turso", {"NEKI_DB_POOL": "false"}),
            ("turso, stale pooled connections", "turso", {"FAKE_TURSO_DIE_AFTER_COMMIT": "1", "NEKI_DB_POOL_IDLE": "60"}),
            ("turso, 20 ms latency", "turso", {"FAKE_TURSO_LATENCY_MS": "20"})]
out = {}
tmp = tempfile.mkdtemp()
for name, backend, env in variants:
    f = os.path.join(tmp, name.replace(" ", "_").replace(",", "") + ".json")
    e = dict(os.environ, **env)
    r = subprocess.run([sys.executable, "-I", os.path.join(here, "scenario.py"), backend, src, f],
                       capture_output=True, text=True, env=e)
    if r.returncode:
        print("FAIL (crash):", name, "\n", r.stderr[-1500:]); sys.exit(1)
    print(f"[{name}] {r.stdout.strip()}")
    out[name] = json.load(open(f))
def loose(v):
    # same-second timestamps make ORDER BY created_at ties come out in a different order when timing differs
    if isinstance(v, list):
        v = [loose(x) for x in v]
        return sorted(v, key=lambda x: json.dumps(x, sort_keys=True, default=str)) if v and isinstance(v[0], dict) else v
    if isinstance(v, dict): return {k: loose(x) for k, x in v.items()}
    return v
base = out["sqlite baseline"]; bad = 0
for name, res in out.items():
    if name == "sqlite baseline": continue
    L = (lambda x: loose(x)) if "latency" in name else (lambda x: x)
    diffs = [(a, b) for a, b in zip(base["steps"], res["steps"]) if L(a) != L(b)]
    sd = [t for t in base["state"] if L(base["state"][t]) != L(res["state"][t])]
    if diffs or sd or len(base["steps"]) != len(res["steps"]):
        bad += 1; print("DIFF in", name)
        for a, b in diffs[:8]: print("  sqlite:", str(a)[:160], "\n  turso :", str(b)[:160])
        print("  tables differing:", sd)
    else:
        print("IDENTICAL:", name)
print("RESULT:", "ALL IDENTICAL" if not bad else f"{bad} variant(s) differ")
sys.exit(1 if bad else 0)
