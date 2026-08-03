import React from 'react';

export function StatusBadge({ status }) {
  const getStatusStyles = (s) => {
    switch (s) {
      case 'detected':
        return { color: 'var(--accent-red)', bg: 'var(--accent-red-bg)', text: 'Detected' };
      case 'acknowledged':
        return { color: 'var(--accent-amber)', bg: 'var(--accent-amber-bg)', text: 'Acknowledged' };
      case 'crew_assigned':
        return { color: 'var(--accent-blue)', bg: 'var(--accent-blue-bg)', text: 'Crew Assigned' };
      case 'resolved':
      case 'verified':
        return { color: 'var(--accent-green)', bg: 'var(--accent-green-bg)', text: s === 'verified' ? 'Verified' : 'Resolved' };
      case 'closed':
        return { color: 'var(--text-muted)', bg: 'rgba(255,255,255,0.1)', text: 'Closed' };
      default:
        return { color: '#fff', bg: '#333', text: s };
    }
  };

  const styles = getStatusStyles(status);

  return (
    <span style={{
      backgroundColor: styles.bg,
      color: styles.color,
      padding: '4px 8px',
      borderRadius: '9999px',
      fontSize: '11px',
      fontWeight: '600',
      textTransform: 'uppercase',
      display: 'inline-block'
    }}>
      {styles.text}
    </span>
  );
}
