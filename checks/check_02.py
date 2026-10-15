#!/usr/bin/env python3
"""Assignment 2 checker. Run it with `make check-02`.

It reads only the environment: your runs/ traces, the tracker's comments, your
reports/LAB_02.json and agent/plan_schema.json, and it calls your code directly
with scripted models (harness/scripted.py). It never asks a model anything and
never trusts a model's words.

Assignment 2 is scored out of 100. The checker awards the automated 84; staff read
Part F's and Part G's answers for the other 16. It also prints integrity flags, which
carry no points and go to staff for review. Every format it reads is defined in
checks/FORMATS.md, section 10.
"""

from __future__ import annotations

import copy
import importlib
import json
import sys
import tempfile
import traceback
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from harness import LAB  # noqa: E402
from harness.backends import REAL_BACKENDS  # noqa: E402
from harness.client import BudgetExceeded, ModelClient  # noqa: E402
from harness.formats import (SENTINEL, UNFINISHED, normalize_path, parse_triage_comment,  # noqa: E402
                             result_paths)
from harness.pricing import PriceSheet  # noqa: E402
from harness.runner import WayContext, is_free  # noqa: E402
from harness.scripted import (OFF_PLAN_MARK, AlwaysInvalidPlanner, DraftNamesMissingFile,  # noqa: E402
                              DraftNamesNoFile, DraftNamesSeenFile, DraftNamesUnseenFile, NoCommentPlanner,
                              OffPlanExecutor, RecordingPlanner, RefusesToRead, SchemaBreakingPlanner,
                              ScriptedTriage, SentinelSearcher, plan_tool, triage_steps)
from harness.settings import load_settings  # noqa: E402
from harness.trace import TraceWriter, read_trace  # noqa: E402
from harness.tracker import Tracker  # noqa: E402
from tools import RunContext, default_tools  # noqa: E402

CONFIGS = ("agent", "planned_off", "planned_self", "planned_external")   # Part F's four
PLANNED = CONFIGS[1:]
RUNS_PER_ISSUE = 3
NOTES_ISSUES, NOTES_RUNS = (4203, 4204, 4206), 2   # Part G: per issue, per setting of --notes
TOLERANCE = 0.01                  # "within 1%"
MISLEADING_ISSUE = 4206           # its text blames the wrong file
REJECT_ISSUE, BOUNDARY_ISSUE = 4191, 4192   # development issues: the scripted runs reveal nothing about evaluation
SPECIMEN = {("2", 2), ("3", 3), ("5", 1)}  # slide 18: step 2 needs step 4; step 3 has no outcome; step 5's tool does not exist
STRICT_LIMITS = {"optional": 24, "unions": 16, "properties": 5000, "depth": 10}


@dataclass
class Section:
    name: str
    possible: float
    earned: float = 0.0
    notes: list[str] = field(default_factory=list)
    manual: bool = False

    def note(self, text: str) -> None:
        self.notes.append(text)


def within(value, target, tol=TOLERANCE) -> bool:
    if value is None or target is None:
        return False
    try:
        return abs(float(value) - float(target)) <= max(tol * abs(float(target)), 1e-9)
    except (TypeError, ValueError):
        return False


def sid(value) -> str:
    """Step ids compared as text, so 2 and "2" are the same step."""
    return str(value)


def raised(what: str) -> str:
    return f"{what} raised:\n" + traceback.format_exc(limit=3)


def max_steps() -> int | None:
    try:
        return int(yaml.safe_load((ROOT / "agent" / "bounds.yaml").read_text())["max_steps"])
    except Exception:
        return None


# --------------------------------------------------------------------------------------
# The checker's own reading of a plan: section 10.2's four checks
# --------------------------------------------------------------------------------------

def plan_steps(plan) -> list[dict]:
    steps = plan.get("steps") if isinstance(plan, dict) else None
    return [s for s in steps if isinstance(s, dict)] if isinstance(steps, list) else []


def checker_validate(plan: dict, limit: int) -> set[tuple[str | None, int]]:
    steps = plan_steps(plan)
    tools = set(((plan.get("meta") or {}) if isinstance(plan, dict) else {}).get("tools") or [])
    position = {}
    for i, step in enumerate(steps):
        position.setdefault(sid(step.get("id")), i)
    failures = set()
    for i, step in enumerate(steps):
        tool = step.get("tool")
        if tool and tool not in tools:
            failures.add((sid(step.get("id")), 1))
        if any(position.get(sid(d), len(steps)) >= i for d in step.get("depends_on") or []):
            failures.add((sid(step.get("id")), 2))
        if not tool or not str(step.get("expected_result") or "").strip():
            failures.add((sid(step.get("id")), 3))
    if not 1 <= len(steps) <= limit:
        failures.add((None, 4))
    return failures


def their_failures(verdict) -> set[tuple[str | None, int]] | None:
    """A validate() result as a set of (step, check), or None if it is not section 10.2's shape."""
    if not isinstance(verdict, dict) or not isinstance(verdict.get("failures"), list):
        return None
    out = set()
    for f in verdict["failures"]:
        if not isinstance(f, dict) or "check" not in f:
            return None
        out.add((None if f.get("step") is None else sid(f.get("step")), int(f["check"])))
    return out


# --------------------------------------------------------------------------------------
# Runs: read every trace of this assignment, and decide success from the tracker
# --------------------------------------------------------------------------------------

def configuration(start: dict) -> str | None:
    """Part F's configuration of a run: agent, or planned_<its --critique mode>."""
    if start.get("way") == "agent":
        return "agent"
    if start.get("way") == "planned":
        return f"planned_{start.get('critique') or 'off'}"
    return None


def load_runs(eval_issues: set[int]) -> tuple[dict, list[dict], list[str]]:
    """Part F's runs by configuration, on the evaluation issues; and Part G's notes runs, on
    4203, 4204 and 4206 (a notes run anywhere else is development). A run the daily quota
    stopped is not finished, and is left out."""
    runs: dict[str, list[dict]] = {c: [] for c in CONFIGS}
    notes_runs: list[dict] = []
    notes, quota = [], []
    for path in sorted((ROOT / "runs").glob("*.jsonl")):
        if path.name.startswith("_"):
            continue
        try:
            records = read_trace(path)
        except json.JSONDecodeError:
            notes.append(f"{path.name}: not valid JSON lines, skipped")
            continue
        start = records[0] if records and records[0].get("type") == "run_start" else None
        end = records[-1] if records and records[-1].get("type") == "run_end" else None
        if not start or start.get("lab") != LAB or is_free(start.get("backend") or ""):
            continue
        config = configuration(start)
        if start.get("way") == "notes" and start.get("issue") not in NOTES_ISSUES:
            continue
        if start.get("way") != "notes" and (config not in CONFIGS or start.get("issue") not in eval_issues):
            continue
        if not end:
            notes.append(f"{path.name}: no run_end record (the run did not finish), skipped")
            continue
        if any(r.get("type") == "end" and r.get("terminal_reason") in UNFINISHED for r in records):
            quota.append(path.name)
            continue
        run = {"run_id": start["run_id"], "issue": start["issue"], "sweep": start["sweep"],
               "backend": start["backend"], "critique": start.get("critique") or "off",
               "notes": start.get("notes") or "off", "records": records}
        if start.get("way") == "notes":
            notes_runs.append(run)
        else:
            runs[config].append(run)
    if quota:
        notes.append(f"{len(quota)} runs stopped by the daily quota or by rate limits are not finished and "
                     "not counted; run the same command again to redo them")
    return runs, notes_runs, notes


def grounded_pass(tracker: Tracker, run: dict, answer: dict) -> bool:
    comments = tracker.comments(run_id=run["run_id"], issue=run["issue"])
    if len(comments) != 1:
        return False
    label, file = parse_triage_comment(comments[0]["body"])
    return label == answer["label"] and file == normalize_path(answer["file"])


def exact_repeat(records: list[dict]) -> bool:
    seen = set()
    for r in records:
        if r.get("type") == "tool_call":
            key = json.dumps([r.get("name"), r.get("input") or {}], sort_keys=True)
            if key in seen:
                return True
            seen.add(key)
    return False


def right_text(body: str | None, answer: dict) -> bool:
    label, file = parse_triage_comment(body or "")
    return label == answer["label"] and file == normalize_path(answer["file"])


def summarize(config: str, runs: list[dict], passed: dict[str, bool], issues: list[int],
              answers: dict, tracker: Tracker) -> dict:
    """Section 10.10's fields for one configuration, from the traces and the tracker."""
    per_issue_runs, per_issue_pass, per_sweep = defaultdict(int), defaultdict(int), defaultdict(int)
    plan_shares, critique_shares, revisions, rounds, tokens, latency = [], [], [], [], [], []
    changed = fixed = broken = held = 0
    for r in runs:
        ok = passed[r["run_id"]]
        per_issue_runs[r["issue"]] += 1
        per_issue_pass[r["issue"]] += ok
        per_sweep[r["sweep"]] += ok
        calls = [x for x in r["records"] if x.get("type") == "model_call"]
        total = sum(c["usage"]["prompt_tokens"] for c in calls)
        share = lambda purposes: (sum(c["usage"]["prompt_tokens"] for c in calls  # noqa: E731
                                      if c.get("purpose") in purposes) / total if total else 0.0)
        plan_shares.append(share(("plan", "revise")))
        critique_shares.append(share(("critique",)))
        tokens.append(sum(c["usage"]["prompt_tokens"] + c["usage"]["output_tokens"] for c in calls))
        latency.append(r["records"][-1].get("elapsed_s") or 0.0)
        revisions.append(sum(1 for x in r["records"] if x.get("type") == "revision"))
        lines = [x for x in r["records"] if x.get("type") == "critique"]
        rounds.append(len(lines))
        if any(x.get("changed") for x in lines):
            changed += 1
            before = right_text(lines[0].get("draft"), answers[r["issue"]])
            fixed += (not before) and ok
            broken += before and not ok
        held += bool(lines) and lines[-1].get("result") == "fail" and not tracker.comments(run_id=r["run_id"])
    sweeps = sorted({r["sweep"] for r in runs})
    n = len(runs)
    planned, second = config != "agent", config in ("planned_self", "planned_external")
    mean = lambda xs: sum(xs) / len(xs) if xs else None  # noqa: E731
    ordered = sorted(latency)
    return {
        "runs": n,
        "passes": sum(passed[r["run_id"]] for r in runs),
        "per_issue": {str(i): per_issue_pass[i] for i in issues},
        "sweep_min": min((per_sweep[s] for s in sweeps), default=None),
        "sweep_max": max((per_sweep[s] for s in sweeps), default=None),
        "mean_tokens": mean(tokens),
        "p50_latency_s": ordered[max(0, -(-len(ordered) // 2) - 1)] if ordered else None,
        "max_latency_s": max(latency, default=None),
        "plan_overhead_share": mean(plan_shares) if planned else None,
        "critique_overhead_share": mean(critique_shares) if second else None,
        "runs_with_repeat": sum(exact_repeat(r["records"]) for r in runs),
        "off_plan": sum(1 for r in runs for x in r["records"] if x.get("type") == "off_plan") if planned else None,
        "revisions_mean": mean(revisions) if planned else None,
        "revisions_max": max(revisions, default=None) if planned else None,
        "rounds_mean": mean(rounds) if second else None,
        "rounds_max": max(rounds, default=None) if second else None,
        "drafts_changed": changed if second else None,
        "drafts_fixed": fixed if second else None,
        "drafts_broken": broken if second else None,
        "drafts_held": held if second else None,
        "_per_issue_runs": dict(per_issue_runs),
    }


# --------------------------------------------------------------------------------------
# The probe: your make_plan and revise_plan, called with a recording client
# --------------------------------------------------------------------------------------

def issue_texts() -> dict[int, dict]:
    tracker = Tracker(ROOT)
    out = {}
    for n in tracker.issue_numbers("eval") + tracker.issue_numbers("dev"):
        issue = tracker.issue(n)
        out[n] = {"sentinels": SENTINEL.findall(issue["body"]), "title": str(issue.get("title", ""))}
    return out


def probe_planner(tmp: Path) -> dict:
    out = {"plan_error": None, "revise_error": None, "plan_requests": [], "revise_requests": [],
           "plans": {}, "keeps_done": None, "keeps_note": "", "retries_failed": None, "plan_purpose": None,
           "revise_purpose": None}
    try:
        from agent.plan import make_plan, revise_plan
    except Exception:
        out["plan_error"] = out["revise_error"] = raised("importing agent/plan.py")
        return out
    prices = PriceSheet(ROOT / "pricing.yaml")
    schemas = default_tools(RunContext("check-probe", Tracker(ROOT, state_dir=tmp / "probe"),
                                       ROOT / "fixtures" / "repo")).schemas

    # make_plan, on every issue
    recorder = RecordingPlanner()
    trace_path = tmp / "probe-plan.jsonl"
    trace = TraceWriter(trace_path, "check-probe-plan", {"lab": LAB, "way": "check"})
    for n in sorted(issue_texts()):
        before = len(recorder.requests)
        try:
            out["plans"][n] = make_plan(ModelClient(recorder, prices), n, copy.deepcopy(schemas), trace=trace)
        except NotImplementedError:
            out["plan_error"] = "agent/plan.py: make_plan is not written yet"
            break
        except Exception:
            out["plan_error"] = raised(f"make_plan(client, {n}, tool_schemas)")
            break
        out["plan_requests"] += [(n, req) for req in recorder.requests[before:]]
    trace.run_end({}, None)
    out["plan_purpose"] = [r.get("purpose") for r in read_trace(trace_path) if r["type"] == "model_call"]
    if out["plan_error"]:
        out["revise_error"] = "revise_plan was not tried: make_plan must work first"
        return out

    # revise_plan: step 1 done, step 2 failed, its query carrying a sentinel
    texts = issue_texts()
    trace_path = tmp / "probe-revise.jsonl"
    trace = TraceWriter(trace_path, "check-probe-revise", {"lab": LAB, "way": "check"})
    keeps, retries = [], []
    for n in (MISLEADING_ISSUE, BOUNDARY_ISSUE):
        plan = copy.deepcopy(out["plans"].get(n))
        steps = plan_steps(plan)
        if len(steps) < 2:
            out["revise_error"] = f"make_plan returned fewer than two steps for issue {n}, so revise_plan was not tried"
            break
        steps[0]["status"], steps[1]["status"] = "done", "failed"
        sentinel = (texts[n]["sentinels"] or ["SNTL-MISSING"])[0]
        step_results = [
            {"id": steps[0].get("id"), "tool": steps[0].get("tool"), "status": "done", "count": 1, "paths": [],
             "error_code": None, "args": {"number": n}},
            {"id": steps[1].get("id"), "tool": steps[1].get("tool"), "status": "failed", "count": 0, "paths": [],
             "error_code": "no_matches", "args": {"query": f"{sentinel} {texts[n]['title']}"}},
        ]
        given = copy.deepcopy(plan)
        recorder = RecordingPlanner(mode="revise")
        try:
            revised = revise_plan(ModelClient(recorder, prices), plan, step_results, trace=trace)
        except NotImplementedError:
            out["revise_error"] = "agent/plan.py: revise_plan is not written yet"
            break
        except Exception:
            out["revise_error"] = raised(f"revise_plan(client, plan, step_results) for issue {n}")
            break
        out["revise_requests"] += [(n, req) for req in recorder.requests]
        done_id = sid(steps[0].get("id"))
        before = next((s for s in plan_steps(given) if sid(s.get("id")) == done_id), {})
        after = next((s for s in plan_steps(revised) if sid(s.get("id")) == done_id), None)
        strip = lambda s: {k: v for k, v in (s or {}).items() if k != "status"}  # noqa: E731
        if after is None:
            keeps.append(False)
            out["keeps_note"] = f"issue {n}: step {done_id}, which had run, is missing from the revised plan"
        elif strip(after) != strip(before):
            keeps.append(False)
            out["keeps_note"] = (f"issue {n}: step {done_id}, which had run, came back changed: "
                                 f"{json.dumps(strip(before))[:160]} became {json.dumps(strip(after))[:160]}")
        else:
            keeps.append(True)
        failed_id = sid(steps[1].get("id"))
        was = next((s for s in plan_steps(given) if sid(s.get("id")) == failed_id), {})
        now = next((s for s in plan_steps(revised) if sid(s.get("id")) == failed_id), None)
        retries.append(now is not None and strip(now) != strip(was))
    trace.run_end({}, None)
    out["revise_purpose"] = [r.get("purpose") for r in read_trace(trace_path) if r["type"] == "model_call"]
    out["keeps_done"] = bool(keeps) and all(keeps) and not out["revise_error"]
    out["retries_failed"] = bool(retries) and all(retries) and not out["revise_error"]
    return out


def leaks(requests: list[tuple[int, dict]], texts: dict) -> tuple[list[str], list[str]]:
    """Sentinels found in requests (scored), and titles (noted)."""
    found, titles = [], []
    for n, request in requests:
        blob = json.dumps(request)
        for m, t in texts.items():
            for s in t["sentinels"]:
                if s in blob:
                    found.append(f"issue {m}'s sentinel {s} is in a request made for issue {n}")
            if t["title"] and t["title"] in blob:
                titles.append(f"issue {m}'s title is in a request made for issue {n}")
    return sorted(set(found)), sorted(set(titles))


# --------------------------------------------------------------------------------------
# Schema compiles
# --------------------------------------------------------------------------------------

def schema_report(schema: dict) -> dict:
    """Walk a plan schema: strict-mode shape, counts and sizes (section 10.11)."""
    defs = {**(schema.get("definitions") or {}), **(schema.get("$defs") or {})}
    found = {"loose_objects": [], "not_required": [], "free_form": [], "optional": 0, "unions": 0,
             "properties": 0, "depth": 0}

    def deref(node, seen=()):
        while isinstance(node, dict) and "$ref" in node:
            name = str(node["$ref"]).split("/")[-1]
            if name in seen:
                return {}
            seen = (*seen, name)
            node = defs.get(name, {})
        return node if isinstance(node, dict) else {}

    def shapes(node) -> int:
        branches = node.get("anyOf") or node.get("oneOf")
        if branches:
            return len(branches)
        kind = node.get("type")
        return len(set(kind)) if isinstance(kind, list) else 1

    def kinds(node) -> set:
        kind = node.get("type")
        return set(kind) if isinstance(kind, list) else ({kind} if kind else set())

    def walk(node, path, level, is_field):
        node = deref(node)
        found["depth"] = max(found["depth"], level)
        if is_field and shapes(node) > 1:
            found["unions"] += 1
        props = node.get("properties")
        if "object" in kinds(node) or props is not None:
            if not props:
                found["free_form"].append(path or "(the root)")
            else:
                found["properties"] += len(props)
                if node.get("additionalProperties") is not False:
                    found["loose_objects"].append(path or "(the root)")
                missing = sorted(set(props) - set(node.get("required") or []))
                found["optional"] += len(missing)
                found["not_required"] += [f"{path}.{m}" if path else m for m in missing]
                for name, child in props.items():
                    walk(child, f"{path}.{name}" if path else name, level + 1, True)
        if isinstance(node.get("items"), dict):
            walk(node["items"], f"{path}[]", level + 1, True)
        for i, branch in enumerate(node.get("anyOf") or node.get("oneOf") or []):
            walk(branch, f"{path}|{i}", level, False)

    walk(schema, "", 1, False)
    text = json.dumps(schema)
    found["representation"] = "args_json" if '"args_json"' in text else (
        "oneOf" if ('"oneOf"' in text or '"anyOf"' in text) else None)
    return found


def provider_has_strict() -> bool:
    """Anthropic and OpenAI itself have a strict mode; another OpenAI-compatible endpoint may not."""
    settings = load_settings(ROOT / "settings.yaml")
    if settings.provider == "anthropic":
        return True
    return settings.provider == "openai-compatible" and (not settings.base_url or "api.openai.com" in settings.base_url)


def check_schema(report: dict, probe: dict, runs: dict) -> Section:
    s = Section("Schema compiles", 5)
    path = ROOT / "agent" / "plan_schema.json"
    try:
        schema = json.loads(path.read_text())
    except FileNotFoundError:
        s.note("agent/plan_schema.json is missing: Part A, task 1")
        return s
    except json.JSONDecodeError as exc:
        s.note(f"agent/plan_schema.json is not valid JSON: {exc}")
        return s
    if not isinstance(schema, dict) or not schema.get("properties"):
        s.note("agent/plan_schema.json is not an object schema with properties")
        return s
    found = schema_report(schema)

    # 1. Strict shape: every object closed, every field required, nothing free-form. 2 points.
    shape = not found["loose_objects"] and not found["not_required"] and not found["free_form"]
    s.earned += 2.0 * shape
    for key, what in (("loose_objects", "objects without additionalProperties: false"),
                      ("not_required", "fields not listed as required (make them required, and nullable)"),
                      ("free_form", "free-form objects, with no fixed properties")):
        if found[key]:
            s.note(f"{what}: {', '.join(found[key][:6])}")

    # 2. OpenAI's size limits and Anthropic's budgets. 1 point.
    sizes = found["properties"] <= STRICT_LIMITS["properties"] and found["depth"] <= STRICT_LIMITS["depth"]
    if not sizes:
        s.note(f"{found['properties']} object properties and {found['depth']} levels of nesting: "
               f"the limits are {STRICT_LIMITS['properties']:,} and {STRICT_LIMITS['depth']}")
    budget = found["optional"] <= STRICT_LIMITS["optional"] and found["unions"] <= STRICT_LIMITS["unions"]
    s.earned += 1.0 * (sizes and budget)
    s.note(f"counted: optional fields {found['optional']} (at most {STRICT_LIMITS['optional']}), "
           f"union types {found['unions']} (at most {STRICT_LIMITS['unions']})")

    # 3. Your report counts the same. 1 point.
    mine = report.get("schema") or {}
    wrong = [k for k, v in (("optional_fields", found["optional"]), ("union_types", found["unions"]))
             if mine.get(k) != v]
    if found["representation"] and mine.get("args_representation") != found["representation"]:
        wrong.append(f"args_representation (your schema uses {found['representation']})")
    s.earned += 1.0 * (not wrong)
    if wrong:
        s.note(f"reports/LAB_02.json schema disagrees with the file on {', '.join(wrong)}")

    # 4. The planner offers this schema; a strict request carrying it was accepted. 1 point.
    offered = [t for _, req in probe["plan_requests"] for t in (req.get("tools") or [])
               if t.get("input_schema") == schema]
    strict = mine.get("strict_compiles", "missing")
    accepted = any(c.get("purpose") == "plan" for config in PLANNED for r in runs[config]
                   if r["backend"] in REAL_BACKENDS
                   for c in r["records"] if c.get("type") == "model_call")
    if not offered:
        s.note("make_plan's request offers no tool whose input_schema is agent/plan_schema.json"
               + (f" ({probe['plan_error'].splitlines()[0]})" if probe["plan_error"] else ""))
    elif strict is None and not provider_has_strict():
        s.earned += 1.0
        s.note("strict_compiles is null: your vendor has no strict mode")
    elif strict is None:
        s.note("strict_compiles is null, but your provider has a strict mode (Anthropic, and OpenAI itself): "
               "send one strict request carrying the schema, and record whether it was accepted")
    elif strict is True and all(t.get("strict") is True for t in offered) and accepted:
        s.earned += 1.0
        s.note("the plan tool is marked strict, and your planned runs show its requests were accepted")
    elif strict is True:
        s.note("strict_compiles is true, but " + ("the plan tool is not marked \"strict\": true"
                                                   if not all(t.get("strict") is True for t in offered)
                                                   else "no planned run on a real model shows a plan call"))
    else:
        s.note(f"strict_compiles is {strict!r}: true when a strict request carrying the schema was accepted, "
               "null when your vendor has no strict mode")
    return s


# --------------------------------------------------------------------------------------
# Plan before action
# --------------------------------------------------------------------------------------

def check_plan_first(runs: dict, notes_runs: list[dict]) -> Section:
    s = Section("Plan before action", 6)
    planned = [r for config in PLANNED for r in runs[config]] + notes_runs
    if not planned:
        s.note("no finished planned or notes runs")
        return s
    late = []
    for r in planned:
        types = [(x.get("type"), x.get("version")) for x in r["records"]]
        first_tool = next((i for i, (t, _) in enumerate(types) if t == "tool_call"), None)
        first_plan = next((i for i, (t, v) in enumerate(types) if t == "plan" and v == 1), None)
        if first_tool is not None and (first_plan is None or first_plan > first_tool):
            late.append(r["run_id"])
    if late:
        s.note(f"{len(late)} of {len(planned)} planned and notes runs have a tool call before the plan's "
               f"version 1 line, e.g. {late[0]}")
    else:
        s.earned = 6.0
        s.note(f"in all {len(planned)} planned and notes runs, version 1's plan line precedes the first tool call")
    return s


# --------------------------------------------------------------------------------------
# Plan before untrusted text
# --------------------------------------------------------------------------------------

def check_untrusted(probe: dict) -> Section:
    s = Section("Plan before untrusted text", 8)
    texts = issue_texts()
    missing = [n for n, t in texts.items() if len(t["sentinels"]) != 1]
    if missing:
        s.note(f"issues without exactly one sentinel: {missing}. Restore fixtures/issues/")
        return s
    for half, error, requests, purpose, want in (
            ("make_plan", probe["plan_error"], probe["plan_requests"], probe["plan_purpose"], "plan"),
            ("revise_plan", probe["revise_error"], probe["revise_requests"], probe["revise_purpose"], "revise")):
        if error:
            s.note(error)
            continue
        if not requests:
            s.note(f"{half} made no model call through the client it was given")
            continue
        found, titles = leaks(requests, texts)
        if found:
            s.note(f"{half}: {found[0]}" + (f" (and {len(found) - 1} more)" if len(found) > 1 else ""))
        else:
            s.earned += 4.0
            s.note(f"{half}: {len(requests)} requests, no sentinel in any")
        for t in titles[:1]:
            s.note(f"{half}: {t} (no points; the request should carry nothing from the issue)")
        if purpose is not None and want not in purpose:
            s.note(f"{half} did not trace its call with purpose={want!r} when given a trace "
                   "(no points here; Part F's overheads need it)")
    return s


# --------------------------------------------------------------------------------------
# Validator
# --------------------------------------------------------------------------------------

def hidden_plans(limit: int) -> list[tuple[str, dict, set]]:
    """Plans with one planted defect each, and the (step, check) each must produce."""
    tools = ["read_issue", "search_repo", "read_file", "post_comment"]

    def plan(edit):
        steps = triage_steps(4192)
        edit(steps)
        return {"meta": {"model": None, "prompt": None, "tools": list(tools)}, "steps": steps}

    def set_(i, key, value):
        return lambda steps: steps[i].__setitem__(key, value)

    long = {"meta": {"model": None, "prompt": None, "tools": list(tools)},
            "steps": [{"id": 1, "action": "read the issue", "tool": "read_issue", "args": {"number": 4192},
                       "depends_on": [], "expected_result": "the issue", "status": "pending"}]
            + [{"id": i, "action": f"search, attempt {i - 1}", "tool": "search_repo", "args": {"query": "$fill"},
                "depends_on": [i - 1], "expected_result": "at least one path", "status": "pending"}
               for i in range(2, limit + 2)]}
    return [
        ("a tool not in the plan's list", plan(set_(2, "tool", "open_file")), {("3", 1)}),
        ("a dependency on a later step", plan(set_(1, "depends_on", [3])), {("2", 2)}),
        ("a dependency on a step that does not exist", plan(set_(3, "depends_on", [1, 9])), {("4", 2)}),
        ("a step that depends on itself", plan(set_(2, "depends_on", [3])), {("3", 2)}),
        ("a step with no tool", plan(set_(2, "tool", None)), {("3", 3)}),
        ("a step with no expected result", plan(set_(1, "expected_result", "")), {("2", 3)}),
        (f"{limit + 1} steps, one over max_steps", long, {(None, 4)}),
        ("no steps at all", {"meta": {"model": None, "prompt": None, "tools": list(tools)}, "steps": []}, {(None, 4)}),
    ]


def check_validator(report: dict) -> Section:
    s = Section("Validator", 10)
    try:
        from agent.validator import validate
    except Exception:
        s.note(raised("importing agent/validator.py"))
        return s
    limit = max_steps()
    if not limit:
        s.note("agent/bounds.yaml has no max_steps the checker can read")
        return s

    def run(plan, what):
        try:
            return their_failures(validate(copy.deepcopy(plan))), None
        except NotImplementedError:
            return None, "agent/validator.py: validate is not written yet"
        except Exception:
            return None, raised(f"validate() on {what}")

    folder = ROOT / "fixtures" / "plans"
    # 1. Slide 18's specimen: three rejects, each by its own check, and check 4 passes. 3 points.
    got, error = run(json.loads((folder / "s18_specimen.json").read_text()), "s18_specimen.json")
    if error:
        s.note(error)
        return s
    if got is None:
        s.note("validate() must return {\"valid\": bool, \"failures\": [{\"step\": id, \"check\": n}]}")
        return s
    s.earned += sum(0.5 for f in SPECIMEN if f in got) + 1.5 * (got == SPECIMEN)
    if got != SPECIMEN:
        s.note(f"s18_specimen.json: want (step, check) {sorted(SPECIMEN)} and nothing else, "
               f"so check 4 passes; got {sorted(got, key=str)}")

    # 2. Hidden plans, one planted defect each. 0.75 points each.
    rejected = 0
    for what, plan, want in hidden_plans(limit):
        got, error = run(plan, what)
        rejected += bool(got)
        if got is not None and {c for _, c in got} == {c for _, c in want} and want <= got:
            s.earned += 0.75
        else:
            s.note(f"a hidden plan with {what}: want {sorted(want, key=str)}, got "
                   + (error.splitlines()[0] if error else str(sorted(got or [], key=str))))

    # 3. The good plans: valid, no failures. 0.5 points each, once the validator can reject anything.
    for name in ("good_triage.json", "good_export_fix.json"):
        got, error = run(json.loads((folder / name).read_text()), name)
        if got == set() and rejected:
            s.earned += 0.5
        elif got == set():
            s.note(f"{name} passes, but so does every hidden plan: a validator that rejects nothing earns nothing")
        else:
            s.note(f"{name} is a good plan, but got {error.splitlines()[0] if error else sorted(got or [], key=str)}")

    # Your report's fixture_validation (no points).
    mine = {e.get("plan"): e for e in report.get("fixture_validation") or [] if isinstance(e, dict)}
    for path in sorted(folder.glob("*.json")):
        if path.name not in mine:
            s.note(f"reports/LAB_02.json fixture_validation has no entry for {path.name} (no points)")
    return s


# --------------------------------------------------------------------------------------
# Reject exit and boundary: your planned way, against scripted models
# --------------------------------------------------------------------------------------

class WatchedTools:
    """The run's tool registry, with a look at the progress file before every call."""

    def __init__(self, tools, progress: Path):
        self._tools, self._progress = tools, progress
        self.snapshots: list[tuple[list[str], dict | None]] = []   # (paths returned before this call, the file then)
        self._returned: list[str] = []

    @property
    def schemas(self):
        return self._tools.schemas

    def names(self):
        return self._tools.names()

    def call(self, name, tool_input):
        try:
            state = json.loads(self._progress.read_text()) if self._progress.exists() else None
        except (OSError, json.JSONDecodeError):
            state = {"_unreadable": True}
        self.snapshots.append((list(self._returned), state))
        result = self._tools.call(name, tool_input)
        self._returned += result_paths(name, tool_input, result.content, result.is_error)
        return result


def scripted_run(backend, issue: int, tmp: Path, label: str, *, way: str = "planned", critique: str = "off",
                 notes: str = "off") -> tuple[list[dict], list[dict], str | None, object]:
    settings = load_settings(ROOT / "settings.yaml")
    run_id = f"check-{label}-{uuid.uuid4().hex[:6]}"
    trace_path = tmp / f"{run_id}.jsonl"
    trace = TraceWriter(trace_path, run_id, {"lab": LAB, "way": way, "issue": issue, "sweep": 0,
                                             "backend": f"harness.scripted:{type(backend).__name__}",
                                             "critique": critique, "notes": notes})
    tracker = Tracker(ROOT, state_dir=tmp / f"tracker-{label}")
    client = ModelClient(backend, PriceSheet(ROOT / "pricing.yaml"), session_ceiling=settings.session_token_ceiling)
    progress = tmp / f"{run_id}.progress.json"
    if hasattr(backend, "watch"):
        backend.watch = progress
    tools = WatchedTools(default_tools(RunContext(run_id, tracker, ROOT / "fixtures" / "repo")), progress)
    ctx = WayContext(run_id, issue, client, tools, trace, tracker, settings, ROOT,
                     critique=critique, notes=notes, runs_dir=tmp)
    error = None
    try:
        importlib.import_module(f"ways.{way}").run(ctx)
    except NotImplementedError:
        error = "NotImplementedError"
    except BudgetExceeded:
        error = "BudgetExceeded"
    except Exception:
        error = traceback.format_exc(limit=3)
    trace.run_end(client.totals(), error)
    return read_trace(trace_path), tracker.comments(run_id=run_id), error, tools


def planned_constant(name: str, module: str = "ways.planned"):
    try:
        value = getattr(importlib.import_module(module), name, None)
    except Exception:
        return None
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def explain(error: str | None, way: str = "planned") -> str:
    if error == "NotImplementedError":
        return f"ways/{way}.py: run is not written yet"
    if error == "BudgetExceeded":
        return "the run went on until the harness's token ceiling stopped it: nothing bounded it"
    return "your way raised:\n" + (error or "")


def check_reject_exit(tmp: Path) -> Section:
    s = Section("Reject exit", 8)
    backend = AlwaysInvalidPlanner()
    try:
        records, comments, error, _ = scripted_run(backend, REJECT_ISSUE, tmp, "reject")
    except Exception:
        s.note(raised("the reject-exit run"))
        return s
    if error:
        s.note(explain(error))
        return s
    ends = [r.get("terminal_reason") for r in records if r.get("type") == "end"]
    tool_calls = [r for r in records if r.get("type") == "tool_call"]
    if ends == ["escalated"]:
        s.earned += 1.5
    else:
        s.note(f"with a planner that only writes invalid plans the run ended {ends}; want escalated")
    if not tool_calls:
        s.earned += 1.5
    else:
        s.note(f"{len(tool_calls)} tool calls ran from plans the validator rejects, the first {tool_calls[0].get('name')}")
    if not comments:
        s.earned += 0.5
    else:
        s.note(f"{len(comments)} comments reached the tracker for that run")
    bound = planned_constant("MAX_REPLANS")
    if bound is None:
        s.note("ways/planned.py: MAX_REPLANS must be a whole number (your re-plan bound)")
    elif backend.plan_calls == bound + 1:
        s.earned += 1.5
        s.note(f"escalated after {backend.plan_calls} planner calls: one plan and MAX_REPLANS = {bound} re-plans")
    else:
        s.note(f"{backend.plan_calls} planner calls; with MAX_REPLANS = {bound} there should be {bound + 1}")

    # Plans that pass the four checks but break your schema, or end without post_comment. 1.5 points each.
    for planner, what, fix in (
            (SchemaBreakingPlanner(), "break your schema (no action, an extra property)",
             "check the plan against agent/plan_schema.json (harness.schema.errors) before the four checks"),
            (NoCommentPlanner(), "do not end with post_comment",
             "with the schema check, reject a plan whose last step is not post_comment")):
        try:
            records, comments, error, _ = scripted_run(planner, REJECT_ISSUE, tmp, planner.name)
        except Exception:
            s.note(raised(f"the {planner.name} run"))
            continue
        ends = [r.get("terminal_reason") for r in records if r.get("type") == "end"]
        tool_calls = [r for r in records if r.get("type") == "tool_call"]
        if not error and ends == ["escalated"] and not tool_calls and not comments:
            s.earned += 1.5
            s.note(f"plans that {what} were rejected: escalated after {planner.plan_calls} planner calls")
        else:
            s.note(f"with a planner whose plans pass the four checks but {what}, the run ended {ends} after "
                   f"{len(tool_calls)} tool calls: {fix}" + (f"\n{explain(error)}" if error else ""))
    return s


def check_boundary(tmp: Path) -> Section:
    s = Section("Boundary", 8)
    backend = OffPlanExecutor()
    try:
        records, comments, error, _ = scripted_run(backend, BOUNDARY_ISSUE, tmp, "boundary")
    except Exception:
        s.note(raised("the boundary run"))
        return s
    if error in ("NotImplementedError", "BudgetExceeded"):
        s.note(explain(error))
        return s
    if not backend.off_plan_calls:
        s.note("your executor never asked the model to fill in a step, so nothing could go off plan: the "
               "scripted planner marks search terms, the path and the comment \"$fill\" (checks/FORMATS.md, 10.1)"
               + (f"\n{explain(error)}" if error else ""))
        return s
    off = [r for r in records if r.get("type") == "off_plan"]
    ran = [r for r in records if r.get("type") == "tool_call" and OFF_PLAN_MARK in json.dumps(r.get("input"))]
    if off:
        s.earned += 3.0
    else:
        s.note(f"the scripted executor tried {len(backend.off_plan_calls)} off-plan calls, the first "
               f"{backend.off_plan_calls[0]['name']}; the trace has no off_plan line")
    if not ran:
        s.earned += 3.0
    else:
        s.note(f"{len(ran)} off-plan calls ran, the first {ran[0].get('name')}: refuse a call that is not the step's tool")
    if not comments:
        s.earned += 2.0
    else:
        s.note(f"the tracker changed: {len(comments)} comments from that run")
    if error:
        s.note("no points lost, but your way raised; halt a step with trace.end instead:\n" + error)
    return s


# --------------------------------------------------------------------------------------
# Revisions
# --------------------------------------------------------------------------------------

def check_revisions(probe: dict, runs: dict) -> Section:
    s = Section("Revision", 6)
    # 1. revise_plan keeps a step that already ran. 1.5 points.
    if probe["revise_error"]:
        s.note(probe["revise_error"])
    else:
        if probe["keeps_done"]:
            s.earned += 1.0
            s.note("revise_plan kept the step that was done, though the scripted reviser rewrote it")
        else:
            s.note(probe["keeps_note"] or "revise_plan did not keep the step that was done")
        if probe["retries_failed"]:
            s.earned += 0.5
        else:
            s.note("revise_plan did not let the reviser change the step that failed: a failed step may be "
                   "changed to retry it")

    # 2 to 4. Every planned run (on 4206 alone the checkpoint may never fire, which
    # would make these checks pass without testing anything).
    on_issue = [r for config in PLANNED for r in runs[config]]
    if not on_issue:
        s.note("no finished planned runs")
        return s
    limit = max_steps() or 0
    bound = planned_constant("MAX_REVISIONS")
    over, invalid, stray, misplaced, total = [], [], [], [], 0
    for r in on_issue:
        revisions = sum(1 for x in r["records"] if x.get("type") == "revision")
        total += revisions
        if bound is None or revisions > bound:
            over.append((r["run_id"], revisions))
        last_tool = None
        for x in r["records"]:
            if x.get("type") == "tool_call":
                last_tool = x.get("name")
            elif x.get("type") == "revision" and last_tool != "search_repo":
                misplaced.append((r["run_id"], last_tool))
        active = None
        for x in r["records"]:
            if x.get("type") == "plan":
                active = x.get("plan") or {}
                if (x.get("version") or 1) >= 2 and checker_validate(active, limit):
                    invalid.append((r["run_id"], x.get("version")))
            elif x.get("type") == "tool_call" and active is not None:
                tools_by_id = {sid(st.get("id")): st.get("tool") for st in plan_steps(active)}
                step = x.get("plan_step")
                if step is None or tools_by_id.get(sid(step)) != x.get("name"):
                    stray.append((r["run_id"], f"{x.get('name')} (plan_step {step})"))
    s.note(f"{len(on_issue)} planned runs, {total} revisions")
    if bound is None:
        s.note("ways/planned.py: MAX_REVISIONS must be a whole number (your revision bound)")
    elif bound < 1:
        s.note("ways/planned.py: MAX_REVISIONS is 0, which allows no revision; Part C's checkpoints need at least 1")
    elif not over and not misplaced:
        s.earned += 1.5
    elif over:
        s.note(f"{len(over)} runs exceed MAX_REVISIONS = {bound}, e.g. {over[0][0]} with {over[0][1]}")
    else:
        s.note(f"{len(misplaced)} revisions do not follow a search: the checkpoint is after a search step, "
               f"e.g. in {misplaced[0][0]} after {misplaced[0][1]}")
    if not invalid:
        s.earned += 1.5
    else:
        s.note(f"{len(invalid)} logged revisions fail the four checks, e.g. {invalid[0][0]} version {invalid[0][1]}")
    if not stray:
        s.earned += 1.5
    else:
        s.note(f"{len(stray)} tool calls do not name, as plan_step, a step of the plan version active when "
               f"they ran whose tool they call, e.g. {stray[0][1]} in {stray[0][0]}: pass "
               "ctx.call_tool(..., plan_step=<the step's id>)")
    return s


# --------------------------------------------------------------------------------------
# Second pass
# --------------------------------------------------------------------------------------

def critique_calls(records: list[dict]) -> list[dict]:
    return [r for r in records if r.get("type") == "model_call" and r.get("purpose") == "critique"]


def critique_lines(records: list[dict]) -> list[dict]:
    return [r for r in records if r.get("type") == "critique"]


def check_second_pass(runs: dict, tmp: Path) -> Section:
    s = Section("Second pass", 10)
    rounds = planned_constant("MAX_ROUNDS")
    if rounds not in (1, 2):
        s.note(f"ways/planned.py: MAX_ROUNDS must be 1 or 2, the same bound in both modes; it is {rounds}")

    def play(backend, critique, label):
        try:
            records, comments, error, _ = scripted_run(backend, BOUNDARY_ISSUE, tmp, label, critique=critique)
        except Exception:
            return None, None, raised(f"the {label} run")
        if error in ("NotImplementedError", "BudgetExceeded"):
            return None, None, explain(error)
        return records, comments, error

    # 1. off: no critique call and no critique line, one comment; and the same in your planned_off runs. 1.5 points.
    records, comments, error = play(DraftNamesSeenFile(), "off", "second-pass-off")
    if records is None:
        s.note(error)
        return s
    recorded = [r["run_id"] for r in runs["planned_off"] if critique_calls(r["records"]) or critique_lines(r["records"])]
    if not critique_calls(records) and not critique_lines(records) and len(comments) == 1 and not recorded:
        s.earned += 1.5
    else:
        s.note("off mode: " + (f"{len(critique_calls(records))} critique calls and {len(critique_lines(records))} "
                               f"critique lines, {len(comments)} comments posted (want 0, 0 and 1)"
                               if not recorded else f"your planned_off run {recorded[0]} has a critique call or line"))
    if error:
        s.note("off mode: your way raised:\n" + error)

    # 2 to 5. external, against three drafts.
    held_ok = True
    for backend, label, want in ((DraftNamesMissingFile(), "a path that does not exist", "fail"),
                                 (DraftNamesUnseenFile(), "a path this run never saw", "fail"),
                                 (DraftNamesNoFile(), "label bug with file none", "fail"),
                                 (DraftNamesSeenFile(), "a path this run saw", "pass")):
        records, comments, error = play(backend, "external", f"second-pass-{backend.name}")
        if records is None:
            s.note(f"external, {label}: {error}")
            held_ok = False
            continue
        lines, calls = critique_lines(records), critique_calls(records)
        ends = [r.get("terminal_reason") for r in records if r.get("type") == "end"]
        first = lines[0] if lines else {}
        if want == "fail":
            revised = rounds is not None and (rounds < 2 or calls)
            if first.get("result") == "fail" and first.get("mode") == "external" and revised:
                s.earned += 1.0
            else:
                s.note(f"external, a draft naming {label} ({backend.DRAFT_PATH}): first critique line {first or 'none'}"
                       + ("" if revised else "; it was not rewritten, though a round remained"))
            if comments or ends != ["escalated"] or len(lines) > (rounds or 0) or (lines and lines[-1].get("result") != "fail"):
                held_ok = False
                s.note(f"external, a draft naming {label}: still failing at the bound it must be held: "
                       f"{len(comments)} comments posted, the run ended {ends}, {len(lines)} critique lines")
        else:
            if first.get("result") == "pass" and len(lines) == 1 and not calls and len(comments) == 1:
                s.earned += 1.5
            else:
                s.note(f"external, a draft naming {label}: want one critique line that passes, no model call for "
                       f"the check, and one comment; got {len(lines)} lines (first {first.get('result')}), "
                       f"{len(calls)} critique calls, {len(comments)} comments")
        if error:
            s.note(f"external, {label}: your way raised:\n{error}")
    if held_ok:
        s.earned += 2.0

    # 6. Your runs: rounds within MAX_ROUNDS, each a critique line of the run's mode; a draft that
    # still failed was not posted; no run posted more than one comment. 2 points.
    tracker = Tracker(ROOT)
    bad = []
    second = [r for c in ("planned_self", "planned_external") for r in runs[c]]
    for r in [x for c in PLANNED for x in runs[c]]:
        lines = critique_lines(r["records"])
        posted = tracker.comments(run_id=r["run_id"])
        if len(posted) > 1:
            bad.append(f"{r['run_id']} posted {len(posted)} comments")
        elif rounds is not None and len(lines) > rounds:
            bad.append(f"{r['run_id']} has {len(lines)} critique lines, over MAX_ROUNDS = {rounds}")
        elif any(x.get("mode") != r["critique"] for x in lines):
            bad.append(f"{r['run_id']}: a critique line's mode is not the run's --critique {r['critique']}")
        elif lines and lines[-1].get("result") == "fail" and posted:
            bad.append(f"{r['run_id']} posted a draft that still failed its last round")
        elif r in second and not lines and posted:
            bad.append(f"{r['run_id']} posted with no second pass, in {r['critique']} mode")
    if rounds in (1, 2) and not bad and second:
        s.earned += 2.0
        s.note(f"{len(second)} runs with a second pass: every round logged and within MAX_ROUNDS = {rounds}")
    elif not second:
        s.note("no finished planned runs in self or external mode on the evaluation issues")
    for b in bad[:3]:
        s.note(b)
    return s


# --------------------------------------------------------------------------------------
# Detectors and diff
# --------------------------------------------------------------------------------------

def fixture_run(run: str) -> tuple[dict, list[dict]]:
    folder = ROOT / "fixtures" / "traces" / run
    return json.loads((folder / "plan.json").read_text()), read_trace(folder / "trace.jsonl")


def groups_of(value) -> list[set[str]] | None:
    if not isinstance(value, list) or not all(isinstance(g, (list, tuple, set)) for g in value):
        return None
    return [{sid(x) for x in g} for g in value]


def flat(value) -> set[str]:
    out = set()
    for item in value or []:
        out |= flat(item) if isinstance(item, (list, tuple, set)) else {sid(item)}
    return out


def check_detectors(report: dict) -> Section:
    s = Section("Detectors and diff", 8)
    try:
        from agent.detectors import ladder, repeat_check
    except Exception:
        s.note(raised("importing agent/detectors.py"))
        return s
    looping_plan, looping = fixture_run("looping")
    s49_plan, s49 = fixture_run("s49")

    # 1. The looping run's repeats: turns 1 and 3, turns 2 and 4. 2.5 points.
    try:
        got = groups_of(repeat_check(copy.deepcopy(looping)))
        want = [{"1", "3"}, {"2", "4"}]
        if got is not None and sorted(map(sorted, got)) == sorted(map(sorted, want)):
            s.earned += 2.5
        else:
            s.note(f"the looping run: repeat_check gave {got}; want the groups [1, 3] and [2, 4]")
    except NotImplementedError:
        s.note("agent/detectors.py: repeat_check is not written yet")
    except Exception:
        s.note(raised("repeat_check on the looping run"))

    # 2. Slide 51's run: q1 fires on the two searches, q2 does not, q3 fires on "confirm". 4 points.
    confirm = sid(s49_plan["steps"][-1]["id"])
    searches = {sid(r["step"]) for r in s49 if r.get("type") == "tool_call" and r.get("name") == "search_repo"}
    try:
        got = ladder(copy.deepcopy(s49_plan), copy.deepcopy(s49))
        q = {k: (got.get(k) or {}) for k in ("q1", "q2", "q3")} if isinstance(got, dict) else {}
        if q.get("q1", {}).get("fired") is True and searches <= flat(q["q1"].get("ids")):
            s.earned += 1.5
        else:
            s.note(f"slide 51's run: question 1 should fire on the repeated search, steps {sorted(searches)}; "
                   f"got {q.get('q1')}")
        if q.get("q2", {}).get("fired") is False:
            s.earned += 1.0
        else:
            s.note(f"slide 51's run: question 2 should not fire, since every step's result is used; got {q.get('q2')}")
        if q.get("q3", {}).get("fired") is True and confirm in flat(q["q3"].get("ids")):
            s.earned += 1.5
        else:
            s.note(f"slide 51's run: question 3 should fire on step {confirm}, \"confirm the button works\"; "
                   f"got {q.get('q3')}")
    except NotImplementedError:
        s.note("agent/detectors.py: ladder is not written yet")
    except Exception:
        s.note(raised("ladder on slide 51's run"))

    # 3. The diff labels "confirm" skipped. 1.5 points.
    try:
        from agent.diff import diff
        got = diff(copy.deepcopy(s49_plan), copy.deepcopy(s49))
        labels = {sid(k): v for k, v in ((got or {}).get("steps") or {}).items()} if isinstance(got, dict) else {}
        if labels.get(confirm) == "skipped":
            s.earned += 1.5
        else:
            s.note(f"slide 51's run: the diff should label step {confirm} skipped; got {labels.get(confirm)!r}")
        mine = {sid(k): v for k, v in ((report.get("diff_s49") or {}).get("steps") or {}).items()}
        if mine and mine != labels:
            s.note("reports/LAB_02.json diff_s49 differs from what agent/diff.py returns (no points)")
    except NotImplementedError:
        s.note("agent/diff.py: diff is not written yet")
    except Exception:
        s.note(raised("diff on slide 51's run"))
    return s


# --------------------------------------------------------------------------------------
# Runs
# --------------------------------------------------------------------------------------

# --------------------------------------------------------------------------------------
# Notes and compaction
# --------------------------------------------------------------------------------------

def context_truth(records: list[dict]) -> dict:
    """A notes run as the trace tells it: compacted before its first question, and each
    question's path, its truth (did this run's tool calls return it, before the question?) and its answer."""
    seen, compacted, asked, questions, calls_between, seen_then = [], False, False, [], 0, []
    for x in records:
        if x.get("type") == "tool_call":
            seen += [p for p in x.get("paths") or [] if p not in seen]
        elif x.get("type") == "compaction" and not asked:
            compacted = True
        elif x.get("type") == "model_call" and asked and len(questions) < 6:
            calls_between += 1
        elif x.get("type") == "question":
            if not asked:
                seen_then = list(seen)
            asked = True
            questions.append({"path": x.get("path"), "truth": "yes" if x.get("path") in seen else "no",
                              "answer": x.get("answer")})
    asked_seen = {q["path"] for q in questions if q["truth"] == "yes"}
    return {"compacted": compacted, "questions": questions, "one_call": calls_between == 0,
            "follows_rule": len(questions) == 6 and asked_seen == set(seen_then[:3]),
            "right": sum(q["truth"] == q["answer"] for q in questions)}


def check_notes(notes_runs: list[dict], report: dict, tmp: Path) -> Section:
    s = Section("Notes and compaction", 8)

    # 1 to 3. ways/notes.py against a scripted model, with the file shown and without.
    shown = {}
    for setting in ("on", "off"):
        backend = SentinelSearcher(watch=None) if setting == "on" else ScriptedTriage(watch=None)
        try:
            records, _, error, tools = scripted_run(backend, REJECT_ISSUE, tmp, f"notes-{setting}", way="notes",
                                                    notes=setting)
        except Exception:
            s.note(raised(f"the notes {setting} run"))
            continue
        if error in ("NotImplementedError", "BudgetExceeded"):
            s.note(explain(error, "notes"))
            break
        if error:
            s.note(f"notes {setting}: your way raised (no points lost for that alone):\n{error}")
        shown[setting] = backend.shown
        if setting == "on":   # 1. the file after every step (1.5 points), and never a search term (0.5)
            late = [i + 1 for i, (returned, state) in enumerate(tools.snapshots[1:], start=1)
                    if not isinstance(state, dict) or not isinstance(state.get("steps_done"), list)
                    or not set(returned) <= set(state.get("paths") or [])]
            if len(tools.snapshots) >= 2 and not late:
                s.earned += 1.0
            else:
                s.note(f"the progress file is not up to date before tool call {late[0] if late else 2}: it must "
                       "hold \"steps_done\" and every path returned so far, written after every step")
            sentinel = (SENTINEL.findall(Tracker(ROOT).issue(REJECT_ISSUE)["body"]) or ["SNTL-MISSING"])[0]
            progress = tmp / f"{records[0]['run_id']}.progress.json"
            in_file = progress.exists() and sentinel in progress.read_text()
            to_planner, started = [], False   # plan-tool requests once the executor has started: the reviser's
            for r in backend.requests:
                if not plan_tool(r.get("tools")):
                    started = True
                elif started and sentinel in json.dumps(r):
                    to_planner.append(r)
            if backend.requests and not in_file and not to_planner:
                s.earned += 0.5
            else:
                s.note("a search for text copied from the issue reached " + ("the progress file" if in_file else
                       "a reviser's request") + ": the file holds paths, never search terms")
    if "on" in shown:   # 2. shown with --notes on. 1 point.
        if any(shown["on"]):
            s.earned += 1.0
        else:
            s.note("with --notes on, no model call showed the progress file's text as written")
    # A run that ends early, before its comment, still compacts and asks. 0.5 points.
    if shown:
        try:
            records, _, error, _ = scripted_run(RefusesToRead(), REJECT_ISSUE, tmp, "notes-early", way="notes",
                                                notes="off")
            c = context_truth(records)
            ends = [r.get("terminal_reason") for r in records if r.get("type") == "end"]
            if c["compacted"] and len(c["questions"]) == 6 and c["one_call"]:
                s.earned += 0.5
            else:
                s.note(f"a notes run that could not read a file ended {ends or 'without an end line'} with "
                       f"{len(c['questions'])} questions{'' if c['compacted'] else ' and no compaction before them'}: "
                       "ask the six at the end of every run, however it ends, compacting once first if it has not"
                       + (f"\n{explain(error, 'notes')}" if error else ""))
        except Exception:
            s.note(raised("the early-ending notes run"))
    if "off" in shown:  # 3. never shown with --notes off, and still written. 1 point.
        if shown["off"] and not any(shown["off"]):
            s.earned += 1.0
        else:
            s.note("with --notes off, " + ("a model call showed the progress file's text" if any(shown["off"])
                                           else "no progress file was written"))

    # 4. Part G's 12 runs, each compacted before six questions. 2 points.
    counts = defaultdict(int)
    for r in notes_runs:
        counts[(r["notes"], r["issue"])] += 1
    short = [f"--notes {n} on {i}" for n in ("off", "on") for i in NOTES_ISSUES if counts[(n, i)] < NOTES_RUNS]
    truths = {r["run_id"]: context_truth(r["records"]) for r in notes_runs}
    weak = [rid for rid, c in truths.items() if not c["compacted"] or not c["one_call"] or not c["follows_rule"]]
    threshold = planned_constant("COMPACT_AT", "ways.notes")
    if not short and not weak and threshold:
        s.earned += 2.0
        s.note(f"{len(notes_runs)} notes runs, each compacted before its questions")
    else:
        if short:
            s.note(f"fewer than {NOTES_RUNS} finished notes runs for {', '.join(short)}")
        if weak:
            s.note(f"{len(weak)} notes runs did not compact before their questions, or did not ask six in one "
                   "call about the three earliest paths the run saw (or all, if fewer) and paths it did not "
                   "see for the rest, "
                   f"e.g. {weak[0]}")
        if not threshold:
            s.note("ways/notes.py: COMPACT_AT must be a whole number of tokens")

    # 5. Your context entries match the trace. 2 points.
    mine = {e.get("run_id"): e for e in report.get("context") or [] if isinstance(e, dict)}
    wrong = []
    for r in notes_runs:
        c, e = truths[r["run_id"]], mine.get(r["run_id"])
        if e is None:
            wrong.append(f"{r['run_id']} has no context entry")
            continue
        theirs = [{"path": q.get("path"), "truth": q.get("truth"), "answer": q.get("answer")}
                  for q in e.get("questions") or [] if isinstance(q, dict)]
        if (e.get("notes_shown") is not (r["notes"] == "on") or e.get("compacted") is not c["compacted"]
                or theirs != c["questions"] or e.get("right") != c["right"]):
            wrong.append(f"{r['run_id']}: the trace gives right {c['right']} of {len(c['questions'])}, "
                         f"compacted {c['compacted']}, notes shown {r['notes'] == 'on'}")
    extra = sorted(set(mine) - {r["run_id"] for r in notes_runs})
    if extra:
        wrong.append(f"{extra[0]} is not one of Part G's runs (a notes run on 4203, 4204 or 4206 that finished); "
                     "context holds those only")
    if notes_runs and not wrong and not short:
        s.earned += 2.0
    elif short and not wrong:
        s.note("your context entries match the trace, but count only once all 12 of Part G's runs have finished")
    for w in wrong[:2]:
        s.note(f"reports/LAB_02.json context: {w}")
    return s


# --------------------------------------------------------------------------------------
# Runs
# --------------------------------------------------------------------------------------

def check_runs(summary: dict, report: dict, issues: list[int]) -> Section:
    """1.75 points per configuration, only when it is complete (18 finished runs, 3 per issue)
    and its results match the tracker; nothing for a partial one."""
    s = Section("Runs", 7)
    results = report.get("results") or {}
    for config in CONFIGS:
        mine, theirs = summary[config], results.get(config) or {}
        short = [i for i in issues if mine["_per_issue_runs"].get(i, 0) < RUNS_PER_ISSUE]
        complete = mine["runs"] >= RUNS_PER_ISSUE * len(issues) and not short
        fields = ("runs", "passes", "sweep_min", "sweep_max")
        wrong = [k for k in fields if theirs.get(k) != mine[k]]
        if {str(k): v for k, v in (theirs.get("per_issue") or {}).items()} != mine["per_issue"]:
            wrong.append("per_issue")
        if complete and not wrong:
            s.earned += 1.75
            s.note(f"{config}: {mine['passes']}/{mine['runs']} passes, matches your results")
        elif not complete:
            s.note(f"{config}: {mine['runs']} finished runs of {RUNS_PER_ISSUE * len(issues)}"
                   + (f", fewer than {RUNS_PER_ISSUE} on {short}" if short else "")
                   + ": no points until the configuration is complete")
        else:
            s.note(f"{config}: your results disagree with the tracker on {', '.join(wrong)}; the tracker says "
                   f"passes {mine['passes']}/{mine['runs']}, per issue {mine['per_issue']}, "
                   f"sweeps {mine['sweep_min']} to {mine['sweep_max']}")
        if not mine["runs"]:
            continue
        means = ("mean_tokens", "p50_latency_s", "max_latency_s", "plan_overhead_share", "critique_overhead_share",
                 "revisions_mean", "rounds_mean")
        counts = ("runs_with_repeat", "off_plan", "revisions_max", "rounds_max", "drafts_changed", "drafts_fixed",
                  "drafts_broken", "drafts_held")
        traced = [k for k in means if not (theirs.get(k) is None and mine[k] is None) and not within(theirs.get(k), mine[k])]
        traced += [k for k in counts if theirs.get(k) != mine[k]]
        if traced:
            s.note(f"{config}: {', '.join(traced)} differ from your traces (no points; staff read Part F): the "
                   "traces give " + ", ".join(f"{k} {mine[k]:.3g}" if isinstance(mine[k], float) else f"{k} {mine[k]}"
                                               for k in traced))
    return s


# --------------------------------------------------------------------------------------

def integrity_flags(answers: dict) -> list[str]:
    """Evaluation answers found where they should not be. No points: staff decide."""
    flags = []
    paths = {a["file"] for a in answers.values() if a["file"] != "none"}
    places = [p for d in ("prompts", "ways", "agent") for p in sorted((ROOT / d).rglob("*")) if p.is_file()]
    for place in places:
        try:
            text = place.read_text()
        except UnicodeDecodeError:
            continue
        rel = place.relative_to(ROOT).as_posix()
        for path in sorted(paths):
            if path in text:
                flags.append(f"`{rel}` contains the evaluation answer `{path}`")
        if "answers.yaml" in text:
            flags.append(f"`{rel}` reads the answer file; only eval/ should")
        if "check_triage" in text and not rel.startswith("eval/"):
            flags.append(f"`{rel}` uses eval/check_triage.py; a second pass may read only what the run can see")
    return flags


def main() -> int:
    report_path = ROOT / "reports" / "LAB_02.json"
    try:
        report = json.loads(report_path.read_text())
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"reports/LAB_02.json could not be read ({exc}); checking what can be checked without it.\n")
        report = {}
    if not isinstance(report, dict):
        report = {}

    answers = yaml.safe_load((ROOT / "fixtures" / "answers.yaml").read_text())["eval"]
    answers = {int(k): v for k, v in answers.items()}
    issues = sorted(answers)
    tracker = Tracker(ROOT)
    runs, notes_runs, load_notes = load_runs(set(issues))
    passed = {r["run_id"]: grounded_pass(tracker, r, answers[r["issue"]]) for c in CONFIGS for r in runs[c]}
    summary = {c: summarize(c, runs[c], passed, issues, answers, tracker) for c in CONFIGS}

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        try:
            probe = probe_planner(tmp)
        except Exception:
            probe = {"plan_error": raised("calling make_plan"), "revise_error": "not tried", "plan_requests": [],
                     "revise_requests": [], "plans": {}, "keeps_done": None, "keeps_note": "",
                     "retries_failed": None, "plan_purpose": None, "revise_purpose": None}
        checks = [
            lambda: check_schema(report, probe, runs),
            lambda: check_plan_first(runs, notes_runs),
            lambda: check_untrusted(probe),
            lambda: check_validator(report),
            lambda: check_reject_exit(tmp),
            lambda: check_boundary(tmp),
            lambda: check_revisions(probe, runs),
            lambda: check_second_pass(runs, tmp),
            lambda: check_detectors(report),
            lambda: check_notes(notes_runs, report, tmp),
            lambda: check_runs(summary, report, issues),
        ]
        names = ["Schema compiles", "Plan before action", "Plan before untrusted text", "Validator",
                 "Reject exit", "Boundary", "Revision", "Second pass", "Detectors and diff",
                 "Notes and compaction", "Runs"]
        possible = [5, 6, 8, 10, 8, 8, 6, 10, 8, 8, 7]
        sections = []
        for check, name, pts in zip(checks, names, possible):
            try:
                sections.append(check())
            except Exception:
                sections.append(Section(name, pts, notes=[raised("this check")]))
    sections.append(Section("Report (Parts F and G)", 16, manual=True, notes=["read by staff from reports/LAB_02.md"]))

    backends = sorted({r["backend"] for c in CONFIGS for r in runs[c]} | {r["backend"] for r in notes_runs})
    print(f"Assignment 2 check · runs read from runs/ · backends seen: {', '.join(backends) or 'none'}")
    if any(b not in REAL_BACKENDS for b in backends):
        print("  note: runs from a scripted or simulated backend are not a measurement of a model")
    unpriced = sum(1 for c in CONFIGS for r in runs[c] for x in r["records"]
                   if x.get("type") == "model_call" and x.get("cost_usd") is None)
    if unpriced:
        print(f"  note: {unpriced} model calls have no price, so their cost counts as 0: "
              "add your model's line to pricing.yaml, with its source and read date")
    for note in load_notes[:5]:
        print(f"  note: {note}")
    print()
    auto_earned = auto_possible = 0.0
    for sec in sections:
        score = "staff" if sec.manual else f"{round(sec.earned, 2):>5g} / {sec.possible:g}"
        print(f"{sec.name:<28} {score}")
        for note in sec.notes:
            for i, line in enumerate(note.splitlines()):
                print(f"{'    - ' if i == 0 else '      '}{line}")
        if not sec.manual:
            auto_earned += sec.earned
            auto_possible += sec.possible
    print(f"\nAutomated: {round(auto_earned, 2):g} / {auto_possible:g}   "
          "(plus up to 16 from staff for Part F's and Part G's answers)")
    flags = integrity_flags(answers)
    print("\nIntegrity flags (no points; staff review): " + ("none" if not flags else ""))
    for flag in flags:
        print(f"    - Integrity flag: {flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
