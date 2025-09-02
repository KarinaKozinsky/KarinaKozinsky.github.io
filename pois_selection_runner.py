# pois_selection_runner.py
# Triple-run POI selector -> appends to gpt_output.json
# Requires: pip install openai>=1.40  (or latest)
# Env: OPENAI_API_KEY

from __future__ import annotations
from openai import OpenAI
from dotenv import load_dotenv
from pathlib import Path
from datetime import datetime, timezone
import json
import re, os
import uuid
from typing import Any

# ====== CONFIG ======
PROMPT_ID = "pmpt_689a6166e2d481968d04e8a42c7464cd056b21eb3bb9f9c4"
PROMPT_VERSION = "10"
MODEL = "gpt-5-mini"  # optional here; kept for logging
OUTFILE = Path("src/data/gpt_output.json")
INPUT_FILE = "src/data/tour_input.json"

# Load .env before client init
load_dotenv()

# Init client (single source of truth; do NOT re-create elsewhere)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

with open(INPUT_FILE, "r", encoding="utf-8") as f:
    tour_input = json.load(f)

CITY = tour_input["city"]
TOUR_TITLE = tour_input["tour_title"]
MAX_STOPS = tour_input["max_stops"]
PASS_DIRECTIVES = tour_input["pass_directives"]

_pd = tour_input.get("pass_directives", {})
if isinstance(_pd, str):
    # if JSON has a single string, reuse it for A/B/C
    PASS_DIRECTIVES = {"A": _pd, "B": _pd, "C": _pd}
elif isinstance(_pd, dict):
    # ensure all three keys exist (empty if missing)
    PASS_DIRECTIVES = {
        "A": _pd.get("A", ""),
        "B": _pd.get("B", ""),
        "C": _pd.get("C", ""),
    }
else:
    # anything else → default empties
    PASS_DIRECTIVES = {"A": "", "B": "", "C": ""}

    
# ====== UTIL ======
_slug_rx = re.compile(r"[^a-z0-9_-]+")

def slugify(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"\s+", "-", s)
    s = _slug_rx.sub("", s)
    return s or f"poi-{uuid.uuid4().hex[:8]}"

def dedupe_preserve_order(seq):
    seen = set()
    out = []
    for x in seq or []:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out

def ensure_shape(po):
    if not po.get("poi_id"):
        po["poi_id"] = slugify(po.get("name",""))
    else:
        po["poi_id"] = slugify(po["poi_id"])
    if "alt_names" in po:
        po["alt_names"] = dedupe_preserve_order(po["alt_names"])
    return po

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def load_outfile():
    if OUTFILE.exists():
        try:
            return json.loads(OUTFILE.read_text())
        except Exception:
            return {"runs": []}
    return {"runs": []}

def _coerce_to_dict(maybe: Any) -> dict:
    if isinstance(maybe, dict):
        return maybe
    if isinstance(maybe, list) and maybe:
        return _coerce_to_dict(maybe[0])
    if isinstance(maybe, str):
        s = maybe.strip()
        # fenced ```json ... ```
        m = re.search(r"```json\s*(\{.*?\})\s*```", s, re.S)
        if m:
            s = m.group(1)
        s = s.replace("“", '"').replace("”", '"').replace("’", "'")
        if s.startswith("{") and s.endswith("}"):
            return json.loads(s)
        # find largest balanced {...}
        start = s.find("{")
        if start != -1:
            depth, end = 0, None
            for i, ch in enumerate(s[start:], start):
                if ch == "{": depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            if end:
                chunk = s[start:end]
                try:
                    return json.loads(chunk)
                except json.JSONDecodeError:
                    chunk = re.sub(r"\t", " ", chunk)
                    chunk = re.sub(r"\\(?![\"/bfnrtu])", "", chunk)
                    return json.loads(chunk)
    raise RuntimeError(f"Unsupported parsed type: {type(maybe)}")

def extract_json(resp) -> dict:
    # 1) structured output
    parsed = getattr(resp, "output_parsed", None)
    if parsed is not None:
        return _coerce_to_dict(parsed)

    # 2) blocks (prefer parsed → text)
    out = getattr(resp, "output", None) or []
    buf = ""
    for block in out:
        for c in getattr(block, "content", []) or []:
            if getattr(c, "parsed", None) is not None:
                return _coerce_to_dict(c.parsed)
            t = getattr(c, "text", None)
            if t:
                buf += t

    # 3) raw text fallback
    raw = (getattr(resp, "output_text", "") or "").strip() or buf.strip()
    if not raw:
        raise RuntimeError("Empty model output")
    return _coerce_to_dict(raw)

def save_outfile(data):
    OUTFILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))

# ====== CORE ======
def run_pass(pass_label: str) -> dict:
    # Use the already-keyed global client
    directives = (PASS_DIRECTIVES.get(pass_label, "") or "").replace("{{max_stops}}", str(MAX_STOPS))

    resp = client.responses.create(
        max_output_tokens=4000,
        prompt={
            "id": PROMPT_ID,
            "version": PROMPT_VERSION,
            "variables": {
                "max_stops": str(MAX_STOPS),
                "tour_title": TOUR_TITLE,
                "city": CITY,
                "pass_directives": directives
            },
        },
    )

    parsed = extract_json(resp)

    # sanity guard: make sure it's a dict
    if not isinstance(parsed, dict):
        raise TypeError(f"Model output is not a dict (got {type(parsed)}): {parsed!r}")

    pois_raw = (parsed.get("pois", []) or [])[:MAX_STOPS]

    # Coerce each POI into a dict if model gave you strings
    pois = []
    for i, p in enumerate(pois_raw):
        if isinstance(p, dict):
            pois.append(p)
        elif isinstance(p, str):
            pois.append({"name": p})
        else:
            print(f"    ! Skipping unexpected POI at index {i}: {type(p)}")

    # Now safe to normalize
    cleaned = [ensure_shape(p) for p in pois]

    run_record = {
        "run_id": f"{now_iso()}_{CITY.lower().replace(' ', '-')}_{TOUR_TITLE.lower().replace(' ', '-')}",
        "pass": pass_label,
        "prompt_version": PROMPT_VERSION,
        "model": MODEL,
        "timestamp": now_iso(),
        "inputs": {"city": CITY, "tour_title": TOUR_TITLE, "max_stops": MAX_STOPS},
        "pois": cleaned,
        "errors": []
    }
    return run_record

def main():
    existing = load_outfile()
    runs = existing.get("runs", [])

    for label in ("A", "B", "C"):
        print(f"Running pass {label}...")
        try:
            record = run_pass(label)
            runs.append(record)
            print(f"  → got {len(record['pois'])} items")
        except Exception as e:
            err_record = {
                "run_id": f"{now_iso()}_ERROR",
                "pass": label,
                "prompt_version": PROMPT_VERSION,
                "model": MODEL,
                "timestamp": now_iso(),
                "inputs": {"city": CITY, "tour_title": TOUR_TITLE, "max_stops": MAX_STOPS},
                "pois": [],
                "errors": [repr(e)]
            }
            runs.append(err_record)
            print(f"  ! pass {label} failed: {e}")

    save_outfile({"runs": runs})
    total = sum(len(r.get("pois", [])) for r in runs[-3:])
    print(f"Done. Appended 3 runs. Total new POIs: {total}. Output -> {OUTFILE.resolve()}")

if __name__ == "__main__":
    # Quick sanity check to avoid silent env issues
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY not set in environment")
    main()
