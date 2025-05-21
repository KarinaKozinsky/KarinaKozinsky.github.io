import json

# Load optimized route (list of POI IDs)
with open('step4_optimized_route.json', 'r') as f:
    optimized_route = json.load(f)  # expects: ["yerba_buena_cove", "old_mint_sf", ...]

# Load full POI metadata
with open('pois_meta.json', 'r') as f:
    pois_meta = json.load(f)  # expects: list of POI objects

# Build a lookup dictionary for POIs by ID
poi_lookup = {poi['poi_id']: poi for poi in pois_meta}

# Prepare the tour data
tour = {
    "tour_id": "sf_gold_rush_tour_001",
    "title": "San Francisco Gold Rush Walking Tour",
    "summary": "Explore the key sites of San Francisco's Gold Rush era, from the old waterfront to hidden architectural gems.",
    "estimated_duration_minutes": sum(
        [
            next((d['duration_minutes'] for d in poi.get('distance_matrix_data', []) if d['to_poi_id'] == optimized_route[i + 1]), 0)
            for i, poi_id in enumerate(optimized_route[:-1])
            for poi in [poi_lookup[poi_id]]
        ]
    ),
    "poi_list": optimized_route
}

# Write tour.json
with open('tour.json', 'w') as f:
    json.dump(tour, f, indent=4)

print("✅ tour.json generated successfully!")
