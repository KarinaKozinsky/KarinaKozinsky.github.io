#!/usr/bin/env python3
# refinement.py
# - Builds prompt variables for the curated prompt (version 4)
# - Calls OpenAI Responses with your saved prompt ID
# - Writes parsed JSON to src/data/gpt_output.json
# - Logs to src/data/tour_log.jsonl and backs up outputs

from __future__ import annotations
import os, json, time, shutil, re
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, List
from dotenv import load_dotenv

PROMPT_ID = "pmpt_68a25521819c8197b0ce22ebbb06b3600d589e1085511e96"
PROMPT_VERSION = "10"

load_dotenv() 

BASE = Path("src/data")
FILES = {
    "tour_in": BASE / "tour_input.json",
    "pois": BASE / "current_pois.json",
    "recheck": BASE / "recheck.json",
    "drop": BASE / "drop.json",
    "gpt_out": BASE / "gpt_output.json",
    "backups": BASE / "backups",
    "counter": BASE / "counter.txt",
    "log": BASE / "tour_log.jsonl",
    "vars_dump": "src/data/backups/prompt_vars_sent.json",
}
FILES["backups"].mkdir(parents=True, exist_ok=True)

def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def ensure_dirs():
    FILES["backups"].mkdir(parents=True, exist_ok=True)
    BASE.mkdir(parents=True, exist_ok=True)
    if not FILES["log"].exists():
        FILES["log"].touch()

def read_json(p: Path, default=None):
    if not p.exists():
        return default
    with open(p, "r") as f:
        return json.load(f)

def write_json(p: Path, obj: Any):
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    tmp.replace(p)

def append_log(event: Dict[str, Any]):
    event["ts"] = now_iso()
    with open(FILES["log"], "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")

def read_counter() -> int:
    try:
        return int(FILES["counter"].read_text().strip())
    except Exception:
        return 0

def backup_file(src: Path, stem: str, loop_id: int):
    if not src.exists():
        return
    dst = FILES["backups"] / f"{stem}_{loop_id:04d}.json"
    shutil.copyfile(src, dst)

def safe_dumps(obj: Any) -> str:
    # compact to save tokens but keep Unicode
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))

def extract_text(resp) -> str | None:
    """
    Try hard to extract a textual payload from Responses:
    - resp.output_text (when formatter is plain text)
    - resp.output[*].content[*].text  (common)
    - resp.output[*].content[*].json  (JSON Schema formatter)
    - fallback: model_dump_json() or str(resp)
    """
    # 1) direct field
    txt = getattr(resp, "output_text", None)
    if isinstance(txt, str) and txt.strip():
        return txt.strip()

    # 2) walk output blocks
    try:
        blocks = getattr(resp, "output", None) or getattr(resp, "outputs", None) or []
        texts, json_blobs = [], []
        for b in blocks or []:
            content = getattr(b, "content", None) or getattr(b, "contents", None) or []
            for part in content or []:
                # Some SDKs expose .text or .json; be permissive
                t = getattr(part, "text", None)
                if isinstance(t, str) and t.strip():
                    texts.append(t.strip())
                j = getattr(part, "json", None)
                if j is not None:
                    # ensure str for downstream parser
                    try:
                        json_blobs.append(json.dumps(j, ensure_ascii=False))
                    except Exception:
                        pass
        if json_blobs:
            # prefer the first JSON chunk – it’s usually the full answer
            return json_blobs[0]
        if texts:
            return "\n".join(texts).strip()
    except Exception:
        pass

    # 3) try a full dump if available (pydantic)
    try:
        dump = resp.model_dump_json()  # type: ignore[attr-defined]
        if isinstance(dump, str) and dump.strip():
            return dump
    except Exception:
        pass

    # 4) last resort
    s = str(resp)
    return s.strip() or None



def extract_json_blob(text: str) -> dict:
    """
    Extract the first complete top-level JSON object from model text.
    - Prefers a ```json fenced block if present.
    - Otherwise scans with a brace counter and returns the first object.
    """
    s = text.strip()
    if not s:
        raise ValueError("Empty model text.")

    # Prefer a fenced JSON block if present
    m = re.search(r"```(?:json)?\s*({.*?})\s*```", s, flags=re.DOTALL)
    if m:
        s = m.group(1)

    # Find first '{'
    start = s.find("{")
    if start == -1:
        raise ValueError("No JSON object found in model text.")

    # Brace-counter to locate end of first complete object
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        ch = s[i]

        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue

        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = s[start:i+1]
                return json.loads(candidate)

    raise ValueError("Unbalanced braces: could not extract JSON.")


def main():
    ensure_dirs()
    t0 = time.time()
    loop_id = read_counter()
    (FILES["backups"] / f"run_{loop_id:04d}_started.txt").write_text(now_iso())
    print(f"[{now_iso()}] Starting refinement loop {loop_id}")

    # --- Load inputs ---
    tour_in = read_json(FILES["tour_in"], default={}) or {}
    pois_doc = read_json(FILES["pois"], default={"pois": []}) or {"pois": []}
    recheck = read_json(FILES["recheck"], default=[]) or []
    drop = read_json(FILES["drop"], default=[]) or []

    city = tour_in.get("city", "")
    theme = tour_in.get("theme", "")
    mode = tour_in.get("mode", "walking")
    # flexible naming for target stops
    target_stops = int(tour_in.get("target_stops") or tour_in.get("stop_count") or 9)

    # Build kept list from current_pois.json (lean payload)
    kept: List[Dict[str, Any]] = []
    for p in (pois_doc.get("pois") or []):
        if p.get("status") == "keep":
            kept.append({
                "poi_id": p.get("poi_id"),
                "name": p.get("name"),
                "type": p.get("type"),
            })

    empty_slots = max(0, target_stops - len(kept))

    # --- If nothing to do, just log and exit gracefully ---
    if empty_slots == 0 and not recheck and not drop:
        append_log({
            "stage": "refinement",
            "status": "skipped",
            "reason": "no_empty_slots_and_no_flagged",
            "kept": len(kept),
            "target": target_stops,
            "empty_slots": empty_slots,
        })
        print("Nothing to refine: no empty slots and no flagged POIs.")
        return

    # --- Prepare variables for prompt v4 ---
    vars_for_prompt = {
        "city": city,
        "theme": theme,
        "mode": mode,
        "empty_slots": str(empty_slots),  # strings are safest for template vars
        "kept_pois_json": safe_dumps(kept),
        "recheck_pois_json": safe_dumps(recheck),
        "drop_pois_json": safe_dumps(drop),
    }

    # Dump what we sent (for debugging)
    write_json(FILES["vars_dump"], {
        "prompt_id": PROMPT_ID,
        "version": PROMPT_VERSION,
        "variables": vars_for_prompt
    })

    # --- Call OpenAI Responses with prompt id/version ---
    print(f"[{now_iso()}] Importing OpenAI …")
    from openai import OpenAI   # lazy import, so earlier steps still run
    print(f"[{now_iso()}] OpenAI imported.")

    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY_TOUR")
    if not api_key:
        msg = "Missing OPENAI_API_KEY environment variable (or OPENAI_API_KEY_TOUR)."
        append_log({"stage": "refinement", "status": "error", "error": msg})
        raise RuntimeError(msg)

    client = OpenAI(api_key=api_key, timeout=30)
    print(f"[{now_iso()}] Calling Responses API …")
    api_t0 = time.time()
    resp = client.responses.create(
        prompt={
            "id": PROMPT_ID,
            "version": PROMPT_VERSION,
            "variables": vars_for_prompt
        },
        max_output_tokens=3000,
        
    )
    print(f"[{now_iso()}] Responses API returned.")
    api_ms = int((time.time() - api_t0) * 1000)

    # --- Save raw response text for debugging ---
    raw_text = extract_text(resp)
    loop_id = read_counter()
    raw_dump_path = FILES["backups"] / f"gpt_raw_response_{loop_id:04d}.txt"
    with open(raw_dump_path, "w", encoding="utf-8") as f:
        f.write(raw_text or "")

    # Also dump the full response object for debugging
    full_dump_path = FILES["backups"] / f"gpt_response_full_{loop_id:04d}.json"
    try:
        if hasattr(resp, "model_dump_json"):
            full_dump_path.write_text(resp.model_dump_json())
        else:
            (FILES["backups"] / f"gpt_response_full_{loop_id:04d}.txt").write_text(str(resp))
    except Exception:
        pass

    if not raw_text or not raw_text.strip():
        append_log({
            "stage": "refinement",
            "status": "error",
            "error": "empty_model_response",
            "api_ms": api_ms,
        })
        raise RuntimeError("Empty response from model; cannot parse.")

    # --- Parse JSON from model ---
    try:
        parsed = extract_json_blob(raw_text)
    except Exception as e:
        append_log({
            "stage": "refinement",
            "status": "error",
            "error": f"json_parse_failed: {e}",
            "api_ms": api_ms,
        })
        raise

    # --- normalize output to a single 'proposals' list ---
    items = None
    container_key = None

    if isinstance(parsed, dict):
        for k in ("pois", "proposals", "fixed_and_replacements", "items", "results", "output"):
            v = parsed.get(k)
            if isinstance(v, list):
                items = v
                container_key = k
                break
    elif isinstance(parsed, list):
        items = parsed
        container_key = "<array>"

    if items is None:
        # save raw text and a short parsed preview for debugging
        (FILES["backups"] / f"gpt_output_raw_{loop_id:04d}.txt").write_text(raw_text)
        (FILES["backups"] / f"gpt_output_parsed_preview_{loop_id:04d}.json").write_text(
            json.dumps(parsed, ensure_ascii=False)[:2000]
        )
        raise RuntimeError(
            "Model output missing a proposals-style list "
            "(accepted: 'proposals','fixed_and_replacements','items','pois','results','output', or top-level array)."
        )

    def coerce_item(it: dict) -> dict:
        # Tolerate non-dict (rare), at least keep the name-ish value
        if not isinstance(it, dict):
            return {"name": str(it), "gpt_refined": False}

        status = (it.get("status") or "").lower()
        replacement_of = it.get("replacement_of") or it.get("replaces")
        note = it.get("note") or it.get("notes")

        out = {
            # DO NOT include 'poi_id' – slug later in merger
            "name": it.get("name"),
            "address": it.get("address"),
            "type": it.get("type"),
            # Prefer explicit gpt_refined; otherwise infer from status
            "gpt_refined": bool(it.get("gpt_refined", status in ("fixed", "fix", "recheck_fixed"))),
        }

        if replacement_of:
            out["replacement_of"] = replacement_of
        if note:
            out["note"] = note

        # Preserve useful optional fields if provided
        for k in ("alt_names", "hint", "importance", "narration_score", "teaser", "sources", "starting"):
            if k in it and it[k] is not None:
                out[k] = it[k]

        # Strip empty values
        out = {k: v for k, v in out.items() if v not in (None, "", [])}
        return out

    # Normalize items and write a clean object with ONLY "proposals"
    items = [coerce_item(x) for x in items]

    # Build a clean output object – do NOT keep the model's original container (e.g., "pois")
    final_out = {"proposals": items}

    # Backup previous file and write the new clean output
    backup_file(FILES["gpt_out"], "gpt_output", loop_id)
    write_json(FILES["gpt_out"], final_out)

    # For logging/metrics downstream
    proposals = final_out["proposals"]


    # --- Backup previous gpt_output and write new one ---
    backup_file(FILES["gpt_out"], "gpt_output", loop_id)
    write_json(FILES["gpt_out"], parsed)

    # --- Log success, with simple metrics ---
    t_ms = int((time.time() - t0) * 1000)
    n_new   = sum(1 for x in proposals if isinstance(x, dict) and x.get("gpt_refined") is False)
    n_fixes = sum(1 for x in proposals if isinstance(x, dict) and x.get("gpt_refined") is True)


    append_log({
        "stage": "refinement",
        "status": "ok",
        "api_ms": api_ms,
        "total_ms": t_ms,
        "empty_slots": empty_slots,
        "proposals_total": len(proposals),
        "proposals_fix": n_fixes,
        "proposals_new": n_new,
    })

    print(f"Refinement complete. Proposals: {len(proposals)} | fixes: {n_fixes} | new: {n_new}")

if __name__ == "__main__":
    main()
