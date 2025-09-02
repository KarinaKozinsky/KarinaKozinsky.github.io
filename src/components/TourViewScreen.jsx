import React, { useEffect, useState, useRef } from "react";
import MapPreview from "./MapPreview";
import { useNavigate } from "react-router-dom";
import { useAudioUnlock } from "../AudioUnlockContext";


// Simple Haversine function (meters)
function getDistanceMeters(lat1, lng1, lat2, lng2) {
  const toRad = (x) => (x * Math.PI) / 180;
  const R = 6371000;
  const dLat = toRad(lat2 - lat1);
  const dLng = toRad(lng2 - lng1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLng / 2) ** 2;
  return R * 2 * Math.asin(Math.sqrt(a));
}

export default function TourViewScreen() {
  const [tour, setTour] = useState(null);
  const stopRefs = useRef([]);
  const [activeStop, setActiveStop] = useState(0);
  const [userLocation, setUserLocation] = useState(null); 
  const [showTooFarModal, setShowTooFarModal] = useState(false);
  const navigate = useNavigate();
  const wakeLockRef = useRef(null);
  const { setAudioUnlocked } = useAudioUnlock();
  
  
  // Load tour JSON
  useEffect(() => {
    fetch("/tours/sf/gold_rush/gold_rush.json")
      .then(res => res.json())
      .then(setTour)
      .catch(console.error);
  }, []);

  // Wake lock function
  async function requestWakeLock() {
    try {
      if ('wakeLock' in navigator) {
        wakeLockRef.current = await navigator.wakeLock.request('screen');
        wakeLockRef.current.addEventListener('release', () => {
          console.log('Screen Wake Lock released');
        });
        console.log('Screen Wake Lock acquired');
      }
    } catch (err) {
      console.error(`Wake Lock failed: ${err.name}, ${err.message}`);
    }
  }

  // Call this on unmount to release wake lock
  useEffect(() => {
    return () => {
      if (wakeLockRef.current) {
        wakeLockRef.current.release();
      }
    };
  }, []);

  // Get user location once (not continuous)
  useEffect(() => {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(
      pos => {
        setUserLocation({
          lat: pos.coords.latitude,
          lng: pos.coords.longitude,
        });
      },
      err => {
        console.warn("Location error:", err);
      }
    );
  }, []);


  if (!tour) return <div>Loading…</div>;
  const stops = tour.stops || [];

  const handleStartTour = () => {
    if (!userLocation || !stops[0]) {
      navigate("/live"); // Fallback, or show an error
      return;
    }
    const dist = getDistanceMeters(
      userLocation.lat, userLocation.lng,
      stops[0].lat, stops[0].lng
    );
    const DISTANCE_THRESHOLD = 300; // meters
    if (dist > DISTANCE_THRESHOLD) {
      setShowTooFarModal(true);
    } else {
      requestWakeLock(); // <--- keep device unlocked
      setAudioUnlocked(true); //unlock autoplayback
      navigate("/live");
    }
  };

  return (
    <div
      style={{
        width: "100vw",
        height: "100vh",
        display: "flex",
        flexDirection: "column",
        background: "#fff",
        fontFamily: "sans-serif",
        alignItems: "center",
      }}
    >
      {/* Title Bar */}
      <div
        style={{
          width: "100%",
          maxWidth: 393,
          margin: "0 auto",
          padding: "24px 0 8px 0",
          textAlign: "center",
          fontSize: 22,
          fontWeight: 600,
          letterSpacing: 0.5,
          background: "#fff",
        }}
      >
        {tour.title || "Tour Title"}
      </div>
      {/* Main Content (map + stops) */}
      <div
        style={{
          width: "100%",
          maxWidth: 393,
          display: "flex",
          flexDirection: "column",
          margin: "0 auto",
          minHeight: 0,
        }}
      >
        {/* Map */}
        <div
          style={{
            width: "100%",
            height: 260,
            borderRadius: 16,
            overflow: "hidden",
            marginTop: 16,
          }}
        >
          <MapPreview 
          stops={stops} 
          activeStop={activeStop}
          userLocation={userLocation}
          visitedStops={[]}
          enableUserMarker={false}  
          />
        </div>
        {/* Stops List */}
        <div
          style={{
            flex: 1,
            minHeight: 0,
            width: "100%",
            maxWidth: 393,
            overflowY: "auto",
            boxSizing: "border-box",
            margin: "0 auto 8 auto",
          }}
        >
          {stops.map((stop, i) => (
            <div
              key={i}
              ref={el => stopRefs.current[i] = el}
              style={{
                margin: "8px 0",
                padding: 16,
                borderRadius: 10,
                background: i === activeStop ? "#e8e7ff" : "#f6f6f6",    // subtle purple highlight if active
                border: i === activeStop ? "2.5px solid #8C8CFF" : "1px solid #e5e5e5",
                fontWeight: 600,
                transition: "all 0.2s"
              }}
              onClick={() => {
                console.log("Stop tapped:", i, stop.name);
                setActiveStop(i);
              }}
            >
              <div>{i + 1}. {stop.name}</div>
              <div style={{ fontSize: 14, fontWeight: 400, marginTop: 8 }}>
                {stop.teaser || "No teaser yet."}
              </div>
            </div>
          ))}
        </div>
      </div>
      <button
        style={{
          width: "100%",
          maxWidth: 393,
          margin: "0 0 24px 0",
          padding: "18px 0",
          background: "#333333",
          color: "#fff",
          fontSize: 18,
          fontWeight: 600,
          borderRadius: 13,
          border: "none",
          cursor: "pointer",
          display: "block",
        }}
        onClick={handleStartTour}
      >
        Start Tour
      </button>

      {/* MODAL - INSIDE COMPONENT RETURN! */}
      {showTooFarModal && (
  <div style={{
    position: "fixed", top: 0, left: 0, width: "100vw", height: "100vh",
    background: "rgba(0,0,0,0.36)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000
  }}>
    <div style={{
      background: "#fff",
      borderRadius: 14,
      padding: 28,
      maxWidth: 340,
      textAlign: "center",
      boxShadow: "0 6px 24px rgba(0,0,0,0.18)"
    }}>
      <div style={{ fontWeight: 600, fontSize: 18, marginBottom: 14 }}>
        You’re too far from the starting point
      </div>
      <div style={{ marginBottom: 18 }}>
        What would you like to do?
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {/* Get Directions */}
        <button
          style={{
            background: "#8C8CFF", color: "#fff", border: "none",
            borderRadius: 8, padding: "10px 18px", fontWeight: 600
          }}
          onClick={() => {
            const first = stops[0];
            const url = `https://www.google.com/maps/dir/?api=1&destination=${first.lat},${first.lng}`;
            window.open(url, "_blank");
          }}
        >Get Directions</button>
        {/* Start the Tour Anyway */}
        <button
          style={{
            background: "#333", color: "#fff", border: "none",
            borderRadius: 8, padding: "10px 18px", fontWeight: 600
          }}
          onClick={() => {
            setShowTooFarModal(false);
            navigate("/live");
          }}
        >Start the Tour Anyway</button>
        {/* Cancel */}
        <button
          style={{
            background: "#ddd", color: "#333", border: "none",
            borderRadius: 8, padding: "10px 18px", fontWeight: 600
          }}
          onClick={() => setShowTooFarModal(false)}
        >Cancel</button>
      </div>
    </div>
  </div>
)}
    </div>
  );
}
