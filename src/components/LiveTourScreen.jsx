import React, { useEffect, useState, useRef } from "react";
import MapPreview from "./MapPreview";
import { MdPlayArrow, MdPause, MdSettings } from "react-icons/md";
import { useAudioUnlock } from "../AudioUnlockContext";
import { NarrationProgressBar } from "./NarrationProgressBar";

// --- Helper: Distance ---
function getDistanceMeters(lat1, lng1, lat2, lng2) {
  const toRad = (x) => (x * Math.PI) / 180;
  const R = 6371000;
  const dLat = toRad(lat2 - lat1);
  const dLng = toRad(lng2 - lng1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) *
      Math.cos(toRad(lat2)) *
      Math.sin(dLng / 2) ** 2;
  return R * 2 * Math.asin(Math.sqrt(a));
}

// --- Helper: Real stop index ---
function isRealStop(idx, allStops) {
  return idx > 0 && idx < allStops.length - 1;
}

export default function LiveTourScreen() {
  // --- State and Refs ---
  const [tour, setTour] = useState(null);
  const [greeting, setGreeting] = useState(null);
  const [ending, setEnding] = useState(null);

  const [allStops, setAllStops] = useState([]);
  const [activeStop, setActiveStop] = useState(0); // index in allStops
  const [isPlaying, setIsPlaying] = useState(false);
  const [visitedStops, setVisitedStops] = useState([]);
  const [showSettings, setShowSettings] = useState(false);
  const [hasPlayedGreeting, setHasPlayedGreeting] = useState(false);
  const [banner, setBanner] = useState(null);
  const [currentAudio, setCurrentAudio] = useState(null); // "greeting" | "approaching" | "arrived" | "narration" | "ending" | null
  const { audioUnlocked } = useAudioUnlock();

  // --- Refs
  const stopRefs = useRef([]);
  const greetingAudioRef = useRef(null);
  const approachAudioRef = useRef(null);
  const arriveAudioRef = useRef(null);
  const narrationAudioRef = useRef(null);
  const endingAudioRef = useRef(null);

  //--Constants
  const VISITED_THRESHOLD_SECONDS = 60;
  const APPROACH_DISTANCE = 60; // m
  const ARRIVE_DISTANCE = 18;   // m
  const AUDIO_DELAY = 10000;    // ms
  const BANNER_TIMEOUT = 15000; // ms

  // For location tracking
  const [userLocation, setUserLocation] = useState(null);


  // --- 1. Fetch tour/greeting/ending data once ---
  useEffect(() => {
    async function fetchAllTourData() {
      try {
        const [tourRes, greetingRes, endingRes] = await Promise.all([
          fetch("/tours/sf/gold_rush/gold_rush.json"),
          fetch("/tours/sf/gold_rush/greeting.json"),
          fetch("/tours/sf/gold_rush/ending.json"),
        ]);
        const [tourData, greetingData, endingData] = await Promise.all([
          tourRes.json(),
          greetingRes.json(),
          endingRes.json(),
        ]);
        setTour(tourData);
        setGreeting(greetingData);
        setEnding(endingData);
        setAllStops([greetingData, ...(tourData.stops || []), endingData]);
      } catch (err) {
        console.error(err);
      }
    }
    fetchAllTourData();
  }, []);

  // Save/load progress
  useEffect(() => {
    if (!tour || !tour.tour_id) return;
    localStorage.setItem(
      `tourProgress_${tour.tour_id}`,
      JSON.stringify({ activeStop, visitedStops })
    );
  }, [tour, activeStop, visitedStops]);

  useEffect(() => {
    if (!tour || !tour.tour_id) return;
    try {
      const progress = JSON.parse(localStorage.getItem(`tourProgress_${tour.tour_id}`));
      if (progress) {
        setActiveStop(progress.activeStop ?? 0);
        setVisitedStops(progress.visitedStops ?? []);
      }
    } catch (e) {}
  }, [tour]);

  // Watch user location
  useEffect(() => {
    const watchId = navigator.geolocation.watchPosition(
      (pos) => setUserLocation({
        lat: pos.coords.latitude,
        lng: pos.coords.longitude
      }),
      (err) => console.warn("Location error:", err),
      { enableHighAccuracy: true, maximumAge: 10000, timeout: 5000 }
    );
    return () => navigator.geolocation.clearWatch(watchId);
  }, []);

  // --- Play/Pause button logic ---
  const handlePlay = () => {
  if (!isPlaying) {
    if (!currentAudio) {
      if (activeStop === 0) setCurrentAudio("greeting");
      else if (activeStop === allStops.length - 1) setCurrentAudio("ending");
      else setCurrentAudio("narration");
    }
    setIsPlaying(true);
  } else {
    setIsPlaying(false);
  }
};

  // --- Skip logic ---
  const handleSkip = (targetIndex) => {
  if (
    typeof targetIndex === "number" &&
    targetIndex >= 0 &&
    targetIndex < allStops.length
  ) {
    setActiveStop(targetIndex);
    setCurrentAudio(null);   // Let effects decide what to play
    setIsPlaying(false);     // Wait for user action or auto effect
    return;
  }
};

  // --- Greeting ends: always go to first real stop. Proximity logic will decide audio. ---
  const onGreetingEnded = () => {
    setHasPlayedGreeting(true);
    setActiveStop(1); // Move to first real stop after greeting
  };

  // --- Autoplay Logic for ALL stops (greeting, real stops, ending) ---
  useEffect(() => {
  console.log('[AUTOPLAY EFFECT]', {
    activeStop,
    currentAudio,
    isPlaying,
    hasPlayedGreeting,
    visitedStops,
    userLocation
  });

  if (!allStops.length) {
    console.log('[AUTOPLAY] allStops not loaded');
    return;
  }

  // 1. GREETING: Always visible, but do not autoplay. User must tap play.
  if (activeStop === 0) {
    console.log('[AUTOPLAY] On greeting stop');
    if (currentAudio !== "greeting") {
      setCurrentAudio("greeting");
      setIsPlaying(false);
    }
    return;
  }

  // 2. ENDING: Always autoplay when reached.
  if (activeStop === allStops.length - 1) {
    console.log('[AUTOPLAY] On ending stop');
    if (currentAudio !== "ending") {
      setCurrentAudio("ending");
      setIsPlaying(true);
    }
    return;
  }

  // 3. REAL STOPS:
  if (isRealStop(activeStop, allStops)) {
    if (visitedStops.includes(activeStop)) {
      console.log('[AUTOPLAY] Revisited stop');
      if (currentAudio !== "narration") {
        setCurrentAudio("narration");
        setIsPlaying(false); // Do not autoplay on revisited stops unless user taps play
      }
      return;
    }
    const stop = allStops[activeStop];
    if (!stop.lat || !stop.lng) {
      console.log('[AUTOPLAY] Stop has no lat/lng');
      if (currentAudio !== "narration") {
        setCurrentAudio("narration");
        setIsPlaying(true);
      }
      return;
    }
    let dist = null;
    if (userLocation) {
      dist = getDistanceMeters(userLocation.lat, userLocation.lng, stop.lat, stop.lng);
      console.log('[AUTOPLAY] Calculated dist:', dist);
    }
    // If already playing a prompt or narration, don't interrupt.
    if (
      currentAudio === "approaching" ||
      currentAudio === "arrived" ||
      currentAudio === "narration"
    ) {
      console.log('[AUTOPLAY] Already in a prompt/narration:', currentAudio);
      return;
    }

    if (dist !== null) {
      if (dist <= ARRIVE_DISTANCE) {
        console.log('[AUTOPLAY] In ARRIVE range');
        setCurrentAudio("arrived");
        setIsPlaying(true);
        setBanner("You’re here! Ready to hear the story?");
        if (window.navigator.vibrate) window.navigator.vibrate(150);
        setTimeout(() => setBanner(null), BANNER_TIMEOUT);
      } else if (dist <= APPROACH_DISTANCE) {
        console.log('[AUTOPLAY] In APPROACH range');
        setCurrentAudio("approaching");
        setIsPlaying(true);
        setBanner("Almost there! Come a bit closer to hear the story.");
        if (window.navigator.vibrate) window.navigator.vibrate(100);
        setTimeout(() => setBanner(null), BANNER_TIMEOUT);
      } else {
        console.log('[AUTOPLAY] Out of range, default to narration');
        setCurrentAudio("narration");
        setIsPlaying(false);
      }
    } else {
      console.log('[AUTOPLAY] No dist, default to narration');
      setCurrentAudio("narration");
      setIsPlaying(true);
    }
  }
}, [
  activeStop,
  allStops,
  userLocation,
  visitedStops,
  currentAudio,
]);



  // --- Approach prompt ends: go to arrived ---
  useEffect(() => {
    const onApproachEnded = () => {
      setCurrentAudio("arrived");
      setIsPlaying(true);
      setBanner("Almost there! Come a bit closer to hear the story.");
      if (window.navigator.vibrate) window.navigator.vibrate(100);
      setTimeout(() => setBanner(null), BANNER_TIMEOUT);
    };
    const approachAudio = approachAudioRef.current;
    if (approachAudio) approachAudio.addEventListener("ended", onApproachEnded);
    return () => {
      if (approachAudio) approachAudio.removeEventListener("ended", onApproachEnded);
    };
  }, []);

  // --- Arrived prompt ends: go to narration after delay ---
  useEffect(() => {
    const onArrivedEnded = () => {
      setBanner("You’re here! Ready to hear the story?");
      if (window.navigator.vibrate) window.navigator.vibrate(150);
      setTimeout(() => {
        setCurrentAudio("narration");
        setIsPlaying(true);
        setBanner(null);
      }, AUDIO_DELAY);
    };
    const arrivedAudio = arriveAudioRef.current;
    if (arrivedAudio) arrivedAudio.addEventListener("ended", onArrivedEnded);
    return () => {
      if (arrivedAudio) arrivedAudio.removeEventListener("ended", onArrivedEnded);
    };
  }, []);

  // --- Mark stop as visited after narration plays 60s (real stops only) ---
  useEffect(() => {
    if (!isRealStop(activeStop, allStops)) return;
    const audio = narrationAudioRef.current;
    if (!audio) return;
    function handleTimeUpdate() {
      if (
        !visitedStops.includes(activeStop) &&
        audio.currentTime >= VISITED_THRESHOLD_SECONDS
      ) {
        setVisitedStops(prev =>
          prev.includes(activeStop) ? prev : [...prev, activeStop]
        );
      }
    }
    audio.addEventListener("timeupdate", handleTimeUpdate);
    return () => {
      audio.removeEventListener("timeupdate", handleTimeUpdate);
    };
    // eslint-disable-next-line
  }, [activeStop, visitedStops, allStops]);

  // --- Only one audio element plays at a time (untouched) ---
  useEffect(() => {
    const refs = {
      greeting: greetingAudioRef,
      approaching: approachAudioRef,
      arrived: arriveAudioRef,
      narration: narrationAudioRef,
      ending: endingAudioRef,
    };
    Object.entries(refs).forEach(([state, ref]) => {
      if (ref.current) {
        if (currentAudio === state && isPlaying) ref.current.play();
        else {
          ref.current.pause();
        }
      }
    });
  }, [currentAudio, isPlaying]);

  //Arrived Prompt Handler (always triggers narration after prompt finishes)
  const onArrivedEnded = () => {
  setBanner("You’re here! Ready to hear the story?");
  if (window.navigator.vibrate) window.navigator.vibrate(150); // Haptic
  setTimeout(() => {
    setCurrentAudio("narration");
    setIsPlaying(true);
    setBanner(null);
  }, AUDIO_DELAY);
};

   // --- When user switches stops, reset all audio state ---
useEffect(() => {
  setIsPlaying(false);
  setCurrentAudio(null); // <------ THIS is the key!
  if (narrationAudioRef.current) {
    narrationAudioRef.current.currentTime = 0;
  }
  if (greetingAudioRef.current) {
    greetingAudioRef.current.currentTime = 0;
  }
  if (endingAudioRef.current) {
    endingAudioRef.current.currentTime = 0;
  }
}, [activeStop]);


  // --- Scroll to active stop (UI) ---
  useEffect(() => {
    if (allStops.length && stopRefs.current[activeStop]) {
      stopRefs.current[activeStop].scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [activeStop, allStops]);

  // --- Debug location ---
  useEffect(() => {
    if (userLocation) {
      console.log("User location:", userLocation);
    }
  }, [userLocation]);

  if (!tour || !greeting || !ending) return <div>Loading…</div>;

  return (
    <div style={{
      width: "100vw",
      height: "100vh",
      display: "flex",
      flexDirection: "column",
      background: "#fff",
      fontFamily: "sans-serif",
      alignItems: "center",
    }}>
      {/* Banner */}
      {banner && (
        <div style={{
          position: "fixed",
          top: 80,
          left: 0,
          right: 0,
          zIndex: 100,
          textAlign: "center",
          background: "#fdf6b2",
          color: "#444",
          padding: 10
        }}>
          {banner}
        </div>
      )}

      {/* Title and settings */}
      <div style={{
        width: "100%",
        maxWidth: 393,
        margin: "0 auto",
        padding: "24px 0 8px 0",
        display: "flex",
        flexDirection: "row",
        alignItems: "center",
        justifyContent: "space-between",
      }}>
        <span style={{
          fontSize: 24,
          fontWeight: 600,
          letterSpacing: 0.5,
          color: "#222",
          fontFamily: "inherit",
        }}>
          {tour.title || "Tour Title"}
        </span>
        <button
          onClick={() => setShowSettings(s => !s)}
          aria-label="Settings"
        >
          <MdSettings size={24} color="#000000" />
        </button>
      </div>

      {/* Main content area */}
      <div style={{
        width: "100%",
        maxWidth: 393,
        display: "flex",
        flexGrow: 1,
        flexDirection: "column",
        margin: "0 auto",
        minHeight: 0,
      }}>
        
        {/* Audio elements - always rendered for preloading/progress bar */}
        <audio
          ref={greetingAudioRef}
          src={greeting.audio}
          preload="auto"
          onEnded={onGreetingEnded}
          style={{ display: "none" }}
        />
        <audio
          ref={approachAudioRef}
          src="/audio/approach_prompt.mp3"
          preload="auto"
          style={{ display: "none" }}
        />
        <audio
          ref={arriveAudioRef}
          src="/audio/arrive_prompt.mp3"
          preload="auto"
          onEnded={onArrivedEnded}
          style={{ display: "none" }}
        />
        <audio
          ref={narrationAudioRef}
          src={isRealStop(activeStop, allStops) ? (allStops[activeStop]?.narration_audio || allStops[activeStop]?.audio) : null}
          preload="auto"
          onEnded={() => setIsPlaying(false)}
          style={{ display: "none" }}
        />
        <audio
          ref={endingAudioRef}
          src={ending.audio}
          preload="auto"
          onEnded={() => setIsPlaying(false)}
          style={{ display: "none" }}
        />
        
        {/* Map */}
        <div style={{
          width: "100%",
          height: 260,
          borderRadius: 16,
          overflow: "hidden",
          marginTop: 16,
        }}>
          <MapPreview
            stops={tour.stops}
            userLocation={userLocation}
            activeStop={
              isRealStop(activeStop, allStops)
                ? activeStop - 1 // match to index in real stops
                : null
            }
            visitedStops={visitedStops.map(i => i - 1).filter(i => i >= 0)}
            enableUserMarker={true}
          />
        </div>

        {/* Stops List */}
        <div style={{
          margin: "16px 0 8px 0",
          display: "flex",
          flex: 1,
          flexDirection: "column",
          gap: 10,
          overflowY: "auto",
          width: "100%",
          boxSizing: "border-box",
        }}>
          {allStops.map((stop, i) => (
            <div
              key={i}
              ref={el => stopRefs.current[i] = el}
              style={{
                padding: 16,
                borderRadius: 10,
                background: i === activeStop ? "#e8e7ff" : "#f6f6f6",
                border: i === activeStop ? "2.5px solid #e8e7ff" : "1px solid #e5e5e5",
                fontWeight: 600,
                cursor: "pointer",
                transition: "all 0.2s"
              }}
              onClick={() => setActiveStop(i)}
            >
              <div>
                {(i === 0 || i === allStops.length - 1)
                  ? stop.title // Greeting/ending: show title, no number
                  : `${i}. ${stop.name}`} {/* Real stops: number and name */}
              </div>
              {activeStop === i && (
                <div style={{ fontSize: 14, fontWeight: 400 }}>
                  {stop.narration_text || stop.body || "No narration yet."}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Settings modal (untouched) */}
      {showSettings && (
        <div
          style={{
            position: "fixed",
            top: 0, left: 0, right: 0, bottom: 0,
            background: "rgba(0,0,0,0.25)",
            zIndex: 5000,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
          onClick={() => setShowSettings(false)}
        >
          <div
            style={{
              background: "#fff",
              borderRadius: 16,
              boxShadow: "0 6px 36px #0002",
              padding: 32,
              minWidth: 260,
              minHeight: 120,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: 24,
              position: "relative",
            }}
            onClick={e => e.stopPropagation()}
          >
            <div style={{ fontWeight: 600, fontSize: 18, marginBottom: 8 }}>
              Tour Settings
            </div>
            <button
              style={{
                background: "#f6f6f6",
                color: "#8C8CFF",
                border: "none",
                borderRadius: 8,
                fontWeight: 600,
                fontSize: 16,
                padding: "12px 28px",
                cursor: "pointer",
              }}
              onClick={() => {
                setVisitedStops([]);
                setActiveStop(0);
                localStorage.removeItem(`tourProgress_${tour.tour_id}`);
                setShowSettings(false);
              }}
            >
              Restart Tour
            </button>
            <button
              style={{
                background: "#fff",
                color: "#666",
                border: "1px solid #e5e5e5",
                borderRadius: 8,
                fontWeight: 400,
                fontSize: 14,
                padding: "8px 20px",
                marginTop: 8,
                cursor: "pointer",
              }}
              onClick={() => setShowSettings(false)}
            >
              Close
            </button>
          </div>
        </div>
      )}

      {/* Audio Controls */}
      <div style={{
        position: "fixed",
        bottom: 0,
        zIndex: 10,
        background: "#333",
        color: "#fff",
        borderRadius: "16px",
        width: "100%",
        maxWidth: 393,
        padding: 16,
        display: "flex",
        flexDirection: "column",
        gap: 16,
        alignItems: "center",
        justifyContent: "center",
      }}>
        {/* Progress bar: always visible */}
        <NarrationProgressBar
          audioRef={
            activeStop === 0
              ? greetingAudioRef
              : activeStop === allStops.length - 1
              ? endingAudioRef
              : narrationAudioRef
          }
          isPlaying={isPlaying}
          key={activeStop}
          current={activeStop + 1}
          total={allStops.length}
        />

        <div style={{
          width: 324,
          height: 56,
          display: "flex",
          flexDirection: "row",
          justifyContent: "space-between",
          alignItems: "center",
          margin: "0 auto",
        }}>
          {/* Skip Previous */}
          <button
            style={{
              width: 24,
              height: 24,
              background: "none",
              border: "none",
              padding: 0,
              cursor: "pointer",
            }}
            onClick={() => handleSkip(Math.max(activeStop - 1, 0))}
            aria-label="Skip to previous stop"
          >
            <img src="/icons/skip-back.svg" alt="Skip back" style={{ width: 24, height: 24 }} />
          </button>
          {/* Fast Rewind */}
          <button
            style={{
              width: 24,
              height: 24,
              background: "none",
              border: "none",
              padding: 0,
              cursor: "pointer",
            }}
            onClick={() => {/* your fast-rewind handler */}}
            aria-label="Rewind 10 seconds"
          >
            <img src="/icons/rewind.svg" alt="Rewind 10 seconds" style={{ width: 24, height: 24 }} />
          </button>
          {/* Play/Pause */}
          <button
            style={{
              width: 56,
              height: 56,
              borderRadius: "50%",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
            onClick={handlePlay}
          >
            {isPlaying ? (
              <MdPause color="#333333" />
            ) : (
              <MdPlayArrow color="#333333" />
            )}
          </button>
          {/* Fast Forward */}
          <button
            style={{
              width: 24,
              height: 24,
              background: "none",
              border: "none",
              padding: 0,
              cursor: "pointer",
            }}
            onClick={handleSkip}
            aria-label="Forward 10 seconds"
          >
            <img src="/icons/forward.svg" alt="Forward 10 seconds" style={{ width: 24, height: 24 }} />
          </button>
          {/* Skip Next */}
          <button
            style={{
              width: 24,
              height: 24,
              background: "none",
              border: "none",
              padding: 0,
              cursor: "pointer",
            }}
            onClick={() => handleSkip(Math.min(activeStop + 1, allStops.length - 1))}
            aria-label="Skip to next stop"
          >
            <img src="/icons/skip-forward.svg" alt="Skip next" style={{ width: 24, height: 24 }} />
          </button>
        </div>
      </div>
    </div>
  );
}

