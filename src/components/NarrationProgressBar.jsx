import React, { useEffect, useState, useRef } from "react";

// Props: audioRef (ref to <audio>), isPlaying (for re-render)
export function NarrationProgressBar({ audioRef, isPlaying }) {
  const [progress, setProgress] = useState(0); // 0..1
  const [duration, setDuration] = useState(0);
  const [current, setCurrent] = useState(0);
  const barRef = useRef();

  // Update on audio changes
  useEffect(() => {
    if (!audioRef || !audioRef.current) return;
    const audio = audioRef.current;

    function update() {
      setCurrent(audio.currentTime);
      setDuration(audio.duration || 0);
      setProgress(audio.duration ? audio.currentTime / audio.duration : 0);
    }
    audio.addEventListener("timeupdate", update);
    audio.addEventListener("loadedmetadata", update);
    return () => {
      audio.removeEventListener("timeupdate", update);
      audio.removeEventListener("loadedmetadata", update);
    };
  }, [audioRef, isPlaying]);

  // Seek by clicking bar or dragging thumb
  const handleSeek = (e) => {
    if (!audioRef || !audioRef.current || !duration) return;
    const rect = barRef.current.getBoundingClientRect();
    let x = e.type === "touchstart"
      ? e.touches[0].clientX - rect.left
      : e.clientX - rect.left;
    let percent = Math.max(0, Math.min(1, x / rect.width));
    audioRef.current.currentTime = percent * duration;
  };

  // Tap on start time to reset
  const handleReset = () => {
    if (!audioRef || !audioRef.current) return;
    audioRef.current.currentTime = 0;
  };

  // Drag (mobile/desktop)
  const handleThumbDrag = (e) => {
    if (!audioRef || !audioRef.current || !duration) return;
    e.preventDefault();
    document.body.style.userSelect = "none";
    const moveHandler = (moveEvent) => {
      const rect = barRef.current.getBoundingClientRect();
      let x =
        moveEvent.type === "touchmove"
          ? moveEvent.touches[0].clientX - rect.left
          : moveEvent.clientX - rect.left;
      let percent = Math.max(0, Math.min(1, x / rect.width));
      if (audioRef.current && duration) {
        audioRef.current.currentTime = percent * duration;
      }
    };
    const upHandler = () => {
      document.removeEventListener("mousemove", moveHandler);
      document.removeEventListener("touchmove", moveHandler);
      document.removeEventListener("mouseup", upHandler);
      document.removeEventListener("touchend", upHandler);
      document.body.style.userSelect = "";
    };
    document.addEventListener("mousemove", moveHandler);
    document.addEventListener("touchmove", moveHandler);
    document.addEventListener("mouseup", upHandler);
    document.addEventListener("touchend", upHandler);
  };

  // After all hooks, check if audioRef is missing
  const disabled = !audioRef || !audioRef.current;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "row",
        alignItems: "center",
        justifyContent: "center", 
        padding: 0,
        gap: 12,
        position: "relative",
        width: 324,
        height: 24,
        margin: "0 auto",
        opacity: disabled ? 0.5 : 1,   // visually disable
        pointerEvents: disabled ? "none" : "auto" // don't allow scrub
      }}
    >
      {/* Start Time */}
      <span
        style={{
          height: 18,
          fontFamily: "Mulish, sans-serif",
          fontWeight: 400,
          fontSize: 16,
          color: "#BEBEBE",
          lineHeight: "18px",
          cursor: disabled ? "default" : "pointer"
        }}
        onClick={disabled ? undefined : handleReset}
      >
        {formatTime(disabled ? 0 : current)}
      </span>
      {/* Bar */}
      <div
        ref={barRef}
        style={{
          flex: 1,
          height: 8,
          position: "relative",
          justifyContent: "center",
          background: "none",
          cursor: disabled ? "default" : "pointer"
        }}
        onClick={disabled ? undefined : handleSeek}
        onTouchStart={disabled ? undefined : handleSeek}
      >
        {/* Placeholder bar */}
        <div
          style={{
            position: "absolute",
            width: "100%",
            height: 0,
            border: "1px solid rgba(120, 120, 120, 0.6)",
            borderRadius: 3,
            top: "50%",
            left: 0,
            transform: "translateY(-50%)",
            zIndex: 0,
          }}
        />
        {/* Progress line */}
        <div
          style={{
            position: "absolute",
            width: `${(disabled ? 0 : progress) * 100}%`,
            height: 0,
            border: "3px solid #8C8CFF",
            borderRadius: 3,
            top: "50%",
            left: 0,
            transform: "translateY(-50%)",
            zIndex: 1,
          }}
        />
        {/* Blue Thumb */}
        <div
          style={{
            position: "absolute",
            left: `calc(${(disabled ? 0 : progress) * 100}% + 3px)`,
            top: "50%",
            width: 12,
            height: 12,
            background: "#8C8CFF",
            borderRadius: "50%",
            boxShadow: "0 0 4px #8C8CFF80",
            zIndex: 2,
            transform: "translate(-50%, -50%)", // Center thumb
            cursor: disabled ? "default" : "grab"
          }}
          onMouseDown={disabled ? undefined : handleThumbDrag}
          onTouchStart={disabled ? undefined : handleThumbDrag}
        />
      </div>
      {/* End Time */}
      <span
        style={{
          height: 18,
          fontFamily: "Mulish, sans-serif",
          fontWeight: 400,
          fontSize: 16,
          color: "#BEBEBE",
          lineHeight: "18px"
        }}
      >
        {formatTime(disabled ? 0 : duration)}
      </span>
    </div>
  );
}

function formatTime(seconds) {
  if (!isFinite(seconds)) return "0:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}
