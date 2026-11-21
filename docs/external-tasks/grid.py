"""Build a coverage grid from tasks.toml. Standard library only (Python 3.11+)."""
import argparse
import sys
import tomllib
from collections import Counter, defaultdict

PATTERNS = ["bugfix", "feature", "refactor", "perf", "investigation", "review", "design", "docs"]
DOMAINS = ["ml-compiler", "ml-runtime", "ml-training", "compiler-ir", "native-interop", "concurrency",
           "build-tooling", "agent-infra", "data-storage", "dev-env", "numerics", "web-app"]
EVIDENCE_RANK = {"validated": 0, "probed": 1, "adjacent": 2, "source": 3}
STATUS_RANK = {"active": 0, "pilot": 0, "pilot-pending": 1, "hold": 2, "reserve": 2,
               "calibration": 3, "deferred": 4, "lead": 5, "dropped": 6}
INACTIVE = {"dropped", "lead"}
REQUIRED = ["id", "track", "repo", "title", "pattern", "domains", "languages", "env", "setup",
            "grading", "evidence", "status"]
ENUMS = {
    "track": {"internal", "external"},
    "pattern": set(PATTERNS),
    "env": {"cpu", "gpu-optional", "gpu-required"},
    "grading": {"existing_tests", "new_test", "checkable_answer", "judge_only"},
    "evidence": set(EVIDENCE_RANK),
    "status": set(STATUS_RANK),
}


def load(path):
    with open(path, "rb") as f:
        tasks = tomllib.load(f).get("task", [])
    ok, seen = [], set()
    for t in tasks:
        tid = t.get("id", "?")
        missing = [k for k in REQUIRED if k not in t]
        if missing:
            print(f"warning: {tid} missing {missing}; skipped", file=sys.stderr)
            continue
        if tid in seen:
            print(f"warning: duplicate id {tid}", file=sys.stderr)
        seen.add(tid)
        for k, allowed in ENUMS.items():
            if t[k] not in allowed:
                print(f"warning: {tid} {k}={t[k]!r} not in {sorted(allowed)}", file=sys.stderr)
        for d in t["domains"]:
            if d not in DOMAINS:
                print(f"warning: {tid} unknown domain {d!r} (counted anyway)", file=sys.stderr)
        ok.append(t)
    return ok


def table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tasks")
    ap.add_argument("--min", type=int, default=1, help="internal tasks needed before a cell stops counting as thin")
    args = ap.parse_args()

    tasks = load(args.tasks)
    live = [t for t in tasks if t["status"] not in INACTIVE]
    internal = [t for t in live if t["track"] == "internal"]
    external = [t for t in live if t["track"] == "external"]

    domains = DOMAINS + sorted({d for t in live for d in t["domains"]} - set(DOMAINS))
    cell = defaultdict(lambda: {"internal": [], "external": []})
    for t in live:
        for d in t["domains"]:
            cell[(d, t["pattern"])][t["track"]].append(t)

    print(f"# Coverage: {len(internal)} internal, {len(external)} live external "
          f"({len(tasks) - len(live)} dropped/lead not counted)\n")

    print("## Pattern × domain (I = internal, E = external)\n")
    rows = []
    for d in domains:
        r = [d]
        for p in PATTERNS:
            c = cell[(d, p)]
            ni, ne = len(c["internal"]), len(c["external"])
            r.append("" if ni == ne == 0 else f"I:{ni} E:{ne}")
        rows.append(r)
    print(table(["domain"] + PATTERNS, rows))

    print(f"\n## Gaps (internal < {args.min}) with external fillers\n")
    any_gap = False
    for d in domains:
        for p in PATTERNS:
            c = cell[(d, p)]
            if len(c["internal"]) >= args.min or not c["external"]:
                continue
            any_gap = True
            fillers = sorted(c["external"], key=lambda t: (EVIDENCE_RANK[t["evidence"]], STATUS_RANK[t["status"]]))
            desc = ", ".join(f"{t['id']} ({t['evidence']}, {t['status']})" for t in fillers)
            print(f"- **{d} / {p}** (internal {len(c['internal'])}): {desc}")
    if not any_gap:
        print("_No gaps that external candidates could fill._")

    empty_internal_domains = [d for d in domains if not any(cell[(d, p)]["internal"] for p in PATTERNS)]
    print("\n## Domains with no internal tasks\n")
    print(", ".join(empty_internal_domains) or "_none_")

    def marginal(name, key, multi=False):
        ci, ce = Counter(), Counter()
        for t in internal:
            ci.update(t.get(key, []) if multi else [t.get(key, "—")])
        for t in external:
            ce.update(t.get(key, []) if multi else [t.get(key, "—")])
        keys = sorted(set(ci) | set(ce), key=lambda k: -(ci[k] + ce[k]))
        print(f"\n## By {name}\n")
        print(table([name, "internal", "external"], [[k, ci[k], ce[k]] for k in keys]))

    marginal("pattern", "pattern")
    marginal("language", "languages", multi=True)
    marginal("env", "env")
    marginal("grading", "grading")
    marginal("evidence", "evidence")
    marginal("demands", "demands", multi=True)
    marginal("familiarity", "familiarity")

    judged = [t for t in live if t["grading"] in ("checkable_answer", "judge_only")]
    if live:
        print(f"\n_{len(judged)}/{len(live)} live tasks rely on answer or judge grading._")


if __name__ == "__main__":
    main()
