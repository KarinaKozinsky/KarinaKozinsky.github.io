import os
import json
import re
from dotenv import load_dotenv
from openai import OpenAI

print("Tour plan script started")

TOUR_PATH = "public/tours/sf/gold_rush/gold_rush.json"
RESEARCH_PATH = "public/tours/sf/gold_rush/gold_rush_research.json"
PLAN_OUTPUT_PATH = "public/tours/sf/gold_rush/gold_rush_plan.json"
PROMPT_ID = "pmpt_68b49f50f79c819495f584a8fb198aa30d89bc3223d5361f"  
PROMPT_VERSION = "4"  

# Load API key
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

# --- Helpers ---
def trim_links(bullets):
    """Remove any URLs (parentheses style) from each bullet."""
    return [re.sub(r"\s*\([^)]*\)", "", b).strip() for b in bullets]

def format_stops_for_prompt(stops):
    """
    Takes a list of {'name': ..., 'bullets': [...]} and returns a markdown string.
    """
    out = []
    for stop in stops:
        out.append(f"## {stop['name']}")
        for bullet in stop["bullets"]:
            out.append(f"- {bullet}")
        out.append("")  # Extra newline between stops
    return "\n".join(out)

def extract_stops_from_response(response):
    # 1) Preferred: structured tool output (strict JSON schema)
    for o in getattr(response, "output", []):
        if getattr(o, "type", "") == "tool" and getattr(o, "name", "") == "tour_plan":
            # Depending on SDK version this can be .arguments or .output/.json
            for attr in ("arguments", "output", "json"):
                payload = getattr(o, attr, None)
                if isinstance(payload, dict) and "stops" in payload:
                    return payload["stops"]

    # 2) Legacy/plain: message text containing a JSON string
    for o in getattr(response, "output", []):
        if getattr(o, "type", "") == "message":
            for c in getattr(o, "content", []):
                # Some SDKs label this "output_text", others "text"
                text = getattr(c, "text", None)
                if isinstance(text, str):
                    try:
                        parsed = json.loads(text)
                        if isinstance(parsed, dict) and "stops" in parsed:
                            return parsed["stops"]
                    except Exception:
                        pass

    # 3) Fallback: top-level output_text (SDK convenience field)
    if hasattr(response, "output_text") and isinstance(response.output_text, str):
        try:
            parsed = json.loads(response.output_text)
            if "stops" in parsed:
                return parsed["stops"]
        except Exception:
            pass

    print("No structured tool output or JSON message found.")
    return []


# --- Load data ---
with open(TOUR_PATH, "r", encoding="utf-8") as f:
    tour = json.load(f)
with open(RESEARCH_PATH, "r", encoding="utf-8") as f:
    research = json.load(f)

# --- Compose prompt variables ---
# We will pass the stops with trimmed bullets
stops = []
for stop in tour["stops"]:
    stop_name = stop["name"]
    key = stop_name.strip().lower().replace(" ", "_")
    bullets = research.get(key, [])
    stops.append({
        "name": stop_name,
        "bullets": trim_links(bullets)
    })

prompt_vars = {
    "tour_title": tour["title"],
    "city": tour["city"],
    "stops_bullets": format_stops_for_prompt(stops)
}

# --- Call OpenAI API ---
response = client.responses.create(
    prompt={
        "id": PROMPT_ID,
        "version": PROMPT_VERSION,
        "variables": prompt_vars
    },
    max_output_tokens=6000
)

# --- Parse response & save ---
tour_plan_stops = extract_stops_from_response(response)

# Save as output (schema: {"stops": [...]})
with open(PLAN_OUTPUT_PATH, "w", encoding="utf-8") as f:
    json.dump({"stops": tour_plan_stops}, f, ensure_ascii=False, indent=2)

print(response.model_dump_json(indent=2))


print(f"Tour plan saved to {PLAN_OUTPUT_PATH}")
print([ (o.type, getattr(o, "name", None)) for o in getattr(response, "output", []) ])

