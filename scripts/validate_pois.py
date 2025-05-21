import json
import os
import googlemaps
import difflib

# === CONFIG ===
API_KEY = os.getenv("GOOGLE_API_KEY")  # Or replace with your API key directly for testing
INPUT_FILE = "tour_planner/pois.json"
OUTPUT_FILE = "tour_planner/validated_pois.json"
FLAGGED_FILE = "tour_planner/flagged_pois.json"
VERBOSE = True  # Set to False if you want less print output

# === INIT GMaps client ===
gmaps = googlemaps.Client(key=API_KEY)

# === Load POIs ===
with open(INPUT_FILE, "r") as f:
    pois = json.load(f)

validated = []
flagged = []

# === Helper: fuzzy name match confidence ===
def is_name_similar(original, result_name):
    score = difflib.SequenceMatcher(None, original.lower(), result_name.lower()).ratio()
    return score >= 0.6  # tweak if needed

# === Helper: check if cluster hint appears to be a location name ===
def is_location_mismatch(cluster_hint, resolved_address):
    if not cluster_hint:
        return False
    # Only flag mismatch if the cluster contains a location-like keyword
    location_keywords = ["san francisco", "chinatown", "bay", "mission", "castro", "soma", "california"]
    for keyword in location_keywords:
        if keyword in cluster_hint.lower():
            return keyword not in resolved_address.lower()
    return False


# === Helper: check if type is acceptable ===
def is_likely_valid_type(types):
    expected_keywords = [
        "museum", "tourist_attraction", "point_of_interest", "church", "park",
        "historical", "art", "library", "building", "landmark", "establishment"
    ]
    return any(any(keyword in t for keyword in expected_keywords) for t in types)

# === VALIDATION LOOP ===
for poi in pois:
    query = poi["title"]
    cluster = poi.get("clusterHint", "")
    search_query = f"{query}, {cluster}" if cluster else query

    try:
        if VERBOSE:
            print(f"🔎 Searching for: {search_query}")

        results = gmaps.places(query=search_query)
        candidates = results.get("results", [])

        if not candidates:
            poi["validation_status"] = "flagged"
            poi["reason"] = "No results found"
            flagged.append(poi)
            continue

        top_result = candidates[0]
        resolved_name = top_result.get("name", "")
        resolved_address = top_result.get("formatted_address", "")
        resolved_types = top_result.get("types", [])

        # Fuzzy name match
        similarity_score = difflib.SequenceMatcher(None, query.lower(), resolved_name.lower()).ratio()
        similar_name = similarity_score >= 0.6

        wrong_location = is_location_mismatch(cluster, resolved_address)

        poi["validated"] = True
        poi["resolved_place_id"] = top_result.get("place_id")
        poi["resolved_address"] = resolved_address
        poi["resolved_name"] = resolved_name
        poi["resolved_types"] = resolved_types
        poi["lat"] = top_result["geometry"]["location"]["lat"]
        poi["lng"] = top_result["geometry"]["location"]["lng"]
        poi["name_similarity_score"] = round(similarity_score, 2)
        poi["title_match_confidence"] = "high" if similar_name else "low"
        poi["candidates"] = [
            {
                "name": r.get("name"),
                "address": r.get("formatted_address"),
                "place_id": r.get("place_id"),
                "types": r.get("types", []),
            }
            for r in candidates[:3]
        ]

        # Logic to flag
        if wrong_location:
            poi["validation_status"] = "flagged"
            poi["reason"] = "Wrong location (likely wrong city)"
            flagged.append(poi)
        elif not similar_name and not is_likely_valid_type(resolved_types):
            poi["validation_status"] = "flagged"
            poi["reason"] = "Low confidence: name + type mismatch"
            flagged.append(poi)
        else:
            poi["validation_status"] = "validated"
            validated.append(poi)

        if VERBOSE:
            print(f"✅ Top result: {resolved_name} ({resolved_address})")
            print(f"   → Score: {poi['name_similarity_score']} | Wrong location: {wrong_location}")

    except Exception as e:
        poi["validation_status"] = "flagged"
        poi["reason"] = f"Error: {str(e)}"
        flagged.append(poi)
        if VERBOSE:
            print(f"❌ Error while processing '{query}': {e}")

# === Save outputs ===
with open(OUTPUT_FILE, "w") as out:
    json.dump(validated, out, indent=2)

with open(FLAGGED_FILE, "w") as out:
    json.dump(flagged, out, indent=2)

print(f"\n🎉 Done! {len(validated)} validated, {len(flagged)} flagged.")
