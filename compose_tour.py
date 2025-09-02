#!/usr/bin/env python3
# compose_tour.py — build a single app-ready tour JSON
# Inputs:
#   - src/data/tour_input.json      (meta + desired slugs/labels)
#   - src/data/tour_optimized.json  (ordered stops + polyline + summary)
# Output:
#   - public/tours/<city_dir>/<tour_dir>/<tour_slug>.json

import json, os, re, sys
from datetime import datetime
from math import fsum

INPUT_TOUR   = "src/data/tour_input.json"
INPUT_OPT    = "src/data/tour_optimized.json"
PUBLIC_ROOT  = "public/tours"

def slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"-+", "-", s)
    return s or "tour"

def pick_address(p: dict) -> str:
    # Prefer Google formatted address if available
    place = p.get("place") or {}
    if place.get("formatted_address"):
        return place["formatted_address"]
    return p.get("address") or ""

def pick_latlng(p: dict) -> tuple[float,float]:
    # Prefer 'place' coords, else top-level
    place = p.get("place") or {}
    lat = place.get("lat", p.get("lat"))
    lng = place.get("lng", p.get("lng"))
    if lat is None or lng is None:
        raise ValueError(f"Stop {p.get('poi_id') or p.get('name')} missing lat/lng.")
    return float(lat), float(lng)

def centroid(points):
    # simple mean centroid for map defaults
    if not points:
        return None
    lat_sum = fsum(p[0] for p in points)
    lng_sum = fsum(p[1] for p in points)
    n = len(points)
    return {"lat": round(lat_sum / n, 6), "lng": round(lng_sum / n, 6)}

def main():
    # ---- Load inputs ----
    try:
        with open(INPUT_TOUR, "r", encoding="utf-8") as f:
            t_in = json.load(f)
    except Exception as e:
        print(f"❌ Failed to read {INPUT_TOUR}: {e}")
        sys.exit(1)

    try:
        with open(INPUT_OPT, "r", encoding="utf-8") as f:
            opt = json.load(f)
    except Exception as e:
        print(f"❌ Failed to read {INPUT_OPT}: {e}")
        sys.exit(1)

    # ---- Pull meta from tour_input.json ----
    tour_id     = t_in.get("tour_id") or slugify(t_in.get("title") or "tour")
    title       = t_in.get("title") or "Untitled Tour"
    city        = t_in.get("city") or "Unknown City"
    description = t_in.get("description") or ""
    mode        = (t_in.get("mode") or "walking").lower()
    effort      = t_in.get("effort_level") or "moderate"

    # Optional explicit path hints; otherwise derive from title/city
    city_dir = t_in.get("city_dir") or slugify(city)
    tour_dir = t_in.get("tour_dir") or slugify(title)
    tour_slug = t_in.get("tour_slug") or slugify(title)

    # ---- Pull route/meta from tour_optimized.json ----
    route_polyline = opt.get("route_polyline")
    summary_in     = opt.get("tour_metadata") or {}
    stops_in       = opt.get("stops") or []

    if not stops_in:
        print("❌ No stops found in optimizer output.")
        sys.exit(1)

    # ---- Sanitize stops ----
    stops_out = []
    coords_for_centroid = []

    for s in stops_in:
        poi_id = s.get("poi_id") or slugify(s.get("name") or "")
        name   = s.get("name") or poi_id
        lat, lng = pick_latlng(s)
        addr  = pick_address(s)
        teaser = s.get("teaser") or ""

        stops_out.append({
            "poi_id": poi_id,
            "name": name,
            "lat": lat,
            "lng": lng,
            "address": addr,
            "teaser": teaser,
            "narration_text": None,   # placeholder for narration pipeline
            "narration_audio": None,  # placeholder for TTS/asset path
            "images": [],             # optional future use
        })
        coords_for_centroid.append((lat, lng))

    # ---- Build summary (rename + ensure stop_count) ----
    summary = {
        "stop_count": len(stops_out),
        "total_distance_km": summary_in.get("total_distance_km"),
        "total_walking_minutes": summary_in.get("total_walking_minutes"),
        "estimated_tour_duration_min": summary_in.get("estimated_tour_duration_min"),
        "effort_level": effort,  # mirror for convenience in UI
    }

    out = {
        "schema_version": "1.0",
        "computed_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",

        "tour_id": tour_id,
        "title": title,
        "city": city,
        "description": description,
        "mode": mode,
        "effort_level": effort,

        "route_polyline": route_polyline,
        "summary": summary,
        "centroid": centroid(coords_for_centroid),

        "actual_start_id": opt.get("actual_start_id"),
        "stops": stops_out,
    }

    # ---- Write to public/tours/<city_dir>/<tour_dir>/<tour_slug>.json ----
    out_dir = os.path.join(PUBLIC_ROOT, city_dir, tour_dir)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{tour_slug}.json")

    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    os.replace(tmp, out_path)

    print(f"✅ Wrote tour → {out_path}")
    print(f"   Stops: {len(stops_out)} | Distance: {summary['total_distance_km']} km | Duration: {summary['estimated_tour_duration_min']} min")

if __name__ == "__main__":
    main()
