import os
import json
import re
from dotenv import load_dotenv
import googlemaps
from difflib import SequenceMatcher

# Load API key
load_dotenv()
API_KEY = os.getenv("VITE_GOOGLE_API_KEY")
gmaps = googlemaps.Client(key=API_KEY)

# ——— Utilities ———
def normalize_punct(text):
    mapping = {
        "‘": "'", "’": "'", "“": '"', "”": '"',
        "–": "-", "—": "-", "‐": "-", "″": '"', "′": "'"
    }
    for a, b in mapping.items():
        text = text.replace(a, b)
    return text.strip()

def strip_suffixes(text):
    suffixes = [" place", " site", " marker", " historic district"]
    t = normalize_punct(text)
    for s in suffixes:
        if t.lower().endswith(s):
            t = t[:-len(s)]
    return t.strip()

def extract_phrase_tokens(text):
    return re.findall(r"\b[a-zA-Z0-9]+\b", strip_suffixes(text).lower())

def phrase_token_fraction(query, result_name):
    query_tokens = set(extract_phrase_tokens(query))
    result_tokens = set(extract_phrase_tokens(result_name))
    if not query_tokens:
        return 0.0
    overlap = len(query_tokens & result_tokens)
    return overlap / len(query_tokens)

def similar(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

def generate_hint_variants(poi):
    variants = []
    if "search_hint" in poi:
        hint = strip_suffixes(normalize_punct(poi["search_hint"]))
        variants.append((hint, "search_hint"))
        variants.append((hint + " san francisco", "search_hint_city"))
    variants.append((strip_suffixes(poi["name"]), "name"))
    for alt in poi.get("alternative_names", []):
        variants.append((strip_suffixes(alt), "alt_name"))
    return variants

# ——— Debug function ———
def forward_lookup_debug(poi):
    variants = generate_hint_variants(poi)
    print(f"\n📌 Testing POI: {poi['name']}")
    print("Generated variants:")
    for v in variants:
        print(" -", v)

    for query, source in variants:
        print(f"\n🔎 Searching: {query} ({source})")
        res = gmaps.find_place(
            input=query,
            input_type="textquery",
            fields=["place_id", "name", "geometry", "business_status", "formatted_address"]
        )
        candidates = res.get("candidates", [])
        if not candidates:
            print("⚠️ No results from find_place, trying text_search...")
            res = gmaps.places(query=query)
            candidates = res.get("results", [])

        for c in candidates:
            score_query = similar(c["name"], query)
            token_fraction = phrase_token_fraction(query, c["name"])
            score_poi_name = similar(c["name"], poi["name"])
            print("→ Candidate:")
            print("  name:", c.get("name"))
            print("  address:", c.get("formatted_address"))
            print("  fuzzy vs query:", round(score_query, 2))
            print("  token fraction (query in result):", round(token_fraction, 2))
            print("  fuzzy vs POI name:", round(score_poi_name, 2))
            if token_fraction >= 0.9:
                print("  ✅ Accepted via query token fraction ≥ 0.9")
            print("  place_id:", c.get("place_id"))

# ——— Test POIs ———

# 1. Dragon Gate test
poi1 = {
    "poi_id": "chinatown_grant_ave",
    "name": "Chinatown Gate & Grant Avenue",
    "alternative_names": ["Dragon Gate", "Chinatown"],
    "search_hint": "Dragon Gate San Francisco",
    "address": "Bush St & Grant Ave, San Francisco, CA 94108"
}

# 2. Yerba Buena test
poi2 = {
    "poi_id": "yerba_buena_cove",
    "name": "Yerba Buena Cove Site",
    "alternative_names": ["Yerba Buena", "Old Waterfront"],
    "search_hint": "Yerba Buena Cove, San Francisco",
    "address": "Embarcadero at Mission St, San Francisco, CA 94105"
}

forward_lookup_debug(poi1)
forward_lookup_debug(poi2)
