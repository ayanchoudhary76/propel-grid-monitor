import React, { useState, useEffect } from 'react';
import { X, MapPin, Hash, CheckCircle2, User, Wrench, AlertTriangle, Loader2 } from 'lucide-react';
import { format } from 'date-fns';
import { api } from '../api';
import { StatusBadge } from './StatusBadge';
import { ConfidenceBadge } from './ConfidenceBadge';

export function TicketDetail({ ticketId, onClose, onActionComplete }) {
  const [ticket, setTicket] = useState(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [error, setError] = useState(null);

  const fetchTicket = async () => {
    try {
      const data = await api.getTicket(ticketId);
      setTicket(data);
      setError(null);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (ticketId) {
      setLoading(true);
      fetchTicket();
      // Poll every 5s to stay in sync with left panel
      const interval = setInterval(fetchTicket, 5000);
      return () => clearInterval(interval);
    }
  }, [ticketId]);

  const handleAction = async (action) => {
    setActionLoading(true);
    setError(null);
    try {
      if (action === 'acknowledge') await api.acknowledgeTicket(ticketId);
      if (action === 'assign_crew') await api.assignCrew(ticketId);
      if (action === 'resolve') await api.resolveTicket(ticketId);
      
      await fetchTicket();
      if (onActionComplete) onActionComplete();
    } catch (err) {
      setError(err.message || 'Action failed');
      // Briefly show error
      setTimeout(() => setError(null), 5000);
    } finally {
      setActionLoading(false);
    }
  };

  if (!ticketId) return null;

  return (
    <div style={{
      gridArea: 'rightpanel',
      borderLeft: '1px solid var(--border-color)',
      backgroundColor: 'rgba(10, 10, 15, 0.95)',
      backdropFilter: 'blur(10px)',
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden',
      width: '350px'
    }}>
      {/* Header */}
      <div style={{ 
        padding: '16px', 
        borderBottom: '1px solid var(--border-color)',
        display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start'
      }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <h2 style={{ fontSize: '18px', fontWeight: '600' }}>Fault Ticket</h2>
          {ticket && <StatusBadge status={ticket.status} />}
        </div>
        <button 
          onClick={onClose}
          style={{ 
            background: 'none', color: 'var(--text-muted)', 
            padding: '4px', borderRadius: '4px' 
          }}
          onMouseOver={(e) => e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.1)'}
          onMouseOut={(e) => e.currentTarget.style.backgroundColor = 'transparent'}
        >
          <X size={20} />
        </button>
      </div>

      {loading ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: '40px' }}>
          <Loader2 size={24} color="var(--accent-blue)" className="animate-spin" style={{ animation: 'spin 1s linear infinite' }} />
        </div>
      ) : ticket ? (
        <div style={{ flex: 1, overflowY: 'auto', padding: '20px', display: 'flex', flexDirection: 'column', gap: '24px' }}>
          
          {/* Location */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <h3 style={{ fontSize: '12px', fontWeight: '600', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Location</h3>
            <p style={{ fontSize: '14px', lineHeight: '1.5' }}>{ticket.fault_location_description}</p>
            
            <div style={{ display: 'flex', gap: '16px', marginTop: '4px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--text-secondary)' }}>
                <MapPin size={14} />
                <span style={{ fontSize: '13px' }}>{ticket.lat.toFixed(5)}, {ticket.lon.toFixed(5)}</span>
              </div>
              {ticket.pincode && (
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--text-secondary)' }}>
                  <Hash size={14} />
                  <span style={{ fontSize: '13px' }}>{ticket.pincode}</span>
                </div>
              )}
            </div>
            <div>
              <ConfidenceBadge source={ticket.topology_source} />
            </div>
          </div>

          {/* Impact */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <h3 style={{ fontSize: '12px', fontWeight: '600', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Impact</h3>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
              <div style={{ backgroundColor: 'var(--bg-card)', padding: '12px', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Affected Poles</div>
                <div style={{ fontSize: '18px', fontWeight: '600', color: 'var(--accent-red)', marginTop: '4px' }}>{ticket.affected_poles_count}</div>
              </div>
              <div style={{ backgroundColor: 'var(--bg-card)', padding: '12px', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Estimated Households</div>
                <div style={{ fontSize: '18px', fontWeight: '600', marginTop: '4px' }}>{ticket.est_households_affected || '?'}</div>
              </div>
            </div>
            <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
              DT: <span style={{ color: 'var(--text-primary)' }}>{ticket.dt_id}</span> • Feeder: <span style={{ color: 'var(--text-primary)' }}>{ticket.feeder_id}</span>
            </div>
          </div>

          {/* Timeline */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <h3 style={{ fontSize: '12px', fontWeight: '600', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Timeline</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', position: 'relative', paddingLeft: '8px' }}>
              <div style={{ position: 'absolute', left: '11px', top: '8px', bottom: '8px', width: '2px', backgroundColor: 'var(--border-color)' }}></div>
              
              <TimelineItem 
                icon={<AlertTriangle size={12} color="#fff" />} 
                bg="var(--accent-red)"
                title="Fault Detected" 
                time={ticket.detected_at} 
                active={true}
              />
              <TimelineItem 
                icon={<CheckCircle2 size={12} color="#fff" />} 
                bg={ticket.acknowledged_at ? "var(--accent-amber)" : "var(--border-color)"}
                title="Acknowledged" 
                time={ticket.acknowledged_at} 
                active={!!ticket.acknowledged_at}
              />
              <TimelineItem 
                icon={<User size={12} color="#fff" />} 
                bg={['crew_assigned','resolved','verified','closed'].includes(ticket.status) ? "var(--accent-blue)" : "var(--border-color)"}
                title="Crew Assigned" 
                time={['crew_assigned','resolved','verified','closed'].includes(ticket.status) ? (ticket.acknowledged_at || ticket.detected_at) : null} 
                active={['crew_assigned','resolved','verified','closed'].includes(ticket.status)}
              />
              <TimelineItem 
                icon={<Wrench size={12} color="#fff" />} 
                bg={ticket.resolved_at ? "var(--accent-green)" : "var(--border-color)"}
                title="Resolved" 
                time={ticket.resolved_at} 
                active={!!ticket.resolved_at}
              />
            </div>
          </div>

          {/* Action Area */}
          <div style={{ marginTop: 'auto', paddingTop: '20px', borderTop: '1px solid var(--border-color)', display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {error && (
              <div style={{ padding: '8px 12px', backgroundColor: 'var(--accent-red-bg)', color: 'var(--accent-red)', borderRadius: '6px', fontSize: '13px', border: '1px solid rgba(255,68,68,0.3)' }}>
                {error}
              </div>
            )}
            
            {ticket.status === 'detected' && (
              <ActionButton onClick={() => handleAction('acknowledge')} loading={actionLoading} color="var(--accent-amber)" text="Acknowledge Fault" />
            )}
            {ticket.status === 'acknowledged' && (
              <ActionButton onClick={() => handleAction('assign_crew')} loading={actionLoading} color="var(--accent-blue)" text="Assign Crew" />
            )}
            {ticket.status === 'crew_assigned' && (
              <ActionButton onClick={() => handleAction('resolve')} loading={actionLoading} color="var(--accent-green)" text="Mark Resolved" />
            )}
            {ticket.status === 'resolved' && (
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px', padding: '12px', color: 'var(--accent-green)' }}>
                <Loader2 size={16} className="animate-spin" style={{ animation: 'spin 1s linear infinite' }} />
                <span style={{ fontSize: '14px', fontWeight: '500' }}>Waiting for auto-verification...</span>
              </div>
            )}
            {ticket.status === 'closed' && (
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px', padding: '12px', color: 'var(--text-muted)' }}>
                <CheckCircle2 size={16} />
                <span style={{ fontSize: '14px', fontWeight: '500' }}>Ticket Closed</span>
              </div>
            )}
          </div>

        </div>
      ) : (
        <div style={{ padding: '20px', color: 'var(--text-muted)' }}>Failed to load ticket details.</div>
      )}
      <style dangerouslySetInnerHTML={{__html: `
        @keyframes spin { 100% { transform: rotate(360deg); } }
      `}} />
    </div>
  );
}

function TimelineItem({ icon, bg, title, time, active }) {
  return (
    <div style={{ display: 'flex', gap: '12px', opacity: active ? 1 : 0.5 }}>
      <div style={{ 
        width: '24px', height: '24px', borderRadius: '50%', 
        backgroundColor: bg, display: 'flex', alignItems: 'center', 
        justifyContent: 'center', zIndex: 1 
      }}>
        {icon}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', paddingTop: '2px' }}>
        <span style={{ fontSize: '13px', fontWeight: '500', color: active ? 'var(--text-primary)' : 'var(--text-muted)' }}>{title}</span>
        <span style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
          {time ? format(new Date(time), 'MMM d, HH:mm:ss') : '--'}
        </span>
      </div>
    </div>
  );
}

function ActionButton({ onClick, loading, color, text }) {
  return (
    <button 
      onClick={onClick}
      disabled={loading}
      style={{
        width: '100%',
        padding: '12px',
        borderRadius: '8px',
        backgroundColor: color,
        color: '#fff',
        fontSize: '14px',
        fontWeight: '600',
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        gap: '8px',
        opacity: loading ? 0.7 : 1
      }}
    >
      {loading ? <Loader2 size={16} style={{ animation: 'spin 1s linear infinite' }} /> : null}
      {text}
    </button>
  );
}
