import os
import json
from dotenv import load_dotenv
from openai import OpenAI

print("Script started")

TOUR_PATH = "public/tours/sf/gold_rush/gold_rush.json"
RESEARCH_OUTPUT_PATH = "public/tours/tel-aviv/jaffa/jaffa_tour_research.json"
PROMPT_ID = "pmpt_6885ca3eb50881908dd5ff50454c2fa2010130b9641c69f6"

# Load your API key
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

# --- Load tour data ---
with open(TOUR_PATH, "r", encoding="utf-8") as f:
    tour = json.load(f)

# --- Helper to extract bullets (unchanged) ---
def extract_bullets_from_response(response):
    """
    Extracts the 'bullets' list from the OpenAI response object.
    """
    for o in getattr(response, "output", []):
        if getattr(o, "type", "") == "message":
            content_list = getattr(o, "content", [])
            for content in content_list:
                text_json = getattr(content, "text", None)
                if text_json and isinstance(text_json, str):
                    try:
                        parsed = json.loads(text_json)
                        bullets = parsed.get("bullets", [])
                        if isinstance(bullets, list):
                            return bullets
                    except Exception as e:
                        print(f"Failed to parse as JSON: {e}")
                        print("Raw text_json was:", text_json)
    print("No JSON string found in any output_text.")
    return []

# --- MAIN LOOP over all stops ---
research_results = {}

for stop in tour["stops"]:
    stop_name = stop["name"].strip()
    print(f"\n=== Researching: {stop_name} ===")
    prompt_vars = {
        "tour_title": tour["title"],
        "name": stop["name"],
        "address": stop["address"],
        "city": tour["city"],
    }
    response = client.responses.create(
        prompt={
            "id": PROMPT_ID,
            "version": "21",
            "variables": prompt_vars
        }
    )
    # Parse as before
    bullets = extract_bullets_from_response(response)
    # --- Remove 'source' from each bullet (safely) ---
    trimmed_bullets = []
    for b in bullets:
        # Handle both string and dict (to be safe)
        if isinstance(b, dict) and "fact" in b:
            trimmed_bullets.append(b["fact"])
        elif isinstance(b, str):
            # If somehow already a string, just add
            trimmed_bullets.append(b)
    # Use a normalized key (snake_case, like before)
    key = stop_name.lower().replace(" ", "_")
    research_results[key] = trimmed_bullets

    # Optional: Save intermediate progress
    with open(RESEARCH_OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(research_results, f, ensure_ascii=False, indent=2)

print(f"\nDone! Research saved to {RESEARCH_OUTPUT_PATH}")
