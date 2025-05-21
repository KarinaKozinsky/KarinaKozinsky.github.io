import React, { useState } from 'react';

export default function AccordionCard({ title, children, isOpenByDefault, summaryComponent }) {
  const [isOpen, setIsOpen] = useState(isOpenByDefault);

  return (
    <div style={styles.card}>
      <div style={styles.header} onClick={() => setIsOpen(!isOpen)}>
        <div style={styles.headerLeft}>
          <h3 style={styles.title}>{title}</h3>
          {!isOpen && summaryComponent && (
            <div style={styles.chipWrapper}>{summaryComponent}</div>
          )}
        </div>
        <span style={styles.toggle}>{isOpen ? '−' : '+'}</span>
      </div>

      <div
        style={{
          ...styles.contentWrapper,
          height: isOpen ? 'auto' : 0,
          overflow: 'hidden',
          transition: 'height 0.3s ease',
        }}
      >
        <div style={{ ...styles.content, opacity: isOpen ? 1 : 0, transition: 'opacity 0.3s ease' }}>
          {children}
        </div>
      </div>
    </div>
  );
}

const styles = {
  card: {
    width: '100%',
    maxWidth: 600,
    border: '1px solid #ccc',
    borderRadius: 8,
    marginBottom: 12,
    boxSizing: 'border-box',
  },
  header: {
    padding: '12px 16px',
    backgroundColor: '#f5f5f5',
    cursor: 'pointer',
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
  },
  headerLeft: {
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
  },
  title: {
    margin: 0,
    fontSize: 16,
  },
  chipWrapper: {
    marginTop: 4,
  },
  toggle: {
    fontSize: 24,
    lineHeight: 1,
  },
  contentWrapper: {
    width: '100%',
  },
  content: {
    padding: 16,
    backgroundColor: 'white',
  },
};
