import React, { createContext, useContext, useState } from "react";

// Create context
const AudioUnlockContext = createContext();

// Custom hook for easy access
export function useAudioUnlock() {
  return useContext(AudioUnlockContext);
}

// Provider component
export function AudioUnlockProvider({ children }) {
  const [audioUnlocked, setAudioUnlocked] = useState(false);

  return (
    <AudioUnlockContext.Provider value={{ audioUnlocked, setAudioUnlocked }}>
      {children}
    </AudioUnlockContext.Provider>
  );
}
