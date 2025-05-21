#!/usr/bin/env python3
import json
import os
import re
import logging
from pathlib import Path
from datetime import datetime
from difflib import SequenceMatcher
from typing import List, Dict
from math import radians, cos, sin, asin, sqrt
from dotenv import load_dotenv
import googlemaps

# ——— Configuration ———
load_dotenv()
API_KEY = os.getenv("VITE_GOOGLE_API_KEY")
if not API_KEY:
    raise ValueError("Google API Key not found in environment variables!")

BASE_DIR = Path("src/data")
INPUT_FILE = BASE_DIR / "pois_for_script_validation.json"
CLEAN_FILE = BASE_DIR / "clean_pois.json"
FLAGGED_FILE = BASE_DIR / "flagged_pois_for_gpt.json"
LOG_FILE = BASE_DIR / "logs" / f"pois_validation_{datetime.now().date()}.json"

NAME_SIM_THRESHOLD = 0.6
HAVERSINE_RECHECK_THRESHOLD = 3000
HAVERSINE_DROP_THRESHOLD = 5000
SUFFIXES = [" place", " site", " marker", " historic district"]

gmaps = googlemaps.Client(key=API_KEY)
logging.basicConfig(level=logging.INFO)

# ——— Helpers ———
def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

def normalize_punct(text: str) -> str:
    mapping = {
        "‘": "'", "’": "'", "“": '"', "”": '"',
        "–": "-", "—": "-", "‐": "-", "″": '"', "′": "'"
    }
    for a, b in mapping.items():
        text = text.replace(a, b)
    return text.strip()

def strip_suffixes(text: str) -> str:
    t = normalize_punct(text)
    for s in SUFFIXES:
        if t.lower().endswith(s.lower()):
            t = t[:-len(s)]
    return t.strip()

def extract_phrase_tokens(text: str) -> List[str]:
    return re.findall(r"\b[a-zA-Z0-9]+\b", strip_suffixes(text).lower())

def is_valid_address(addr: str) -> bool:
    if not addr:
        return False
    has_number = bool(re.search(r"\d+", addr))
    has_intersection = " & " in addr or "/" in addr
    has_street_type = any(st in addr.lower() for st in ["st", "ave", "blvd", "road", "lane", "dr", "way"])
    return has_number or has_intersection or has_street_type

def generate_hint_variants(poi) -> List[tuple]:
    variants = []
    if "search_hint" in poi:
        hint = strip_suffixes(normalize_punct(poi["search_hint"]))
        variants.append((hint, "search_hint"))
        variants.append((hint + " san francisco", "search_hint_city"))
    variants.append((strip_suffixes(poi["name"]), "name"))
    for alt in poi.get("alternative_names", []):
        variants.append((strip_suffixes(alt), "alt_name"))
    return variants

def reverse_anchor_if_intersection(poi, coords):
    if " & " in poi["address"] and coords:
        rev = gmaps.reverse_geocode((coords["lat"], coords["lon"]))
        for place in rev:
            types = place.get("types", [])
            if any(t in types for t in ["premise", "point_of_interest", "establishment"]):
                better_address = place.get("formatted_address")
                if better_address and better_address != poi["address"]:
                    poi["raw_address"] = poi["address"]
                    poi["address"] = better_address
                    set_validation(poi, "script", "recheck", f"intersection → updated anchor: {better_address}")
                break

def haversine(lat1, lon1, lat2, lon2) -> float:
    R = 6371000
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return R * 2 * asin(sqrt(a))

def forward_lookup_with_token_check(poi) -> tuple:
    core_tokens = extract_phrase_tokens(poi["name"])
    variants = generate_hint_variants(poi)

    best_match = None
    best_score = 0.0
    best_token_match_fraction = 0.0
    best_address = None
    matched_by = None
    high_score_suspect = False

    for variant, source in variants:
        res = gmaps.find_place(
            input=variant,
            input_type="textquery",
            fields=["place_id", "name", "geometry", "business_status", "formatted_address"]
        )
        for c in res.get("candidates", []):
            match_tokens = extract_phrase_tokens(c["name"])
            token_overlap = sum(1 for t in core_tokens if t in match_tokens)
            token_match_fraction = token_overlap / len(core_tokens) if core_tokens else 0

            all_names = [poi["name"]] + poi.get("alternative_names", [])
            score = max(similar(c["name"], n) for n in all_names)

            if token_match_fraction < 0.75 and score > 0.8:
                high_score_suspect = True

            if token_match_fraction >= 0.5 and score > best_score:
                best_score = score
                best_token_match_fraction = token_match_fraction
                best_match = c
                best_address = c.get("formatted_address")
                matched_by = source

    return best_match, best_score, best_token_match_fraction, high_score_suspect, best_address, matched_by

def set_validation(poi, who, status, reason):
    poi["validated_by"] = who
    poi["validation_status"] = status
    poi["status_reason"] = reason

def apply_outlier_check_by_neighbor(pois: List[Dict]):
    coords = [
        (p["poi_id"], p["coordinates"]["lat"], p["coordinates"]["lon"])
        for p in pois
        if p.get("validation_status") != "drop"
        and "coordinates" in p and "lat" in p["coordinates"] and "lon" in p["coordinates"]
    ]
    for i, (pid1, lat1, lon1) in enumerate(coords):
        dists = [
            haversine(lat1, lon1, lat2, lon2)
            for j, (pid2, lat2, lon2) in enumerate(coords) if i != j
        ]
        if not dists:
            continue
        min_dist = min(dists)
        poi = next(p for p in pois if p["poi_id"] == pid1)
        poi["distance_to_nearest_poi_m"] = round(min_dist)
        if min_dist > HAVERSINE_DROP_THRESHOLD:
            set_validation(poi, "script", "drop", f"true outlier (nearest={round(min_dist)}m)")
        elif min_dist > HAVERSINE_RECHECK_THRESHOLD and poi.get("validation_status") == "keep":
            set_validation(poi, "script", "recheck", f"potential outlier (nearest={round(min_dist)}m)")

def validate_pois(pois: List[Dict]) -> List[Dict]:
    flagged = []
    valid_pois = []

    for poi in pois:
        match, score, token_match_fraction, high_score_suspect, formatted_address, matched_by = forward_lookup_with_token_check(poi)

        addr_score = 0.0
        if formatted_address:
            addr_score = similar(poi.get("address", ""), formatted_address)
            poi["address"] = formatted_address

        coords = match.get("geometry", {}).get("location") if match else None
        if coords:
            poi["coordinates"] = {"lat": coords["lat"], "lon": coords["lng"]}
            reverse_anchor_if_intersection(poi, poi["coordinates"])

        if matched_by:
            poi["matched_by"] = matched_by

        if match and match.get("business_status") == "CLOSED_PERMANENTLY":
            set_validation(poi, "script", "drop", "closed_permanently")
            flagged.append(poi)
            continue

        if matched_by and matched_by.startswith("search_hint") and coords and is_valid_address(poi["address"]):
            set_validation(poi, "script", "keep", "fallback: matched via search_hint + valid address")
            valid_pois.append(poi)
            continue

        if high_score_suspect:
            set_validation(poi, "script", "recheck", "high fuzzy match, weak token match")
            flagged.append(poi)
            continue

        if score < NAME_SIM_THRESHOLD:
            set_validation(poi, "script", "recheck", f"name_match_score={score:.2f}")
            flagged.append(poi)
            continue

        set_validation(poi, "script", "keep", f"name_match_score={score:.2f}")
        valid_pois.append(poi)

    return valid_pois + flagged

def main():
    BASE_DIR.joinpath("logs").mkdir(exist_ok=True)

    with open(INPUT_FILE) as f:
        raw_data = json.load(f)
    input_pois = raw_data["stops"] if isinstance(raw_data, dict) else raw_data

    clean_pois = []
    if CLEAN_FILE.exists() and CLEAN_FILE.stat().st_size > 0:
        with open(CLEAN_FILE) as f:
            clean_pois = json.load(f)

    validated = validate_pois(input_pois)
    keeps = [p for p in validated if p.get("validation_status") == "keep"]
    flagged = [p for p in validated if p.get("validation_status") in ["drop", "recheck"]]

    clean_dict = {p["poi_id"]: p for p in clean_pois}
    for p in keeps:
        clean_dict[p["poi_id"]] = p
    with open(CLEAN_FILE, "w") as f:
        json.dump(list(clean_dict.values()), f, indent=2)

    with open(FLAGGED_FILE, "w") as f:
        json.dump(flagged, f, indent=2)

    all_pois = list(clean_dict.values()) + flagged
    apply_outlier_check_by_neighbor(all_pois)

    with open(LOG_FILE, "w") as f:
        json.dump(validated, f, indent=2)

    logging.info(f"✅ Done. Kept: {len(keeps)}, Flagged: {len(flagged)}")
    print(f"✅ Validation complete. Kept: {len(keeps)}, Flagged: {len(flagged)}")

if __name__ == "__main__":
    main()
