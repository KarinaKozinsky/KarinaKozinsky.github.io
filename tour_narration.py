import os
import json
from dotenv import load_dotenv
from openai import OpenAI

# --- CONFIG ---
TOUR_PATH = "public/tours/sf/gold_rush/gold_rush.json"
PLAN_PATH = "public/tours/sf/gold_rush/gold_rush_plan.json"
NARRATION_PATH = "public/tours/sf/gold_rush/gold_rush_narration.json"
PROMPT_ID = "pmpt_68b4cfc1a1608193bbd7bb8e10096c2206e1508b86e78f8b" 
PROMPT_VERSION = "4"                                               

# --- LOAD DATA ---
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

with open(TOUR_PATH, "r", encoding="utf-8") as f:
    tour = json.load(f)
with open(PLAN_PATH, "r", encoding="utf-8") as f:
    plan = json.load(f)

# --- Helpers ---
def norm(s: str) -> str:
    return " ".join((s or "").strip().lower().split())

def extract_narration_from_response(response):
    """
    Expects the stored prompt to return a JSON object like:
    {"name": "...", "text": "..."} as a single message.text string.
    """
    for o in getattr(response, "output", []):
        if getattr(o, "type", "") == "message":
            content_list = getattr(o, "content", [])
            for content in content_list:
                text_json = getattr(content, "text", None)
                if text_json and isinstance(text_json, str):
                    try:
                        parsed = json.loads(text_json)
                        name = parsed.get("name", "")
                        text = parsed.get("text", "")
                        if name and text:
                            return {"name": name, "text": text}
                    except Exception as e:
                        print(f"Failed to parse JSON: {e}")
                        print("Raw text_json was:", text_json[:500] + ("..." if len(text_json) > 500 else ""))
    print("No valid JSON narration found.")
    return None

def load_existing_narrations(path):
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            # If somehow not a list, wrap it so we don't crash
            return [data]
    except Exception as e:
        print(f"Warning: failed to read {path}: {e}")
        return []

def save_narrations(path, narrations_list):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(narrations_list, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

# --- Index tour stops by normalized name for matching plan -> tour ---
tour_by_name = {norm(s["name"]): s for s in tour.get("stops", [])}

# --- Load (and index) existing narrations to support resume/append ---
existing = load_existing_narrations(NARRATION_PATH)

# Prefer to dedupe by poi_id when available; fall back to normalized name
done_poi_ids = {item.get("poi_id") for item in existing if item.get("poi_id")}
done_names   = {norm(item.get("name", "")) for item in existing}

print(f"Found {len(existing)} existing narrations.")
wrote_any = False

# --- Iterate through plan stops one-by-one ---
for i, stop_plan in enumerate(plan.get("stops", []), start=1):
    plan_name = stop_plan.get("name", "")
    plan_key = norm(plan_name)
    tour_stop = tour_by_name.get(plan_key)

    if not tour_stop:
        print(f"[{i}] SKIP (no tour stop match): '{plan_name}'")
        continue

    poi_id = tour_stop.get("poi_id")
    if poi_id and poi_id in done_poi_ids:
        print(f"[{i}] SKIP (already have poi_id): {poi_id} — '{plan_name}'")
        continue
    if (not poi_id) and (plan_key in done_names):
        print(f"[{i}] SKIP (already have name): '{plan_name}'")
        continue

    bullets = stop_plan.get("bullets", [])
    address = tour_stop.get("address", "")

    prompt_vars = {
        "tour_title": tour.get("title", ""),
        "city": tour.get("city", ""),
        "name": plan_name,
        "address": address,
        "bullets": "\n".join(bullets)
    }

    print(f"[{i}] Calling model for: '{plan_name}' ...")
    try:
        response = client.responses.create(
            prompt={
                "id": PROMPT_ID,
                "version": PROMPT_VERSION,
                "variables": prompt_vars
            },
            max_output_tokens=3500  # keep as-is per your current setup
        )
    except Exception as e:
        print(f"[{i}] ERROR calling API for '{plan_name}': {e}")
        continue

    narration = extract_narration_from_response(response)
    if not narration:
        print(f"[{i}] No narration parsed for '{plan_name}'.")
        continue

    # Attach poi_id for reliable future merging/dedup
    narration_record = {
        "poi_id": poi_id,
        "name": narration.get("name", plan_name),
        "address": address,
        "text": narration.get("text", "")
    }

    # Append and save immediately (so progress persists even if interrupted)
    existing.append(narration_record)
    save_narrations(NARRATION_PATH, existing)
    wrote_any = True
    print(f"[{i}] Saved narration for '{plan_name}' (poi_id={poi_id}).")

if wrote_any:
    print(f"All done. Narrations appended to {NARRATION_PATH}")
else:
    print("No new narrations were written (everything already present or skipped).")
