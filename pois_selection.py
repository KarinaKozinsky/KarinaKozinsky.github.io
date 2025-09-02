import os
import json
from dotenv import load_dotenv
from openai import OpenAI

# --- CONFIG ---
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

PROMPT_ID = "pmpt_6896933c66848190b9c049bc24e9ffbd0b2d58010c001d63"
PROMPT_VERSION = "2"

# --- INPUTS ---
TOUR_TITLE = "Gold Rush"  # Update as needed
CITY = "San Francisco"    # Update as needed
STOP_COUNT = "10"            # Update as needed (integer)

OUTPUT_PATH = "src/data/gpt_output.json" 

# --- API CALL ---
response = client.responses.create(
    prompt={
        "id": PROMPT_ID,
        "version": PROMPT_VERSION,
        "variables": {
            "tour_title": TOUR_TITLE,
            "city": CITY,
            "stop_count": STOP_COUNT
        }
    },
    max_output_tokens=1500
)

# --- PARSE RESPONSE ---
def extract_json_from_response(response):
    # Look for JSON string in the OpenAI response structure
    for o in getattr(response, "output", []):
        if getattr(o, "type", "") == "message":
            content_list = getattr(o, "content", [])
            for content in content_list:
                text_json = getattr(content, "text", None)
                if text_json and isinstance(text_json, str):
                    try:
                        return json.loads(text_json)
                    except Exception as e:
                        print(f"Failed to parse as JSON: {e}")
                        print("Raw response:", text_json)
    print("No JSON string found in output.")
    return {}

parsed = extract_json_from_response(response)

# --- SAVE OUTPUT ---
with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    json.dump(parsed, f, ensure_ascii=False, indent=2)

print(f"\nTour selection saved to {OUTPUT_PATH}")

