import React, { useState } from 'react';
import AccordionCard from './AccordionCard';
import Chip from './Chip';

export default function CreateTourForm() {
  const [selectedCity, setSelectedCity] = useState('San Francisco');
  const [selectedThemes, setSelectedThemes] = useState(['🎲 Surprise Me']);
  const [customThemeActive, setCustomThemeActive] = useState(false);
  const [customThemeText, setCustomThemeText] = useState('');
  const [selectedDuration, setSelectedDuration] = useState(150); // Set a default duration (2.5 hrs)
  
  const handleClearForm = () => {
    setSelectedCity('San Francisco');
    setSelectedThemes(['🎲 Surprise Me']);
    setCustomThemeActive(false);
    setCustomThemeText('');
    setSelectedDuration(150);
  };


  const themes = [
    '🎲 Surprise Me',
    '🌉 Golden Gate & Views',
    '🍽️ Foodie Favorites',
    '🏛️ Gold Rush History',
    '🎨 Arts & Murals',
    '🌲 Urban Nature',
    '🖊️ In Your Own Words',
  ];

  const handleCityClick = (city) => {
    setSelectedCity(city);
  };

  const handleSliderChange = (e) => {
    setSelectedDuration(Number(e.target.value));
  };

  const handleThemeToggle = (theme) => {
    if (theme === '🖊️ In Your Own Words') {
      setCustomThemeActive(true);
      return;
    }

    if (selectedThemes.includes(theme)) {
      setSelectedThemes(selectedThemes.filter((t) => t !== theme));
    } else {
      if (theme === '🎲 Surprise Me') {
        setSelectedThemes(['🎲 Surprise Me']);
      } else {
        setSelectedThemes([
          ...selectedThemes.filter((t) => t !== '🎲 Surprise Me'),
          theme,
        ]);
      }
    }

    // If toggling off custom input, also clear it
    setCustomThemeActive(false);
    setCustomThemeText('');
  };
  const handleCreatePreview = async () => {
    const payload = {
      city: selectedCity,
      themes: customThemeActive && customThemeText
        ? [customThemeText]
        : selectedThemes,
      duration: selectedDuration,
    };
  
    console.log('Sending this to API:', payload);
  
    try {
      // Make the API call to your endpoint (update the URL as needed)
      const response = await fetch('http://localhost:5000/generate-tour', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      });
  
      // Check if the response is ok (status code 200-299)
      if (!response.ok) {
        throw new Error('Failed to generate tour');
      }
  
      const result = await response.json();
      console.log('API returned:', result);
  
      // For now, simulate a success toast
      alert('✅ Tour preview created!');
      // Later: Navigate to the preview screen and pass result
    } catch (error) {
      console.error('API error:', error);
      alert('❌ Failed to create tour preview.');
    }
  };
  
  
  return (
    <div style={styles.layout}>
      <h2 style={styles.heading}>Create Your Tour</h2>

      <div style={styles.cardWrapper}>
        {/* City selection */}
        <AccordionCard
          title="Where are you going?"
          isOpenByDefault={true}
          summaryComponent={
            <Chip
              label={selectedCity}
              selected={true}
              onClick={() => handleCityClick(selectedCity)}
            />
          }
        >
          <div style={styles.searchContainer}>
            <input
              type="text"
              placeholder="Search for destination"
              style={styles.searchInput}
            />
          </div>

          <div style={styles.chipContainer}>
            {['San Francisco', 'New York', 'Los Angeles'].map((city) => (
              <Chip
                key={city}
                label={city}
                selected={selectedCity === city}
                onClick={() => handleCityClick(city)}
              />
            ))}
          </div>
        </AccordionCard>

        {/* Theme selection */}
        <AccordionCard
          title="What do you want to explore?"
          isOpenByDefault={false}
          summaryComponent={
            <div style={styles.summaryWrapper}>
              {selectedThemes.length === 0 && !customThemeText && (
                <Chip label="🎲 Surprise Me" selected={true} />
              )}

              {selectedThemes
                .filter((theme) => theme !== '🖊️ In Your Own Words')
                .map((theme) => (
                  <Chip
                    key={theme}
                    label={theme}
                    selected={true}
                    onClick={() => handleThemeToggle(theme)}
                  />
                ))}

              {customThemeActive && customThemeText && (
                <Chip
                  label={
                    customThemeText.length > 30
                      ? customThemeText.slice(0, 30) + '…'
                      : customThemeText
                  }
                  selected={true}
                  onClick={() => {
                    setCustomThemeActive(false);
                    setCustomThemeText('');
                  }}
                />
              )}
            </div>
          }
        >
          <div style={styles.chipContainer}>
            {themes.map((theme) => (
              <Chip
                key={theme}
                label={theme}
                selected={selectedThemes.includes(theme)}
                onClick={() => handleThemeToggle(theme)}
              />
            ))}
          </div>

          {customThemeActive && (
            <div style={{ ...styles.inputWrapper, marginTop: 12 }}>
              <input
                type="text"
                maxLength={200}
                placeholder="e.g. quirky shops and hidden murals"
                value={customThemeText}
                onChange={(e) => setCustomThemeText(e.target.value)}
                style={{
                  width: '100%',
                  padding: '10px 16px',
                  fontSize: 16,
                  borderRadius: 8,
                  border: '1px solid #ccc',
                  minHeight: 48,
                  boxSizing: 'border-box',
                }}
              />
              <p style={{ marginTop: 6, fontSize: 13, color: '#888' }}>
                Max 200 characters (~30 words)
              </p>
            </div>
          )}
        </AccordionCard>
        {/* Time selection */}
        <AccordionCard
  title="How much time do you have?"
  isOpenByDefault={false}
  summaryComponent={
    <Chip
      label={
        selectedDuration
          ? `${Math.floor(selectedDuration / 60)}h${selectedDuration % 60 ? ` ${selectedDuration % 60}m` : ''}`
          : 'No time constraints'
      }
      selected={true}
      onClick={() => setSelectedDuration(150)} // Reset to default (2.5 hours)
    />
  }
>
  <div style={{ paddingTop: 12 }}>
    <input
      type="range"
      min={30}
      max={300}
      step={30}
      value={selectedDuration}
      onChange={handleSliderChange}
      style={{ width: '100%' }}
    />
    <div style={{ marginTop: 12, fontSize: 14, color: '#555' }}>
      {selectedDuration ? (
        <>
          The tour is designed to take about ~
          {Math.floor(selectedDuration / 60)}h
          {selectedDuration % 60 ? ` ${selectedDuration % 60}m` : ''}.
          {' '}But feel free to take your time — pause, explore, and resume whenever you want.
        </>
      ) : (
        'Default tour duration is ~2–3 hours.'
      )}
    </div>
  </div>
        </AccordionCard>
      </div>
            {/* Buttons */}
            <div style={styles.buttonContainer}>
            <button style={styles.primaryButton} onClick={handleCreatePreview}>
          Create Preview
        </button>
        <button style={styles.secondaryButton} onClick={handleClearForm}>
          Clear
        </button>
      </div>

    </div>
  );
}

const styles = {
  layout: {
    padding: 24,
    width: '100%',
    maxWidth: 600,
    margin: '0 auto',
    fontFamily: 'sans-serif',
  },
  heading: {
    fontSize: 24,
    marginBottom: 24,
  },
  cardWrapper: {
    width: '100%',
    maxWidth: 600,
    margin: '0 auto',
  },
  searchContainer: {
    marginBottom: 16,
  },
  searchInput: {
    width: '100%',
    padding: '10px 16px',
    fontSize: 16,
    borderRadius: 8,
    border: '1px solid #ccc',
    boxSizing: 'border-box',
  },
  chipContainer: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: 8,
  },
  inputWrapper: {
    marginTop: 16,
    width: '100%',
  },
  summaryWrapper: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: 8,
  },
  buttonContainer: {
    display: 'flex',
    justifyContent: 'flex-end',
    gap: 12,
    marginTop: 32,
  },
  primaryButton: {
    backgroundColor: '#111',
    color: '#fff',
    padding: '10px 20px',
    border: 'none',
    borderRadius: 8,
    fontSize: 16,
    cursor: 'pointer',
  },
  secondaryButton: {
    backgroundColor: '#eee',
    color: '#333',
    padding: '10px 20px',
    border: '1px solid #ccc',
    borderRadius: 8,
    fontSize: 16,
    cursor: 'pointer',
  },

};
