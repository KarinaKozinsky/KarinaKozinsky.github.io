#!/usr/bin/env python3
# filter_pois.py
# - Reads current POIs + tour_input
# - Computes kept/recheck/drop
# - Writes lean recheck/drop JSON for GPT (no coords/place_id)
# - Decides whether to trigger refinement based on empty_slots
# - Backs up outputs with loop id
# - Logs a JSON line to tour_log.jsonl

from __future__ import annotations
import json, shutil, time
from pathlib import Path
from typing import Any, Dict, List

# ------------ FILES / PATHS ------------
FILES = {
    "current_pois": Path("src/data/current_pois.json"),
    "tour_in":      Path("src/data/tour_input.json"),
    "recheck":      Path("src/data/recheck.json"),
    "drop":         Path("src/data/drop.json"),
    "gpt_out":      Path("src/data/gpt_output.json"),   # produced by refinement.py
    "log":          Path("src/data/tour_log.jsonl"),
    "counter":      Path("src/data/loop_counter.txt"),
    "backups_dir":  Path("src/data/backups"),
}
BACKUPS = FILES["backups_dir"]

LEAN_RECHECK_FIELDS = ["poi_id", "name", "address", "type", "reasons", "hint", "alt_names",
                       "refined_attempts", "refined_last_address"]


# ------------ HELPERS ------------
def now_iso() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def ensure_dirs():
    for key in ("recheck", "drop", "gpt_out", "log"):
        FILES[key].parent.mkdir(parents=True, exist_ok=True)
    BACKUPS.mkdir(parents=True, exist_ok=True)

def read_json(p: Path) -> Any:
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)

def write_json(p: Path, obj: Any):
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)

def ensure_counter() -> int:
    """Create counter if missing; return current integer value."""
    FILES["counter"].parent.mkdir(parents=True, exist_ok=True)
    if not FILES["counter"].exists():
        FILES["counter"].write_text("0", encoding="utf-8")
        return 0
    txt = FILES["counter"].read_text(encoding="utf-8").strip() or "0"
    try:
        return int(txt)
    except ValueError:
        FILES["counter"].write_text("0", encoding="utf-8")
        return 0

def bump_for_refinement() -> int:
    """Increment loop counter for the next refinement pass; return loop id used."""
    cur = ensure_counter()
    nxt = cur + 1
    FILES["counter"].write_text(str(nxt), encoding="utf-8")
    return nxt

def backup(src_path: Path, stem: str, loop_id: int):
    """Copy src_path to backups/<stem>_<loop_id>.json if src exists."""
    if not src_path.exists():
        return
    dst = BACKUPS / f"{stem}_{loop_id:04d}.json"
    shutil.copyfile(src_path, dst)

def append_log(rec: dict):
    FILES["log"].parent.mkdir(parents=True, exist_ok=True)
    with open(FILES["log"], "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

# Fields we keep for the GPT payloads (trimmed; no coords/place_id)
LEAN_RECHECK_FIELDS = ["poi_id", "name", "address", "type", "reasons", "hint", "alt_names"]
LEAN_DROP_FIELDS    = ["poi_id", "name", "address", "type", "reasons"]

# ------------ CORE ------------
def load_pois(container: Any) -> List[Dict[str, Any]]:
    """Support {pois:[...]}, {stops:[...]}, or a bare list."""
    if isinstance(container, dict):
        if "pois" in container and isinstance(container["pois"], list):
            return container["pois"]
        if "stops" in container and isinstance(container["stops"], list):
            return container["stops"]
    if isinstance(container, list):
        return container
    raise ValueError("Unsupported POIs structure. Expected {pois:[...]}, {stops:[...]}, or a list.")

def main():
    t0 = time.time()
    ensure_dirs()

    # Read tour input (single source of truth for city/theme/mode/stop_count)
    if not FILES["tour_in"].exists():
        raise FileNotFoundError(f"Missing {FILES['tour_in']}. Create it before running filter.")
    tour_in = read_json(FILES["tour_in"])
    city  = tour_in.get("city")
    theme = tour_in.get("theme")
    mode  = tour_in.get("mode", "walking")
    stop_count = int(tour_in.get("stop_count", 9))

    # Read current POIs
    if not FILES["current_pois"].exists():
        raise FileNotFoundError(f"Missing {FILES['current_pois']}. Run earlier pipeline stages first.")
    raw = read_json(FILES["current_pois"])
    pois = load_pois(raw)

    # Build lean lists
    kept_names: List[Dict[str, Any]] = []
    recheck_list: List[Dict[str, Any]] = []
    drop_list: List[Dict[str, Any]] = []

    for poi in pois:
        status = (poi.get("status") or "").lower()
        if status == "keep":
            entry = {"poi_id": poi.get("poi_id")}
            if poi.get("name"):
                entry["name"] = poi["name"]
            kept_names.append(entry)
        elif status == "recheck":
            entry = {k: poi[k] for k in LEAN_RECHECK_FIELDS if k in poi and poi[k] not in (None, "", [])}
            entry.setdefault("refined_attempts", int(poi.get("refined_attempts") or 0))
            entry.setdefault("refined_last_address", poi.get("refined_last_address") or poi.get("address"))
            recheck_list.append(entry)
        elif status == "drop":
            entry = {k: poi[k] for k in LEAN_DROP_FIELDS if k in poi and poi[k] not in (None, "", [])}
            drop_list.append(entry)
        else:
            # ignore other statuses (e.g., "raw") in this stage
            pass

    # Write lean payloads for refinement step
    write_json(FILES["recheck"], recheck_list)
    write_json(FILES["drop"], drop_list)

    kept_count  = len(kept_names)
    empty_slots = max(0, stop_count - kept_count)
    next_step   = "refinement" if empty_slots > 0 else "optimize"

    # If we need another GPT pass, bump loop id and back up inputs to /backups
    if empty_slots > 0:
        loop_id = bump_for_refinement()
        backup(FILES["current_pois"], "current_pois", loop_id)
        backup(FILES["recheck"],      "recheck",      loop_id)
        backup(FILES["drop"],         "drop",         loop_id)
        loop_used = loop_id
    else:
        # No bump; keep current counter in log for continuity
        loop_used = ensure_counter()

    from collections import Counter
    reason_counts = Counter()
    for poi in pois:
        st = (poi.get("status") or "").lower()
        if st in ("recheck", "drop"):
            for r in poi.get("reasons", []):
                reason_counts[r] += 1

    # Log run
    append_log({
        "ts": now_iso(),
        "stage": "filter_pois",
        "loop_id": loop_used,
        "city": city,
        "theme": theme,
        "mode": mode,
        "kept": kept_count,
        "recheck": len(recheck_list),
        "drop": len(drop_list),
        "stop_count": stop_count,
        "empty_slots": empty_slots,
        "next_step": next_step,
        "took_sec": round(time.time() - t0, 2),
        "reason_counts": dict(reason_counts),
        "files": {
            "current_pois": str(FILES["current_pois"]),
            "recheck": str(FILES["recheck"]),
            "drop": str(FILES["drop"]),
            "log": str(FILES["log"]),
            "backups_dir": str(BACKUPS),
        },
    })

    # Console summary
    print(f"[filter] kept={kept_count} recheck={len(recheck_list)} drop={len(drop_list)} "
          f"target={stop_count} empty_slots={empty_slots} → next={next_step}")

if __name__ == "__main__":
    main()
