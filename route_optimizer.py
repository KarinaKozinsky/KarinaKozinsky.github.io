#!/usr/bin/env python3
# optimizer.py — pick best walking route over all KEEP POIs
# # Strategy:
#  - Score each POI: poi_value_score = narration.mean × min(3.0, 1*primary + 0.7*secondary + 0.3*hidden_gem)
#  - Try Google Directions starting from the top-K scored POIs
#  - Choose the route whose start has the highest score; tie-break by shorter total distance


import json, os
from dotenv import load_dotenv
import googlemaps
from datetime import datetime

# --- CONFIG ---
load_dotenv()
API_KEY = os.getenv("VITE_GOOGLE_API_KEY")
if not API_KEY:
    raise ValueError("Missing Google API key!")

INPUT_FILE  = "src/data/current_pois.json"
OUTPUT_FILE = "src/data/tour_optimized.json"
TOP_K_STARTS = 3  # try routes starting from the top K POIs by score

# NEW: load user tour requirements
TOUR_INPUT_FILE = "src/data/tour_input.json"
try:
    with open(TOUR_INPUT_FILE, "r") as f:
        tour_cfg = json.load(f) or {}
except FileNotFoundError:
    tour_cfg = {}

req = tour_cfg.get("requirements", tour_cfg)  # support either shape

DEFAULT_MODE="walking" 
DEFAULT_MAX_TOTAL_KM=6.5 # target maximum total walking distance
DEFAULT_MAX_STOPS=8  # target maximum number of stops
DEFAULT_TOP_K_STARTS=3

MODE = tour_cfg.get("mode", DEFAULT_MODE)
MAX_TOTAL_KM = float(tour_cfg.get("max_total_km", DEFAULT_MAX_TOTAL_KM))
MAX_STOPS = int(tour_cfg.get("max_stops", DEFAULT_MAX_STOPS))
MODE = "walking"


gmaps = googlemaps.Client(key=API_KEY)


# --- HELPERS ---

# turn "flex"/"unlimited"/None into Python None
def _flex(v):
    if v is None: return None
    if isinstance(v, str) and v.strip().lower() in {"flex", "unlimited", "none"}:
        return None
    return v


def build_route_from_list(pois_list, start_idx):
    """Wrapper that calls directions_route + extract_ordered_pois + summarize_route."""
    directions, start, remaining = directions_route(pois_list, start_idx)
    if not directions:
        raise ValueError("No route returned from Google Directions API.")
    ordered, route_json = extract_ordered_pois(directions, start, remaining, pois_list)
    summary = summarize_route(route_json)
    return ordered, route_json, summary

def prune_route_greedy(pois_list, start_idx, max_km, max_stops):
    """
    Iteratively remove the POI with best (distance reduction) / (value loss)
    until the route fits (max_km, max_stops). Never removes the start POI.
    """
    # Work on a copy so we don't mutate the caller's list
    current = list(pois_list)
    sidx = int(start_idx)

    # Build initial route
    ordered, route_json, summary = build_route_from_list(current, sidx)

    # Keep pruning while above limits and we have enough stops to drop
    while (summary["total_distance_km"] > max_km or len(ordered) > max_stops) and len(current) > 2:
        baseline_km = summary["total_distance_km"]

        best_ratio = None
        best_drop_idx = None
        best_candidate_result = None
        best_gain_km = 0.0
        best_value_loss = None

        # Try removing each non-start POI once; pick the highest gain/value ratio
        for i, p in enumerate(current):
            if i == sidx:
                continue  # never drop the start
            # Remove candidate i and rebuild
            trial = current[:]
            dropped = trial.pop(i)
            # Adjust start index if we removed something before the start
            new_sidx = sidx - 1 if i < sidx else sidx

            try:
                ord2, route2, sum2 = build_route_from_list(trial, new_sidx)
            except Exception:
                continue  # skip any failure

            gain_km = max(0.0, baseline_km - sum2["total_distance_km"])
            value_loss = float(dropped.get("_poi_value_score", 0.0))
            ratio = gain_km / (value_loss if value_loss > 0 else 0.001)

            take = (best_ratio is None or ratio > best_ratio or
                    (abs(ratio - best_ratio) < 1e-9 and gain_km > best_gain_km))
            if take:
                best_ratio = ratio
                best_drop_idx = i
                best_candidate_result = (trial, new_sidx, ord2, route2, sum2)
                best_gain_km = gain_km
                best_value_loss = value_loss

        # If nothing improved, stop to avoid infinite loop
        if best_candidate_result is None:
            break

        # Apply the best drop
        current, sidx, ordered, route_json, summary = best_candidate_result

    return ordered, route_json, summary

def importance_votes_score(poi):
    v = poi.get("importance_votes", {}) or {}
    p = int(v.get("primary", 0))
    s = int(v.get("secondary", 0))
    h = int(v.get("hidden_gem", 0))
    # Weighted up to a cap of 3.0 (so 3 is the max “importance”)
    return min(3.0, 1.0*p + 0.7*s + 0.3*h)

def poi_value_score(poi):
    narr = ((poi.get("narration", {}) or {}).get("mean", 0.0)) or 0.0
    return importance_votes_score(poi) * float(narr)

def get_latlng(p):
    # Prefer the 'place' block if present, else top-level lat/lng
    pl = p.get("place") or {}
    lat = pl.get("lat", p.get("lat"))
    lng = pl.get("lng", p.get("lng"))
    if lat is None or lng is None:
        raise ValueError(f"POI {p.get('poi_id')} missing coordinates.")
    return lat, lng

def build_google_str(p):
    # Prefer Google's formatted address, else our address, else lat,lng
    pl = p.get("place") or {}
    if pl.get("formatted_address"):
        return pl["formatted_address"]
    if p.get("address"):
        return p["address"]
    lat, lng = get_latlng(p)
    return f"{lat},{lng}"

def get_starting_candidates(pois, k=3):
    # Pick top-k seeds by (importance_votes × narration.mean)
    scored = sorted(pois, key=lambda p: poi_value_score(p), reverse=True)
    return scored[:min(k, len(scored))]

def directions_route(pois, start_idx):
    # Build Directions API request for this ordering (walking, optimized waypoints)
    pois_copy = pois[:]  # shallow copy
    start = pois_copy.pop(start_idx)

    waypoints = [build_google_str(p) for p in pois_copy]
    origin = build_google_str(start)
    destination = build_google_str(pois_copy[-1]) if pois_copy else origin

    directions = gmaps.directions(
        origin=origin,
        destination=destination,
        mode=MODE,
        waypoints=waypoints[:-1] if len(waypoints) > 1 else None,
        optimize_waypoints=True if len(waypoints) > 1 else False,
        region="us"
    )
    return directions, start, pois_copy

def extract_ordered_pois(directions, start, remaining_in_input_order, all_pois):
    if not directions:
        raise ValueError("No route returned from Google Directions API.")
    route = directions[0]
    remaining_waypoints = remaining_in_input_order[:-1] if len(remaining_in_input_order) > 1 else []
    wpo = route.get("waypoint_order", list(range(len(remaining_waypoints))))
    ordered = [start] + [remaining_waypoints[i] for i in wpo]
    if remaining_in_input_order:
        ordered.append(remaining_in_input_order[-1])  # destination
    return ordered, route

def summarize_route(route_json):
    legs = route_json["legs"]
    total_distance = sum(l["distance"]["value"] for l in legs)  # meters
    total_duration = sum(l["duration"]["value"] for l in legs)  # seconds
    return {
        "stop_count": len(legs) + 1,
        "total_distance_km": round(total_distance / 1000, 2),
        "total_walking_minutes": round(total_duration / 60),
        # lightweight visit-time heuristic: add ~10 min per stop for narration/pauses
        "estimated_tour_duration_min": round(total_duration / 60 + (len(legs) + 1) * 10),
        "effort_level": "moderate",
    }

def main():
    # --- LOAD ---
    with open(INPUT_FILE, "r") as f:
        root = json.load(f)

    pois = root["pois"] if isinstance(root, dict) and "pois" in root else root
    pois = [p for p in pois if p.get("status") == "keep"]

    if len(pois) < 2:
        raise ValueError("Need at least 2 KEEP POIs to build a route.")

    # Pre-score POIs
    for p in pois:
        p["_poi_value_score"] = poi_value_score(p)

    # Choose top-K starts
    start_candidates = get_starting_candidates(pois, TOP_K_STARTS)

    best = None
    best_summary = None
    best_polyline = None
    best_route = None
    best_ids = None
    best_start_score = None

    for start_poi in start_candidates:
        try:
            start_idx = pois.index(start_poi)
            directions, start, remaining = directions_route(pois, start_idx)
            if not directions:
                continue

            ordered, route_json = extract_ordered_pois(directions, start, remaining, pois)
            summary = summarize_route(route_json)

            # Build full route from this start
            ordered_all, route_json_all, summary_all = build_route_from_list(pois, start_idx)

            # If route exceeds limits, prune greedily
            if summary_all["total_distance_km"] > MAX_TOTAL_KM or len(ordered_all) > MAX_STOPS:
                ordered, route_json, summary = prune_route_greedy(pois, start_idx, MAX_TOTAL_KM, MAX_STOPS)
                pruned = True
            else:
                ordered, route_json, summary = ordered_all, route_json_all, summary_all
                pruned = False

            # Route selection rule:
            #   1) prefer higher start poi_value_score
            #   2) tie-break on shorter total_distance_km
            start_score = start_poi["_poi_value_score"]
            dist_km = summary["total_distance_km"]

            print(
                f"Start: {start_poi.get('name')} (score={start_score:.3f}) "
                f"→ {len(ordered)} stops, {dist_km} km, ~{summary['estimated_tour_duration_min']} min"
                f"{' [pruned]' if pruned else ''}"
            )

            take_it = False
            if best is None:
                take_it = True
            else:
                if (start_score > best_start_score) or (
                    abs(start_score - best_start_score) < 1e-9 and dist_km < best_summary["total_distance_km"]
                ):
                    take_it = True

            if take_it:
                best = ordered
                best_summary = summary
                best_polyline = route_json.get("overview_polyline", {}).get("points")
                best_route = route_json
                best_ids = [p["poi_id"] for p in ordered]
                best_start_score = start_score


        except Exception as e:
            print(f"Error with start {start_poi.get('name')}: {e}")
            continue

    if best is None or best_route is None:
        raise RuntimeError("No viable route produced from the top-K start candidates.")
               
    # --- Extract legs for output ---
    legs_out = []
    legs = best_route.get("legs", [])
    for i, leg in enumerate(legs):
        from_poi = best_ids[i]
        to_poi = best_ids[i+1]
        dist_km = round(leg["distance"]["value"] / 1000, 2)
        duration_min = round(leg["duration"]["value"] / 60)
        legs_out.append({
            "from_poi_id": from_poi,
            "to_poi_id": to_poi,
            "distance_km": dist_km,
            "duration_min": duration_min,
            "summary": leg.get("summary", ""),
        })

    # --- WRITE OUTPUT (no tour-title dependency) ---
    output = {
        "computed_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "mode": MODE,
        "route_polyline": best_polyline,
        "stops": best,               # ordered POI objects
        "route_order": best_ids,     # ordered poi_ids
        "tour_metadata": best_summary,
        "legs": legs_out,
        "actual_start_id": best[0]["poi_id"],
        "start_poi_score": round(best[0].get("_poi_value_score", 0.0), 3),
    }

    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2)

    print(f"✅ Route optimization complete! {len(best)} stops, "
          f"{best_summary['total_distance_km']} km, {best_summary['estimated_tour_duration_min']} min")
    print(f"Best start: {best[0]['name']} (id: {best[0]['poi_id']}, score={output['start_poi_score']})")

if __name__ == "__main__":
    main()
