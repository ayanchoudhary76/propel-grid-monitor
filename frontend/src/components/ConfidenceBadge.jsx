import React from 'react';
import { CheckCircle2, AlertTriangle } from 'lucide-react';

export function ConfidenceBadge({ source }) {
  const isKnown = source === 'known';
  
  return (
    <div 
      title={isKnown ? "Topology exactly maps the database." : "Topology was inferred geometrically and may have minor inaccuracies."}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '4px',
        padding: '4px 8px',
        borderRadius: '6px',
        fontSize: '11px',
        fontWeight: '500',
        backgroundColor: isKnown ? 'var(--accent-green-bg)' : 'var(--accent-amber-bg)',
        color: isKnown ? 'var(--accent-green)' : 'var(--accent-amber)',
        border: `1px solid ${isKnown ? 'var(--accent-green)' : 'var(--accent-amber)'}40`
      }}
    >
      {isKnown ? <CheckCircle2 size={12} /> : <AlertTriangle size={12} />}
      {isKnown ? 'Known Topology' : 'Inferred Topology'}
    </div>
  );
}
