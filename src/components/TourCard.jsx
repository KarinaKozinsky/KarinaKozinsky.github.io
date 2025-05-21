import React from "react";
import MapPreview from "./MapPreview";
import tour from "../data/tour_optimized.json";

// Optional helper to convert 121 min → "2h 1m"
const readableDuration = (min) => {
  const hrs = Math.floor(min / 60);
  const mins = Math.round(min % 60);
  return `${hrs}h${mins > 0 ? ` ${mins}m` : ""}`;
};

const metadata = tour.tour_metadata || {};
const stopsList = tour.stops || [];

const TourCard = ({
  title = "Gold, Grit & Humble Beginnings",
  rating = 4.5,
  price = 9.99,
  type = "Walking Tour",
  effort = metadata.effort || "Moderate Effort",
  duration = metadata.estimated_duration_minutes
    ? readableDuration(metadata.estimated_duration_minutes)
    : "2–2.5 h",
  distance = metadata.total_distance
    ? `${(metadata.total_distance / 1000).toFixed(2)} km`
    : "3.7 km",
  stops = stopsList.length || 6,
  center = metadata.centroid || { lat: 37.7749, lng: -122.4194 },
}) => {
  const styles = {
    card: {
      display: "flex",
      flexDirection: "column",
      width: "393px",
      height: "364px",
      padding: "16px",
      borderRadius: "24px",
      background: "#fff",
      gap: "8px",
      boxShadow: "0px 8px 20px rgba(0, 0, 0, 0.05)",
      fontFamily: "sans-serif",
    },
    mapWrapper: {
      position: "relative",
      height: "248px",
      borderRadius: "10px",
      overflow: "hidden",
    },
    bookmarkIcon: {
      position: "absolute",
      top: "14px",
      right: "14px",
      fontSize: "20px",
      zIndex: 1,
    },
    priceTag: {
      position: "absolute",
      bottom: "16px",
      right: "16px",
      background: "#fff",
      padding: "6px 12px",
      borderRadius: "8px",
      fontWeight: "bold",
      fontSize: "14px",
      zIndex: 1,
    },
    info: {
      display: "flex",
      flexDirection: "column",
      gap: "8px",
    },
    titleRating: {
      display: "flex",
      justifyContent: "space-between",
      fontWeight: "bold",
    },
    metadata: {
      display: "flex",
      flexWrap: "wrap",
      gap: "8px",
      fontSize: "14px",
      color: "#666",
    },
    dots: {
      display: "flex",
      gap: "5px",
    },
    dot: {
      width: "6px",
      height: "6px",
      borderRadius: "50%",
      background: "#d9d9d9",
    },
    dotActive: {
      background: "#161616",
    },
  };

  return (
    <div style={styles.card}>
      <div style={styles.mapWrapper}>
        <div style={styles.bookmarkIcon}>🔖</div>
        <div style={styles.priceTag}>${price}</div>
        <MapPreview center={center} zoom={20} />
      </div>

      <div style={styles.info}>
        <div style={styles.titleRating}>
          <span>{title}</span>
          <span>⭐ {rating}</span>
        </div>

        <div style={styles.metadata}>
          <span>🚶 {type}</span>
          <span>⚡ {effort}</span>
          <span>🕒 {duration}</span>
          <span>📍 {distance}</span>
          <span>🔢 {stops} Stops</span>
        </div>

        <div style={styles.dots}>
          <span style={{ ...styles.dot, ...styles.dotActive }}></span>
          <span style={styles.dot}></span>
          <span style={styles.dot}></span>
          <span style={styles.dot}></span>
          <span style={styles.dot}></span>
        </div>
      </div>
    </div>
  );
};

export default TourCard;
