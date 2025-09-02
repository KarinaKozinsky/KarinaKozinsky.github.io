import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import MapPreview from "./MapPreview";

const readableDuration = (min) => {
  const hrs = Math.floor(min / 60);
  const mins = Math.round(min % 60);
  return `${hrs}h${mins > 0 ? ` ${mins}m` : ""}`;
};

export default function TourCard({
  src = "/tours/sf/gold_rush/gold_rush.json",
  rating = 4.5,
  price = 9.99,
}) {
  const [tour, setTour] = useState(null);

  useEffect(() => {
    let mounted = true;
    fetch(src).then(r => r.json()).then(d => { if (mounted) setTour(d); });
    return () => { mounted = false; };
  }, [src]);

  if (!tour) return null;

  const stops = tour.stops || [];
  const summary = tour.summary || {};
  const title = tour.title || "Tour Title";
  const mode = tour.mode ? `${tour.mode[0].toUpperCase()}${tour.mode.slice(1)}` : "Walking";
  const effort = tour.effort_level ? tour.effort_level : "moderate";
  const distance =
    tour.total_distance_km ?? summary.total_distance_km ?? null;
  const durationMin =
    tour.estimated_tour_duration_min ?? summary.estimated_tour_duration_min ?? null;

  const styles = {
    outer: {
      width: "100%",
      maxWidth:400,
      padding: 8,               // keeps it off screen edges
      boxSizing: "border-box",
    },
    link: {
      display: "block",
      width: "100%",
      textDecoration: "none",
    },
    card: {
      width: "100%",
      boxSizing: "border-box",
      display: "flex",
      flexDirection: "column",
      justifyContent: "center",
      maxWidth: 400,             // target design width
      borderRadius: 16,
      background: "#fff",
      boxShadow: "0px 8px 20px rgba(0, 0, 0, 0.05)",
      fontFamily: "sans-serif",
      gap: 8,
      padding: 8
    },
    mapWrapper: {
      position: "relative",
      width: "100%",
      aspectRatio: "4 / 3",      // responsive height
      minHeight: 200,            // safety for older browsers
      borderRadius: 12,
      overflow: "hidden",
    },
    priceTag: {
      position: "absolute",
      bottom: 16,
      right: 16,
      background: "#fff",
      padding: "6px 12px",
      borderRadius: 8,
      fontWeight: "bold",
      fontSize: 14,
      zIndex: 1,
      boxShadow: "0 2px 8px rgba(0,0,0,0.08)",
    },
    info: { display: "flex", flexDirection: "column", gap: 8 },
    titleRow: {
      display: "flex",
      justifyContent: "space-between",
      fontWeight: 700,
    },
    meta: {
      display: "flex",
      flexWrap: "wrap",
      gap: 8,
      fontSize: 14,
      color: "#666",
    },
    dots: { display: "flex", gap: 5, },
    dot: {
      width: 6, height: 6, borderRadius: "50%", background: "#d9d9d9",
    },
    dotActive: { background: "#161616" },
  };

  return (
    <div style={styles.outer}>
      <Link to="/tour" style={styles.link}>
        <div style={styles.card}>
          <div style={styles.mapWrapper}>
            <div style={styles.priceTag}>${price}</div>
            <MapPreview polyline={tour.route_polyline} stops={stops} />
          </div>

          <div style={styles.info}>
            <div style={styles.titleRow}>
              <span>{title}</span>
              <span>⭐ {rating}</span>
            </div>
            <div style={styles.meta}>
              <span>🚶 {mode}</span>
              <span>⚡ {effort}</span>
              <span>🕒 {durationMin ? readableDuration(durationMin) : "N/A"}</span>
              <span>📍 {distance != null ? `${distance} km` : "N/A"}</span>
              <span>🔢 {stops.length} Stops</span>
            </div>
            <div style={styles.dots}>
              <span style={{ ...styles.dot, ...styles.dotActive }} />
              <span style={styles.dot} />
              <span style={styles.dot} />
              <span style={styles.dot} />
              <span style={styles.dot} />
            </div>
          </div>
        </div>
      </Link>
    </div>
  );
}
