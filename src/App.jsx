import React, { useState } from 'react';
import { BrowserRouter as Router, Routes, Route } from "react-router-dom";
import CreateTourForm from './components/CreateTourForm';
import TourCard from './components/TourCard';
import TourViewScreen from "./components/TourViewScreen";
import LiveTourScreen from "./components/LiveTourScreen";
import { AudioUnlockProvider } from "./AudioUnlockContext";


const styles = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    height: '100vh',
    width: '100vw',
    gap: 16,
  },
  heading: {
    fontSize: 16,
    marginBottom: 12,
  },
  button: {
    padding: '12px 24px',
    fontSize: 18,
    backgroundColor: '#0070f3',
    color: 'white',
    border: 'none',
    borderRadius: 8,
    cursor: 'pointer',
  },
};

export default function App() {
  const [showForm, setShowForm] = useState(false);

  const handleCreateTour = () => setShowForm(true);

  if (showForm) {
    return <CreateTourForm />;
  }

  return (
    <AudioUnlockProvider>
    <Router>
      <Routes>
        <Route
          path="/"
          element={
            <main style={styles.container}>
              <h2 style={styles.title}>1 Tour in San Francisco</h2>
              <TourCard />
              <h2 style={styles.heading}>Didn’t find what you’re looking for?</h2>
              <button style={styles.button} onClick={handleCreateTour}>
                Create Your Own Tour
              </button>
            </main>
          }
        />
        <Route path="/tour" element={<TourViewScreen />} />
        <Route path="/live" element={<LiveTourScreen />} />
      </Routes>
    </Router>
    </AudioUnlockProvider>
  );
}
