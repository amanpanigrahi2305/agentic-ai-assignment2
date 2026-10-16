"""Assignment 2's results script: builds reports/LAB_02.json and the tables of reports/LAB_02.md
from runs/, the tracker and the fixtures. Nothing in it is typed by hand.

    python -m eval.lab02

It decides each run's success with eval/check_triage.check (section 6's rule), and
computes every field of checks/FORMATS.md, section 10.10:

  schema               counted from agent/plan_schema.json as section 10.11 counts
  fixture_validation   agent.validator.validate on every file in fixtures/plans/
  ladder, diff_s49     agent.detectors.ladder and agent.diff.diff on fixtures/traces/
  results              Part F: one entry per configuration, from its finished runs
  context              Part G: one entry per notes run on 4203, 4204 and 4206

In reports/LAB_02.md it replaces what lies between the <!-- partF-table --> and
<!-- partG-table --> markers and their /end markers, and leaves the rest alone.
"""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from pathlib import Path

import yaml

from agent.detectors import ladder, repeat_check
from agent.diff import diff
from agent.validator import validate
from eval.check_triage import check
from harness import LAB, ROOT
from harness.formats import UNFINISHED, normalize_path, parse_triage_comment
from harness.runner import is_free
from harness.trace import read_trace
from harness.tracker import Tracker

CONFIGS = ("agent", "planned_off", "planned_self", "planned_external")
NOTES_ISSUES = (4203, 4204, 4206)

# Section 10.10: a strict request carrying the schema was accepted. Mistral took the plan tool
# marked "strict": true (Part A, task 5; every planned run's plan call carries it); whether
# Mistral enforces it is another question, which is why ways/planned.py checks every plan.
STRICT_COMPILES = True


# -- the schema, counted as section 10.11 counts it ---------------------------------------
def schema_counts(schema: dict) -> dict:
    found = {"optional": 0, "unions": 0, "properties": 0, "depth": 0}

    def shapes(node: dict) -> int:
        branches = node.get("anyOf") or node.get("oneOf")
        if branches:
            return len(branches)
        kind = node.get("type")
        return len(set(kind)) if isinstance(kind, list) else 1

    def walk(node: dict, level: int, is_field: bool) -> None:
        found["depth"] = max(found["depth"], level)
        if is_field and shapes(node) > 1:
            found["unions"] += 1
        props = node.get("properties") or {}
        found["properties"] += len(props)
        found["optional"] += len(set(props) - set(node.get("required") or []))
        for child in props.values():
            walk(child, level + 1, True)
        if isinstance(node.get("items"), dict):
            walk(node["items"], level + 1, True)
        for branch in node.get("anyOf") or node.get("oneOf") or []:
            walk(branch, level, False)

    walk(schema, 1, False)
    return found


# -- runs -------------------------------------------------------------------------------------
def configuration(start: dict) -> str | None:
    if start.get("way") == "agent":
        return "agent"
    if start.get("way") == "planned":
        return f"planned_{start.get('critique') or 'off'}"
    return None


def load_runs(eval_issues: set[int]) -> tuple[dict, list[dict]]:
    """Finished runs of this assignment on a real model: Part F's by configuration, on the
    evaluation issues, and Part G's notes runs on 4203, 4204 and 4206."""
    runs: dict[str, list[dict]] = {c: [] for c in CONFIGS}
    notes: list[dict] = []
    for path in sorted((ROOT / "runs").glob("*.jsonl")):
        if path.name.startswith("_"):
            continue
        records = read_trace(path)
        if not records or records[0].get("type") != "run_start" or records[-1].get("type") != "run_end":
            continue
        start = records[0]
        if start.get("lab") != LAB or is_free(start.get("backend") or ""):
            continue
        if any(r.get("type") == "end" and r.get("terminal_reason") in UNFINISHED for r in records):
            continue
        run = {"run_id": start["run_id"], "issue": start["issue"], "sweep": start["sweep"],
               "notes": start.get("notes") or "off", "records": records}
        if start.get("way") == "notes" and start["issue"] in NOTES_ISSUES:
            notes.append(run)
        elif configuration(start) in CONFIGS and start["issue"] in eval_issues:
            runs[configuration(start)].append(run)
    return runs, notes


def nearest_rank(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(pct / 100 * len(ordered)) - 1)]


def mean(xs: list) -> float | None:
    return sum(xs) / len(xs) if xs else None


def right_text(body: str | None, answer: dict) -> bool:
    label, file = parse_triage_comment(body or "")
    return label == answer["label"] and file == normalize_path(answer["file"])


def prompt_share(calls: list[dict], purposes: tuple) -> float:
    total = sum(c["usage"]["prompt_tokens"] for c in calls)
    part = sum(c["usage"]["prompt_tokens"] for c in calls if c.get("purpose") in purposes)
    return part / total if total else 0.0


def summarize(config: str, runs: list[dict], answers: dict, tracker: Tracker, issues: list[int]) -> tuple[dict, dict]:
    """Section 10.10's fields for one configuration, and the extra rows of Part F's table."""
    planned, second = config != "agent", config in ("planned_self", "planned_external")
    per_issue, per_sweep = defaultdict(int), defaultdict(int)
    tokens, latency, plan_share, crit_share, revisions, rounds = [], [], [], [], [], []
    plan_alone = defaultdict(list)
    repeats = off_plan = changed = fixed = broken = held = 0
    ends = defaultdict(int)
    for r in runs:
        ok = check(tracker, r["run_id"], r["issue"], answers[r["issue"]])
        r["ok"] = ok
        per_issue[r["issue"]] += ok
        per_sweep[r["sweep"]] += ok
        records = r["records"]
        calls = [x for x in records if x.get("type") == "model_call"]
        tokens.append(sum(c["usage"]["prompt_tokens"] + c["usage"]["output_tokens"] for c in calls))
        latency.append(records[-1].get("elapsed_s") or 0.0)
        plan_share.append(prompt_share(calls, ("plan", "revise")))
        crit_share.append(prompt_share(calls, ("critique",)))
        plan_alone[len(calls)].append(prompt_share(calls, ("plan",)))
        repeats += bool(repeat_check(records))
        off_plan += sum(1 for x in records if x.get("type") == "off_plan")
        revisions.append(sum(1 for x in records if x.get("type") == "revision"))
        lines = [x for x in records if x.get("type") == "critique"]
        rounds.append(len(lines))
        if any(x.get("changed") for x in lines):
            changed += 1
            before = right_text(lines[0].get("draft"), answers[r["issue"]])
            fixed += (not before) and ok
            broken += before and not ok
        held += bool(lines) and lines[-1].get("result") == "fail" and not tracker.comments(run_id=r["run_id"])
        for x in records:
            if x.get("type") == "end":
                ends[x.get("terminal_reason")] += 1
    sweeps = sorted({r["sweep"] for r in runs})
    fields = {
        "runs": len(runs),
        "passes": sum(r["ok"] for r in runs),
        "per_issue": {str(i): per_issue[i] for i in issues},
        "sweep_min": min((per_sweep[s] for s in sweeps), default=None),
        "sweep_max": max((per_sweep[s] for s in sweeps), default=None),
        "mean_tokens": mean(tokens),
        "p50_latency_s": nearest_rank(latency, 50),
        "max_latency_s": max(latency, default=None),
        "plan_overhead_share": mean(plan_share) if planned else None,
        "critique_overhead_share": mean(crit_share) if second else None,
        "runs_with_repeat": repeats,
        "off_plan": off_plan if planned else None,
        "revisions_mean": mean(revisions) if planned else None,
        "revisions_max": max(revisions, default=None) if planned else None,
        "rounds_mean": mean(rounds) if second else None,
        "rounds_max": max(rounds, default=None) if second else None,
        "drafts_changed": changed if second else None,
        "drafts_fixed": fixed if second else None,
        "drafts_broken": broken if second else None,
        "drafts_held": held if second else None,
    }
    extra = {"plan_alone": {n: mean(v) for n, v in sorted(plan_alone.items())} if planned else None,
             "ends": dict(ends)}
    return fields, extra


# -- Part G ------------------------------------------------------------------------------------
def context_entry(run: dict) -> dict:
    seen, compacted, asked, questions = [], False, False, []
    for x in run["records"]:
        if x.get("type") == "tool_call":
            seen += [p for p in x.get("paths") or [] if p not in seen]
        elif x.get("type") == "compaction" and not asked:
            compacted = True
        elif x.get("type") == "question":
            asked = True
            questions.append({"path": x.get("path"), "truth": "yes" if x.get("path") in seen else "no",
                              "answer": x.get("answer")})
    return {"run_id": run["run_id"], "issue": run["issue"], "notes_shown": run["notes"] == "on",
            "compacted": compacted, "questions": questions,
            "right": sum(q["truth"] == q["answer"] for q in questions)}


# -- the tables ------------------------------------------------------------------------------------
def pct(x: float | None) -> str:
    return "" if x is None else f"{100 * x:.1f}%"


def num(x, fmt="{:.2f}") -> str:
    return "" if x is None else (fmt.format(x) if isinstance(x, float) else str(x))


def part_f_table(results: dict, extras: dict, issues: list[int]) -> str:
    cols = CONFIGS
    rows = [
        ("Passes, of 18", lambda c: f"{results[c]['passes']} of {results[c]['runs']}"),
        ("Per issue, 4201 to 4206, of 3 each", lambda c: " · ".join(str(results[c]["per_issue"][str(i)]) for i in issues)),
        ("Spread: the lowest and highest sweep, of 6", lambda c: f"{num(results[c]['sweep_min'])} to {num(results[c]['sweep_max'])}"),
        ("Tokens per run", lambda c: num(results[c]["mean_tokens"], "{:,.0f}")),
        ("Latency per run: median, and slowest", lambda c: f"{num(results[c]['p50_latency_s'], '{:.1f}')} s, {num(results[c]['max_latency_s'], '{:.1f}')} s"),
        ("Plan overhead: the mean share of prompt tokens, and how it changes with run length",
         lambda c: "" if results[c]["plan_overhead_share"] is None else
         f"{pct(results[c]['plan_overhead_share'])}; the plan call alone, by model calls a run: "
         + ", ".join(f"{n} calls {pct(v)}" for n, v in extras[c]["plan_alone"].items())),
        ("Second-pass overhead: the mean share of prompt tokens", lambda c: pct(results[c]["critique_overhead_share"])),
        ("Runs with at least one exact repeat", lambda c: num(results[c]["runs_with_repeat"])),
        ("`off_plan` lines", lambda c: num(results[c]["off_plan"])),
        ("Revisions per run: mean, and maximum", lambda c: "" if results[c]["revisions_mean"] is None else f"{results[c]['revisions_mean']:.2f}, {results[c]['revisions_max']}"),
        ("Second-pass rounds per run: mean, and maximum", lambda c: "" if results[c]["rounds_mean"] is None else f"{results[c]['rounds_mean']:.2f}, {results[c]['rounds_max']}"),
        ("Drafts changed; of those fixed, and broken", lambda c: "" if results[c]["drafts_changed"] is None else f"{results[c]['drafts_changed']}; {results[c]['drafts_fixed']}, {results[c]['drafts_broken']}"),
        ("Drafts held at the bound", lambda c: num(results[c]["drafts_held"])),
        ("How runs ended (not a 10.10 field)", lambda c: ", ".join(f"{k} {v}" for k, v in sorted(extras[c]["ends"].items()))),
    ]
    out = ["| Measure | Agent | Planned, off | Planned, self | Planned, external |", "|---|---|---|---|---|"]
    out += [f"| {name} | " + " | ".join(cell(c) for c in cols) + " |" for name, cell in rows]
    return "\n".join(out)


def part_g_table(context: list[dict]) -> str:
    out = ["| Run | Issue | Progress file shown | Compacted before the questions | Answers right, of 6 |", "|---|---|---|---|---|"]
    for e in sorted(context, key=lambda e: (e["notes_shown"], e["issue"], e["run_id"])):
        out.append(f"| `{e['run_id']}` | {e['issue']} | {'yes' if e['notes_shown'] else 'no'} | "
                   f"{'yes' if e['compacted'] else 'no'} | {e['right']} |")
    return "\n".join(out)


def replace_block(text: str, name: str, body: str) -> str:
    pattern = re.compile(rf"<!-- {name} -->.*?<!-- /{name} -->", re.DOTALL)
    return pattern.sub(lambda m: f"<!-- {name} -->\n{body}\n<!-- /{name} -->", text)


def main() -> None:
    answers = {int(k): v for k, v in yaml.safe_load((ROOT / "fixtures" / "answers.yaml").read_text())["eval"].items()}
    issues = sorted(answers)
    tracker = Tracker(ROOT)
    report_path = ROOT / "reports" / "LAB_02.json"
    report = json.loads(report_path.read_text())

    counts = schema_counts(json.loads((ROOT / "agent" / "plan_schema.json").read_text()))
    report["schema"] = {"args_representation": "args_json", "optional_fields": counts["optional"],
                        "union_types": counts["unions"], "strict_compiles": STRICT_COMPILES}

    report["fixture_validation"] = []
    for path in sorted((ROOT / "fixtures" / "plans").glob("*.json")):
        verdict = validate(json.loads(path.read_text()))
        report["fixture_validation"].append({"plan": path.name, "valid": verdict["valid"], "failures": verdict["failures"]})

    report["ladder"] = {}
    for run in ("looping", "s49"):
        folder = ROOT / "fixtures" / "traces" / run
        plan, trace = json.loads((folder / "plan.json").read_text()), read_trace(folder / "trace.jsonl")
        report["ladder"][run] = ladder(plan, trace)
        if run == "s49":
            d = diff(plan, trace)
            report["diff_s49"] = {"steps": {str(k): v for k, v in d["steps"].items()}, "extra": d["extra"]}

    runs, notes = load_runs(set(issues))
    results, extras = {}, {}
    for config in CONFIGS:
        results[config], extras[config] = summarize(config, runs[config], answers, tracker, issues)
    report["results"] = results
    report["context"] = [context_entry(r) for r in notes]
    report_path.write_text(json.dumps(report, indent=2) + "\n")

    md_path = ROOT / "reports" / "LAB_02.md"
    md = replace_block(md_path.read_text(), "partF-table", part_f_table(results, extras, issues))
    md = replace_block(md, "partG-table", part_g_table(report["context"]))
    md_path.write_text(md)

    print(json.dumps({c: {k: results[c][k] for k in ("runs", "passes", "sweep_min", "sweep_max")} for c in CONFIGS}))
    print(f"schema {report['schema']}; context entries {len(report['context'])}")


if __name__ == "__main__":
    main()
