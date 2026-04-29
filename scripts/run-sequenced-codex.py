#!/usr/bin/env python3
"""Autonomous sequenced Codex runner.

Pipeline order (hard-gated):
1) bead in progress
2) vexp capsule (marker validated)
3) implementation via RTK (marker validated)
4) quality gate script
5) bead close + sync
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# claude_core is deployed to ~/.claude/scripts/claude_core by deploy-claude-core.py
_CLAUDE_SCRIPTS = Path(__file__).resolve().parent
if str(_CLAUDE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_CLAUDE_SCRIPTS))
try:
    from claude_core.hooks import walk_ancestor_pids as _walk_ancestor_pids
except Exception:  # pragma: no cover — fallback if claude_core not deployed
    def _walk_ancestor_pids(pid: int) -> set[int]:
        return {pid}

PROJECT_ORDER = ["HEALTH", "WORK", "TODO"]
PROJECT_DIRS: dict[str, Path] = {
    "HEALTH": Path.home() / "Documents" / "Claude Projects" / "HEALTH",
    "WORK": Path.home() / "Documents" / "Claude Projects" / "WORK",
    "TODO": Path.home() / "Documents" / "Claude Projects" / "TODO",
}

TEMPLATE_PATH = Path.home() / ".claude" / "templates" / "codex-sequenced-task.md"
QUALITY_GATE_PATH = Path.home() / ".claude" / "scripts" / "run-quality-gate.sh"
LOG_ROOT = Path.home() / ".claude" / "logs" / "sequenced-codex"

EXPECTED_MARKERS = [
    "STAGE_OK:BEAD_IN_PROGRESS",
    "STAGE_OK:VEXP_CAPSULE",
    "STAGE_OK:RTK_IMPLEMENTATION",
    "STAGE_OK:QUALITY_GATE",
    "STAGE_OK:BEAD_CLOSE_SYNC",
]


@dataclass
class CmdResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_etime_to_seconds(etime: str) -> int:
    # ps etime formats: [[dd-]hh:]mm:ss
    etime = etime.strip()
    days = 0
    if "-" in etime:
        day_part, etime = etime.split("-", 1)
        days = int(day_part)

    parts = [int(p) for p in etime.split(":")]
    if len(parts) == 3:
        hours, minutes, seconds = parts
    elif len(parts) == 2:
        hours, minutes, seconds = 0, parts[0], parts[1]
    else:
        hours, minutes, seconds = 0, 0, parts[0]

    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def run_cmd(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    timeout: int | None = None,
    env: dict[str, str] | None = None,
) -> CmdResult:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        return CmdResult(proc.returncode, proc.stdout, proc.stderr, timed_out=False)
    except subprocess.TimeoutExpired as exc:
        return CmdResult(
            returncode=124,
            stdout=exc.stdout or "",
            stderr=(exc.stderr or "") + "\nTimed out",
            timed_out=True,
        )


def bd_cmd(project: str, args: list[str], timeout: int = 30) -> CmdResult:
    return run_cmd(["bd", *args], cwd=PROJECT_DIRS[project], timeout=timeout)


def parse_json(raw: str, default: Any) -> Any:
    try:
        return json.loads(raw)
    except Exception:
        return default


def get_ready_beads(project: str) -> list[dict[str, Any]]:
    res = bd_cmd(project, ["ready", "--json"])
    if res.returncode != 0:
        return []
    data = parse_json(res.stdout, [])
    return data if isinstance(data, list) else []


def sort_ready_beads(beads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(item: dict[str, Any]) -> tuple[int, str]:
        priority = int(item.get("priority", 2) or 2)
        created = str(item.get("created_at", ""))
        return (priority, created)

    return sorted(beads, key=key)


def bead_matches_filters(bead: dict[str, Any], include_labels: list[str]) -> bool:
    if not include_labels:
        return True

    bead_labels = bead.get("labels") or []
    if not isinstance(bead_labels, list):
        return False

    bead_label_set = {str(x).strip().lower() for x in bead_labels if str(x).strip()}
    wanted = {str(x).strip().lower() for x in include_labels if str(x).strip()}
    return bool(bead_label_set.intersection(wanted))


def find_bead_in_ready(
    bead_id: str,
    project: str,
    include_labels: list[str],
) -> dict[str, Any] | None:
    for bead in sort_ready_beads(get_ready_beads(project)):
        if bead.get("id") == bead_id and bead_matches_filters(bead, include_labels):
            return bead
    return None


def resolve_tasks(args: argparse.Namespace) -> list[tuple[str, dict[str, Any]]]:
    max_tasks = max(1, int(args.max_tasks))
    include_labels = args.include_label or []

    if args.bead_id:
        if args.project != "auto":
            bead = find_bead_in_ready(args.bead_id, args.project, include_labels)
            if not bead:
                raise RuntimeError(
                    f"Bead {args.bead_id} is not ready/open/unblocked in {args.project}"
                )
            return [(args.project, bead)]

        for project in PROJECT_ORDER:
            bead = find_bead_in_ready(args.bead_id, project, include_labels)
            if bead:
                return [(project, bead)]
        raise RuntimeError(f"Bead {args.bead_id} was not found in ready queues")

    tasks: list[tuple[str, dict[str, Any]]] = []

    projects = PROJECT_ORDER if args.project == "auto" else [args.project]
    for project in projects:
        ready = sort_ready_beads(get_ready_beads(project))
        for bead in ready:
            if not bead_matches_filters(bead, include_labels):
                continue
            tasks.append((project, bead))
            if len(tasks) >= max_tasks:
                return tasks

    return tasks


def list_conflicting_sessions() -> list[dict[str, Any]]:
    res = run_cmd(["ps", "-Ao", "pid=,etime=,pcpu=,command="])
    if res.returncode != 0:
        return []

    out: list[dict[str, Any]] = []
    # Exclude our entire ancestor chain so the Claude CLI session that invoked us
    # (hook -> shell -> claude) is not flagged as a "conflicting writer".
    excluded_pids = _walk_ancestor_pids(os.getpid())

    for line in res.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        pid_s, etime, pcpu_s, command = parts
        try:
            pid = int(pid_s)
            pcpu = float(pcpu_s)
        except ValueError:
            continue

        if pid in excluded_pids:
            continue

        is_writer = (
            "codex exec" in command
            or (
                "resources/native-binary/claude" in command
                and "--output-format stream-json" in command
            )
        )
        if not is_writer:
            continue

        if "run-sequenced-codex.py" in command:
            continue

        out.append(
            {
                "pid": pid,
                "etime": etime,
                "etime_seconds": parse_etime_to_seconds(etime),
                "pcpu": pcpu,
                "command": command,
            }
        )

    return out


def enforce_single_writer(kill_stale: bool, stale_minutes: int = 15) -> list[dict[str, Any]]:
    sessions = list_conflicting_sessions()
    if not sessions:
        return []

    if not kill_stale:
        return sessions

    still_active: list[dict[str, Any]] = []
    stale_cutoff = stale_minutes * 60

    for sess in sessions:
        if sess["etime_seconds"] >= stale_cutoff and sess["pcpu"] < 2.0:
            try:
                os.kill(sess["pid"], signal.SIGTERM)
                time.sleep(0.2)
            except ProcessLookupError:
                continue

            try:
                os.kill(sess["pid"], 0)
                os.kill(sess["pid"], signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            still_active.append(sess)

    return still_active


def ensure_vexp_available() -> bool:
    res = run_cmd(["codex", "mcp", "list"], timeout=15)
    if res.returncode != 0:
        return False

    lines = [ln.strip().lower() for ln in res.stdout.splitlines() if ln.strip()]
    return any("vexp" in ln and "enabled" in ln for ln in lines)


def load_template() -> str:
    if not TEMPLATE_PATH.exists():
        raise RuntimeError(f"Template file missing: {TEMPLATE_PATH}")
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def marker_positions(text: str) -> dict[str, int]:
    return {marker: text.find(marker) for marker in EXPECTED_MARKERS}


def validate_markers(text: str) -> tuple[bool, str]:
    positions = marker_positions(text)
    prev = -1
    for marker in EXPECTED_MARKERS:
        pos = positions.get(marker, -1)
        if pos < 0:
            return False, f"Missing marker: {marker}"
        if pos <= prev:
            return False, f"Out-of-order marker: {marker}"
        prev = pos
    return True, "ok"


def parse_capsule_refs(text: str) -> list[str]:
    refs: list[str] = []
    for match in re.finditer(r"^VEXP_CAPSULE_REF:(.+)$", text, re.MULTILINE):
        raw = match.group(1).strip()
        refs.extend([x.strip() for x in raw.split(",") if x.strip()])
    # stable unique
    seen = set()
    unique: list[str] = []
    for r in refs:
        if r not in seen:
            seen.add(r)
            unique.append(r)
    return unique


def parse_rtk_summary(text: str) -> str:
    m = re.search(r"^RTK_USAGE_SUMMARY:(.+)$", text, re.MULTILINE)
    return m.group(1).strip() if m else ""


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def add_failure_comment(project: str, bead_id: str, message: str) -> None:
    _ = bd_cmd(project, ["comments", "add", bead_id, message], timeout=20)


def get_changed_files(project_dir: Path) -> list[str]:
    res = run_cmd(["git", "status", "--short"], cwd=project_dir, timeout=20)
    if res.returncode != 0:
        return []
    lines = [ln.rstrip() for ln in res.stdout.splitlines() if ln.strip()]
    return lines


def format_prompt(template: str, project: str, bead: dict[str, Any]) -> str:
    labels = bead.get("labels") or []
    if isinstance(labels, list):
        labels_str = ", ".join(str(x) for x in labels)
    else:
        labels_str = str(labels)

    return template.format(
        bead_id=bead.get("id", ""),
        project_name=project,
        project_path=str(PROJECT_DIRS[project]),
        bead_title=bead.get("title", ""),
        bead_priority=bead.get("priority", ""),
        bead_type=bead.get("issue_type", bead.get("type", "task")),
        bead_labels=labels_str or "(none)",
        bead_description=bead.get("description", ""),
    )


def run_task(
    *,
    run_log: dict[str, Any],
    log_file: Path,
    project: str,
    bead: dict[str, Any],
    timeout_min: int,
    dry_run: bool,
) -> bool:
    bead_id = str(bead.get("id", ""))
    task_entry: dict[str, Any] = {
        "bead_id": bead_id,
        "project": project,
        "title": bead.get("title", ""),
        "started_at": utc_now(),
        "status": "in_progress",
        "stages": [],
        "artifacts": {},
    }
    run_log["tasks"].append(task_entry)
    write_json(log_file, run_log)

    def stage_start(name: str) -> dict[str, Any]:
        st = {"name": name, "status": "in_progress", "started_at": utc_now()}
        task_entry["stages"].append(st)
        write_json(log_file, run_log)
        return st

    def stage_ok(stage: dict[str, Any], evidence: dict[str, Any] | None = None) -> None:
        stage["status"] = "passed"
        stage["ended_at"] = utc_now()
        if evidence:
            stage["evidence"] = evidence
        write_json(log_file, run_log)

    def stage_fail(stage: dict[str, Any], error: str, evidence: dict[str, Any] | None = None) -> None:
        stage["status"] = "failed"
        stage["ended_at"] = utc_now()
        stage["error"] = error
        if evidence:
            stage["evidence"] = evidence
        write_json(log_file, run_log)

    # Stage 1: bead in progress
    st1 = stage_start("BEAD_IN_PROGRESS")
    if dry_run:
        stage_ok(st1, {"dry_run": True, "note": "Would mark bead in progress"})
    else:
        up = bd_cmd(project, ["update", bead_id, "--status=in_progress"], timeout=20)
        if up.returncode != 0:
            stage_fail(st1, "Failed to set in_progress", {"stderr": up.stderr.strip()})
            task_entry["status"] = "failed"
            task_entry["ended_at"] = utc_now()
            write_json(log_file, run_log)
            return False
        stage_ok(st1, {"stdout": up.stdout.strip()})

    # Stage 2+3: Codex execution + marker validation
    st2 = stage_start("VEXP_CAPSULE")
    st3 = stage_start("RTK_IMPLEMENTATION")

    template = load_template()
    prompt = format_prompt(template, project, bead)
    task_dir = PROJECT_DIRS[project]

    if dry_run:
        task_entry["artifacts"]["prompt_preview"] = prompt[:2000]
        stage_ok(st2, {"dry_run": True, "note": "Would run Codex with vexp capsule"})
        stage_ok(st3, {"dry_run": True, "note": "Would run implementation stage"})
    else:
        task_run_dir = log_file.parent / bead_id
        task_run_dir.mkdir(parents=True, exist_ok=True)
        codex_stdout = task_run_dir / "codex.stdout.log"
        codex_stderr = task_run_dir / "codex.stderr.log"
        last_msg = task_run_dir / "codex.last-message.md"
        prompt_file = task_run_dir / "codex.prompt.md"
        prompt_file.write_text(prompt, encoding="utf-8")

        cmd = [
            "codex",
            "exec",
            "--full-auto",
            "--cd",
            str(task_dir),
            "--output-last-message",
            str(last_msg),
            prompt,
        ]

        proc = run_cmd(cmd, timeout=timeout_min * 60)
        codex_stdout.write_text(proc.stdout or "", encoding="utf-8")
        codex_stderr.write_text(proc.stderr or "", encoding="utf-8")

        task_entry["artifacts"].update(
            {
                "codex_stdout": str(codex_stdout),
                "codex_stderr": str(codex_stderr),
                "codex_last_message": str(last_msg),
                "codex_prompt": str(prompt_file),
            }
        )

        if proc.returncode != 0:
            err = "Codex timed out" if proc.timed_out else f"Codex exited {proc.returncode}"
            stage_fail(st2, err, {"stderr": (proc.stderr or "").strip()[:3000]})
            stage_fail(st3, err)
            recovery = (
                f"Sequenced run failed during Codex stage ({err}). "
                f"Recovery: python3 ~/.claude/scripts/run-sequenced-codex.py "
                f"--project {project} --bead-id {bead_id}. Log: {log_file}"
            )
            add_failure_comment(project, bead_id, recovery)
            task_entry["status"] = "failed"
            task_entry["ended_at"] = utc_now()
            write_json(log_file, run_log)
            return False

        combined = (last_msg.read_text(encoding="utf-8") if last_msg.exists() else "") + "\n" + (proc.stdout or "")
        markers_ok, marker_reason = validate_markers(combined)
        capsule_refs = parse_capsule_refs(combined)
        rtk_summary = parse_rtk_summary(combined)

        if not markers_ok:
            stage_fail(st2, f"Stage marker validation failed: {marker_reason}")
            stage_fail(st3, f"Stage marker validation failed: {marker_reason}")
            recovery = (
                f"Sequenced run failed: {marker_reason}. "
                f"Recovery: python3 ~/.claude/scripts/run-sequenced-codex.py "
                f"--project {project} --bead-id {bead_id}. Log: {log_file}"
            )
            add_failure_comment(project, bead_id, recovery)
            task_entry["status"] = "failed"
            task_entry["ended_at"] = utc_now()
            write_json(log_file, run_log)
            return False

        if not capsule_refs:
            stage_fail(st2, "Missing VEXP_CAPSULE_REF evidence")
            stage_fail(st3, "Missing VEXP_CAPSULE_REF evidence")
            recovery = (
                f"Sequenced run failed: missing VEXP_CAPSULE_REF evidence. "
                f"Recovery: python3 ~/.claude/scripts/run-sequenced-codex.py "
                f"--project {project} --bead-id {bead_id}. Log: {log_file}"
            )
            add_failure_comment(project, bead_id, recovery)
            task_entry["status"] = "failed"
            task_entry["ended_at"] = utc_now()
            write_json(log_file, run_log)
            return False

        stage_ok(st2, {"capsule_refs": capsule_refs})
        stage_ok(st3, {"rtk_usage_summary": rtk_summary or "(not provided)"})

    # Stage 4: quality gate
    st4 = stage_start("QUALITY_GATE")
    if dry_run:
        stage_ok(st4, {"dry_run": True, "note": "Would run quality gate helper"})
    else:
        gate_out_dir = log_file.parent / bead_id
        gate_stdout = gate_out_dir / "quality-gate.stdout.log"
        gate_stderr = gate_out_dir / "quality-gate.stderr.log"

        env = os.environ.copy()
        env["BEAD_ID"] = bead_id

        gate = run_cmd([str(QUALITY_GATE_PATH), str(task_dir)], cwd=task_dir, timeout=45 * 60, env=env)
        gate_stdout.write_text(gate.stdout or "", encoding="utf-8")
        gate_stderr.write_text(gate.stderr or "", encoding="utf-8")
        task_entry["artifacts"].update(
            {
                "quality_gate_stdout": str(gate_stdout),
                "quality_gate_stderr": str(gate_stderr),
            }
        )

        if gate.returncode != 0:
            stage_fail(st4, "Quality gate failed", {"stderr": (gate.stderr or "").strip()[:3000]})
            recovery = (
                f"Quality gate failed in sequenced run. "
                f"Recovery: python3 ~/.claude/scripts/run-sequenced-codex.py "
                f"--project {project} --bead-id {bead_id}. Log: {log_file}"
            )
            add_failure_comment(project, bead_id, recovery)
            task_entry["status"] = "failed"
            task_entry["ended_at"] = utc_now()
            write_json(log_file, run_log)
            return False

        stage_ok(st4, {"stdout_tail": "\n".join((gate.stdout or "").splitlines()[-20:])})

    # Stage 5: close + sync
    st5 = stage_start("BEAD_CLOSE_SYNC")
    if dry_run:
        stage_ok(st5, {"dry_run": True, "note": "Would close bead and sync"})
        task_entry["status"] = "passed"
        task_entry["ended_at"] = utc_now()
        write_json(log_file, run_log)
        return True

    changed = get_changed_files(task_dir)
    task_entry["artifacts"]["changed_files"] = changed

    close_reason = "Completed via sequenced codex pipeline (vexp+rtk+quality-gate passed)"
    close_res = bd_cmd(project, ["close", bead_id, "--reason", close_reason], timeout=20)
    if close_res.returncode != 0:
        stage_fail(st5, "Failed to close bead", {"stderr": close_res.stderr.strip()})
        task_entry["status"] = "failed"
        task_entry["ended_at"] = utc_now()
        write_json(log_file, run_log)
        return False

    sync_ok = False
    sync_errors: list[str] = []
    for _ in range(3):
        sync_res = bd_cmd(project, ["sync"], timeout=30)
        if sync_res.returncode == 0:
            sync_ok = True
            break
        sync_errors.append(sync_res.stderr.strip())
        time.sleep(1)

    if not sync_ok:
        stage_fail(st5, "Failed to sync after retries", {"errors": sync_errors})
        add_failure_comment(
            project,
            bead_id,
            f"Bead closed but sync failed after retries. Please run `bd export -o .beads/issues.jsonl`. Log: {log_file}",
        )
        task_entry["status"] = "failed"
        task_entry["ended_at"] = utc_now()
        write_json(log_file, run_log)
        return False

    stage_ok(st5, {"changed_files": changed[:50]})
    task_entry["status"] = "passed"
    task_entry["ended_at"] = utc_now()
    write_json(log_file, run_log)
    return True


def build_run_log(args: argparse.Namespace, log_file: Path) -> dict[str, Any]:
    return {
        "run_id": log_file.stem,
        "started_at": utc_now(),
        "status": "in_progress",
        "args": {
            "project": args.project,
            "bead_id": args.bead_id,
            "max_tasks": args.max_tasks,
            "include_label": args.include_label,
            "dry_run": args.dry_run,
            "kill_stale": args.kill_stale,
            "timeout_min": args.timeout_min,
        },
        "tasks": [],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run unattended sequenced Codex bead pipeline")
    parser.add_argument("--project", choices=["HEALTH", "WORK", "TODO", "auto"], default="auto")
    parser.add_argument("--bead-id", help="Specific bead ID (must be ready/open/unblocked)")
    parser.add_argument("--max-tasks", type=int, default=1)
    parser.add_argument(
        "--include-label",
        action="append",
        default=[],
        help="Only run beads containing at least one of these labels (repeatable)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--kill-stale", action="store_true")
    parser.add_argument("--timeout-min", type=int, default=90)
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not QUALITY_GATE_PATH.exists():
        print(f"❌ Quality gate helper missing: {QUALITY_GATE_PATH}", file=sys.stderr)
        return 2

    if not ensure_vexp_available():
        print("❌ vexp MCP is not enabled. Aborting before implementation.", file=sys.stderr)
        return 2

    conflicts = enforce_single_writer(kill_stale=args.kill_stale)
    if conflicts:
        print("❌ Conflicting writer sessions detected:", file=sys.stderr)
        for sess in conflicts:
            print(
                f"  pid={sess['pid']} etime={sess['etime']} cpu={sess['pcpu']:.1f} cmd={sess['command']}",
                file=sys.stderr,
            )
        print("Use --kill-stale to terminate stale low-CPU sessions.", file=sys.stderr)
        return 3

    try:
        tasks = resolve_tasks(args)
    except RuntimeError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 2

    if not tasks:
        print("✅ No ready beads found — nothing to do.")
        return 0

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    log_file = LOG_ROOT / datetime.now().strftime("%Y-%m-%d") / f"{run_id}.json"
    run_log = build_run_log(args, log_file)
    write_json(log_file, run_log)

    print(f"🚀 Sequenced run started: {run_id}")
    print(f"📝 Log: {log_file}")

    all_ok = True
    for project, bead in tasks:
        bead_id = bead.get("id", "")
        print(f"\n▶️  Processing {bead_id} ({project}) — {bead.get('title', '')}")
        ok = run_task(
            run_log=run_log,
            log_file=log_file,
            project=project,
            bead=bead,
            timeout_min=args.timeout_min,
            dry_run=args.dry_run,
        )
        all_ok = all_ok and ok

    run_log["status"] = "passed" if all_ok else "failed"
    run_log["ended_at"] = utc_now()
    write_json(log_file, run_log)

    passed = [t for t in run_log["tasks"] if t.get("status") == "passed"]
    failed = [t for t in run_log["tasks"] if t.get("status") != "passed"]

    print("\n📊 Summary")
    print(f"  Passed: {len(passed)}")
    print(f"  Failed: {len(failed)}")
    print(f"  Log: {log_file}")

    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
