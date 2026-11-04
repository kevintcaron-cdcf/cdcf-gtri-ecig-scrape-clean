#!/usr/bin/env python3
"""Run production scrapers concurrently with resumable per-site state.

Each scraper remains an independent process.  A site is considered complete
only after its process exits successfully; failed and interrupted sites are
eligible for retry on the next invocation.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_STATE_DIR = ROOT / ".scrape-run"


def site(script: str, *, env: dict[str, str] | None = None) -> dict[str, object]:
    return {"name": Path(script).stem, "script": script, "env": env or {}}


SITES = [
    site("scraping/getpop.py"),
    site("scraping/mipod.py"),
    site("scraping/vapesourcing.py"),
    site("scraping/vapewh.py"),
    site("scraping/huffandpuffers.py"),
    site("scraping/myvaporstore.py", env={"HEADLESS": "0"}),
    site("scraping/ecigmafia.py"),
    site("scraping/vaping.py"),
    site("scraping/vape_com.py", env={"HEADLESS": "0"}),
    site("scraping/perfectvape.py"),
    site("scraping/puffco.py"),
    site("scraping/vapordna.py"),
    site("scraping/vaporfi.py"),
    site("scraping/prilla.py"),
    site("scraping/nicokick.py"),
    site("scraping/northerner.py"),
    site("scraping/alp_pouch.py"),
    site("scraping/sesh_products.py"),
    site("scraping/juice_head.py"),
    site("scraping/outlaw_dip.py"),
    site("scraping/spree_bar_sales.py"),
    site("scraping/west_coast_vape_supply.py"),
    site("scraping/nic_pouches_us.py"),
]

STATE_VERSION = 1
ACTIVE_PROCESSES: dict[str, subprocess.Popen[bytes]] = {}
ACTIVE_LOCK = threading.Lock()
STATE_LOCK = threading.Lock()
STOP_REQUESTED = False


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_state(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"version": STATE_VERSION, "sites": {}}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Cannot read checkpoint {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("sites", {}), dict):
        raise SystemExit(f"Invalid checkpoint format: {path}")
    return data


def save_state(path: Path, state: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def update_state(path: Path, state: dict[str, object], name: str, **values: object) -> None:
    with STATE_LOCK:
        states = state.setdefault("sites", {})
        assert isinstance(states, dict)
        entry = states.setdefault(name, {})
        assert isinstance(entry, dict)
        entry.update(values)
        state["updated_at"] = now()
        save_state(path, state)


def log_path(log_dir: Path, name: str) -> Path:
    return log_dir / f"{name}.log"


def run_one(item: dict[str, object], state_path: Path, log_dir: Path, state: dict[str, object]) -> tuple[str, int]:
    name = str(item["name"])
    script = ROOT / str(item["script"])
    output = log_path(log_dir, name)
    if STOP_REQUESTED:
        update_state(state_path, state, name, status="interrupted", finished_at=now())
        return name, 130
    environment = os.environ.copy()
    environment.update({str(k): str(v) for k, v in dict(item.get("env", {})).items()})
    update_state(state_path, state, name, status="running", started_at=now(), log=str(output))
    log_dir.mkdir(parents=True, exist_ok=True)
    return_code = 1
    process: subprocess.Popen[bytes] | None = None
    try:
        with output.open("ab") as log:
            log.write(f"\n=== started {now()} ===\n".encode())
            log.flush()
            process = subprocess.Popen(
                [sys.executable, str(script)],
                cwd=ROOT,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            with ACTIVE_LOCK:
                ACTIVE_PROCESSES[name] = process
            return_code = process.wait()
            log.write(f"=== exited {return_code} at {now()} ===\n".encode())
    except OSError as exc:
        with output.open("ab") as log:
            log.write(f"runner error: {exc}\n".encode())
    finally:
        with ACTIVE_LOCK:
            ACTIVE_PROCESSES.pop(name, None)
    status = "succeeded" if return_code == 0 else ("interrupted" if STOP_REQUESTED else "failed")
    update_state(state_path, state, name, status=status, finished_at=now(), return_code=return_code)
    return name, return_code


def interrupt_handler(signum: int, _frame: object) -> None:
    global STOP_REQUESTED
    if STOP_REQUESTED:
        return
    STOP_REQUESTED = True
    print("\nInterrupt received; stopping active scrapers...", flush=True)
    with ACTIVE_LOCK:
        for process in ACTIVE_PROCESSES.values():
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=int(os.getenv("SCRAPE_WORKERS", "4")))
    parser.add_argument("--state-dir", type=Path, default=Path(os.getenv("SCRAPE_STATE_DIR", DEFAULT_STATE_DIR)))
    parser.add_argument("--only", help="comma-separated site names or script paths")
    parser.add_argument("--from", dest="from_site", help="start at this site name or script, inclusive")
    parser.add_argument("--reset", action="store_true", help="discard the checkpoint before running")
    parser.add_argument("--no-resume", action="store_true", help="run selected sites even if already successful")
    parser.add_argument("--list", action="store_true", help="list configured sites and exit")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.workers < 1:
        raise SystemExit("--workers must be at least 1")
    if args.list:
        for item in SITES:
            print(f"{item['name']}: {item['script']}")
        return 0

    state_dir = args.state_dir if args.state_dir.is_absolute() else ROOT / args.state_dir
    state_path = state_dir / "checkpoint.json"
    log_dir = state_dir / "logs"
    if args.reset and state_path.exists():
        state_path.unlink()
    state = load_state(state_path)
    state["version"] = STATE_VERSION

    selected = SITES
    if args.from_site:
        marker = args.from_site.removeprefix("scraping/").removesuffix(".py")
        names = [str(item["name"]) for item in SITES]
        if marker not in names:
            raise SystemExit(f"Unknown --from site: {args.from_site}")
        selected = SITES[names.index(marker) :]
    if args.only:
        wanted = {value.strip().removeprefix("scraping/").removesuffix(".py") for value in args.only.split(",") if value.strip()}
        known = {str(item["name"]) for item in SITES}
        unknown = sorted(wanted - known)
        if unknown:
            raise SystemExit(f"Unknown --only site(s): {', '.join(unknown)}")
        selected = [item for item in selected if str(item["name"]) in wanted]

    statuses = state.get("sites", {})
    assert isinstance(statuses, dict)
    pending = [item for item in selected if args.no_resume or statuses.get(str(item["name"]), {}).get("status") != "succeeded"]
    if not pending:
        print("All selected sites are already complete. Use --reset or --no-resume to run them again.")
        return 0

    print(f"Running {len(pending)} site(s) with {args.workers} worker(s). Checkpoint: {state_path}")
    signal.signal(signal.SIGINT, interrupt_handler)
    signal.signal(signal.SIGTERM, interrupt_handler)
    failures = 0
    with ThreadPoolExecutor(max_workers=min(args.workers, len(pending))) as executor:
        futures = [executor.submit(run_one, item, state_path, log_dir, state) for item in pending]
        for future in as_completed(futures):
            name, return_code = future.result()
            print(f"{name}: {'succeeded' if return_code == 0 else 'failed'}", flush=True)
            failures += return_code != 0
    return 130 if STOP_REQUESTED else (1 if failures else 0)


if __name__ == "__main__":
    raise SystemExit(main())
