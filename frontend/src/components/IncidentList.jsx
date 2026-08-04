import React, { useEffect, useState } from 'react';
import { Zap, Plug, ZapOff, CheckCircle2 } from 'lucide-react';
import { formatDistanceToNow } from 'date-fns';
import { usePolling } from '../hooks/usePolling';
import { api } from '../api';
import { StatusBadge } from './StatusBadge';
import { ConfidenceBadge } from './ConfidenceBadge';

export function IncidentList({ selectedTicketId, onSelectTicket }) {
  const { data: tickets, error: ticketsError } = usePolling(api.getActiveTickets, 5000);
  const { data: outages, error: outagesError } = usePolling(api.getActiveOutages, 30000);
  const [prevCount, setPrevCount] = useState(0);
  const [pulse, setPulse] = useState(false);

  const activeTickets = tickets || [];
  const activeOutages = outages || [];

  // Sort: detected first, then newest first
  const sortedTickets = [...activeTickets].sort((a, b) => {
    if (a.status === 'detected' && b.status !== 'detected') return -1;
    if (a.status !== 'detected' && b.status === 'detected') return 1;
    return new Date(b.detected_at) - new Date(a.detected_at);
  });

  useEffect(() => {
    if (activeTickets.length > prevCount) {
      setPulse(true);
      const t = setTimeout(() => setPulse(false), 2000);
      return () => clearTimeout(t);
    }
    setPrevCount(activeTickets.length);
  }, [activeTickets.length, prevCount]);

  const getIcon = (type) => {
    if (type === 'span') return <Zap size={16} color="var(--accent-red)" />;
    if (type === 'dt') return <Plug size={16} color="var(--accent-red)" />;
    if (type === 'feeder') return <ZapOff size={16} color="var(--accent-red)" />;
    return <Zap size={16} color="var(--accent-red)" />;
  };

  return (
    <div style={{
      gridArea: 'sidebar',
      borderRight: '1px solid var(--border-color)',
      backgroundColor: 'rgba(10, 10, 15, 0.8)',
      backdropFilter: 'blur(10px)',
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden'
    }}>
      <div style={{ padding: '16px', borderBottom: '1px solid var(--border-color)' }}>
        <h2 style={{ fontSize: '14px', fontWeight: '600', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
          Active Incidents
        </h2>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '12px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
        {sortedTickets.length === 0 && (
          <div style={{ 
            display: 'flex', flexDirection: 'column', alignItems: 'center', 
            justifyContent: 'center', padding: '40px 20px', textAlign: 'center',
            color: 'var(--text-muted)'
          }}>
            <CheckCircle2 size={48} color="var(--accent-green)" style={{ marginBottom: '16px', opacity: 0.5 }} />
            <p style={{ fontSize: '14px', fontWeight: '500' }}>No active incidents</p>
            <p style={{ fontSize: '12px', marginTop: '4px' }}>All monitored grid assets are responsive.</p>
          </div>
        )}

        {sortedTickets.map(ticket => {
          const isSelected = ticket.id === selectedTicketId;
          const isNew = pulse && ticket.status === 'detected';
          
          return (
            <div 
              key={ticket.id}
              onClick={() => onSelectTicket(ticket.id)}
              className={isNew ? 'pulse-border-red' : ''}
              style={{
                backgroundColor: isSelected ? 'var(--bg-card-hover)' : 'var(--bg-card)',
                border: `1px solid ${isSelected ? 'var(--accent-blue)' : 'var(--border-color)'}`,
                borderRadius: '8px',
                padding: '12px',
                cursor: 'pointer',
                transition: 'all 0.2s ease',
                boxShadow: isSelected ? '0 0 0 1px var(--accent-blue)' : 'none'
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '8px' }}>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <div style={{ 
                    padding: '6px', borderRadius: '6px', 
                    backgroundColor: 'var(--accent-red-bg)' 
                  }}>
                    {getIcon(ticket.fault_type)}
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column' }}>
                    <span style={{ fontSize: '13px', fontWeight: '600' }}>
                      {ticket.fault_type.toUpperCase()} FAULT
                    </span>
                    <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                      {formatDistanceToNow(new Date(ticket.detected_at), { addSuffix: true })}
                    </span>
                  </div>
                </div>
                <StatusBadge status={ticket.status} />
              </div>
              
              <div style={{ fontSize: '13px', color: 'var(--text-secondary)', marginBottom: '8px', lineHeight: '1.4' }}>
                {(ticket.fault_location_description || '').length > 60 
                  ? (ticket.fault_location_description || '').substring(0, 60) + '...' 
                  : ticket.fault_location_description}
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                  {ticket.affected_poles_count} poles affected
                </span>
                <ConfidenceBadge source={ticket.topology_source} />
              </div>
            </div>
          );
        })}
      </div>

      {activeOutages.length > 0 && (
        <div style={{ 
          borderTop: '1px solid var(--border-color)', 
          padding: '16px',
          backgroundColor: 'var(--bg-card)'
        }}>
          <h3 style={{ fontSize: '12px', fontWeight: '600', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '12px' }}>
            Scheduled Outages
          </h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {activeOutages.map(outage => (
              <div key={outage.outage_id} style={{ 
                fontSize: '12px', padding: '8px', 
                backgroundColor: 'rgba(255,255,255,0.03)', 
                borderRadius: '6px', border: '1px solid var(--border-color)'
              }}>
                <div style={{ fontWeight: '500', color: 'var(--text-primary)' }}>{outage.reason}</div>
                <div style={{ color: 'var(--text-secondary)', marginTop: '4px' }}>
                  {outage.scope}: {outage.target_id}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
