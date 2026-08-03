import React, { useState, useEffect } from 'react';
import { Activity, AlertOctagon, Zap, ShieldCheck } from 'lucide-react';
import { usePolling } from '../hooks/usePolling';
import { api } from '../api';

export function TopBar() {
  const [time, setTime] = useState(new Date());
  const { data: stats } = usePolling(api.getStats, 30000);

  useEffect(() => {
    const timer = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  const totalPoles = stats?.total_poles || 0;
  const onlinePoles = stats?.live_poles || 0;
  const activeFaults = stats?.active_tickets || 0;

  return (
    <div style={{
      gridArea: 'header',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: '0 24px',
      borderBottom: '1px solid var(--border-color)',
      backgroundColor: 'var(--bg-card)',
      zIndex: 100
    }}>
      {/* Left: Logo & Title */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
        <div style={{ 
          width: '32px', height: '32px', 
          backgroundColor: 'var(--accent-blue)', 
          borderRadius: '8px',
          display: 'flex', alignItems: 'center', justifyContent: 'center'
        }}>
          <Zap size={20} color="#fff" />
        </div>
        <h1 style={{ fontSize: '18px', fontWeight: '600', letterSpacing: '-0.5px' }}>
          KSPDB Grid Monitor
        </h1>
      </div>

      {/* Center: Stats */}
      <div style={{ display: 'flex', gap: '24px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Activity size={16} color="var(--text-muted)" />
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            <span style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Network Status</span>
            <span style={{ fontSize: '13px', fontWeight: '500' }}>
              {onlinePoles.toLocaleString()} / {totalPoles.toLocaleString()} Live
            </span>
          </div>
        </div>
        
        <div style={{ 
          display: 'flex', alignItems: 'center', gap: '8px',
          padding: '4px 12px', borderRadius: '20px',
          backgroundColor: activeFaults > 0 ? 'var(--accent-red-bg)' : 'var(--accent-green-bg)',
          border: `1px solid ${activeFaults > 0 ? 'var(--accent-red)' : 'var(--accent-green)'}40`
        }}>
          {activeFaults > 0 ? (
            <AlertOctagon size={16} color="var(--accent-red)" />
          ) : (
            <ShieldCheck size={16} color="var(--accent-green)" />
          )}
          <span style={{ 
            fontSize: '13px', fontWeight: '600', 
            color: activeFaults > 0 ? 'var(--accent-red)' : 'var(--accent-green)'
          }}>
            {activeFaults > 0 ? `${activeFaults} Active Faults` : 'All Systems Normal'}
          </span>
        </div>
      </div>

      {/* Right: Clock & Connection */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <div style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: 'var(--accent-green)' }}></div>
          <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Connected</span>
        </div>
        <div style={{ fontSize: '14px', fontWeight: '500', fontVariantNumeric: 'tabular-nums' }}>
          {time.toLocaleTimeString()}
        </div>
      </div>
    </div>
  );
}
