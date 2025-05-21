import React from 'react';

export default function Chip({ label, selected, onClick }) {
  return (
    <div
      onClick={onClick}
      style={{
        ...styles.chip,
        backgroundColor: selected ? '#4CAF50' : '#e0e0e0',
        color: selected ? 'white' : 'black',
        display: 'inline-block', // Ensures chip is inline and adjusts to content
        padding: '8px 16px',
        borderRadius: '16px',
        cursor: 'pointer',
      }}
    >
      {label}
    </div>
  );
}

const styles = {
  chip: {
    fontSize: '14px',
    fontWeight: '500',
    textAlign: 'center',
    whiteSpace: 'nowrap', // Prevent the label from wrapping to a new line
  },
};
