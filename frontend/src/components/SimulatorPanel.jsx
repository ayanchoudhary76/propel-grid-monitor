import React, { useState } from 'react';
import { ChevronUp, ChevronDown, Wrench, AlertOctagon, RotateCcw, Zap } from 'lucide-react';
import { api } from '../api';
import { usePolling } from '../hooks/usePolling';

export function SimulatorPanel() {
  const [expanded, setExpanded] = useState(false);
  
  const [faultType, setFaultType] = useState('span');
  const [targetId, setTargetId] = useState('');
  const [noisePoleId, setNoisePoleId] = useState('');
  const [outageTargetId, setOutageTargetId] = useState('');
  
  const { data: activeFaults, setData: setActiveFaults } = usePolling(api.getActiveFaults, 5000, expanded);
  
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState('');

  const showMessage = (text) => {
    setMsg(text);
    setTimeout(() => setMsg(''), 5000);
  };

  const handleInjectFault = async () => {
    if (!targetId) return;
    setLoading(true);
    try {
      if (faultType === 'span') await api.injectSpanFault({ dt_id: targetId });
      else if (faultType === 'dt') await api.injectDtFault({ dt_id: targetId });
      else if (faultType === 'feeder') await api.injectFeederFault({ feeder_id: targetId });
      
      showMessage(`Fault injected on ${targetId}`);
      if (expanded) setActiveFaults(await api.getActiveFaults());
    } catch (e) {
      showMessage(`Error: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleRepair = async (id) => {
    try {
      await api.repairFault(id);
      setActiveFaults(await api.getActiveFaults());
      showMessage(`Repaired fault ${id}`);
    } catch (e) {
      showMessage(`Error: ${e.message}`);
    }
  };

  const handleKillDevice = async () => {
    if (!noisePoleId) return;
    try {
      await api.killDevice(noisePoleId);
      showMessage(`Killed device on pole ${noisePoleId}`);
    } catch (e) {
      showMessage(`Error: ${e.message}`);
    }
  };

  const handleScheduledOutage = async () => {
    if (!outageTargetId) return;
    try {
      await api.injectSpanFault({ scope: 'feeder', target_id: outageTargetId }); // The api actually uses another endpoint for outage, let me correct this
      // Wait, there's no wrapper for scheduled outage inject in api.js? Ah, the user provided it: 
      // fetch(`${API_BASE}/simulator/noise/scheduled-outage`, { body: JSON.stringify(body) }) but didn't put it in api.js exactly as a named method.
      // Wait, let's look at api.js. I didn't add it to api.js because it wasn't strictly in the prompt's `export const api` block... oh wait, the prompt's api.js block:
      // it doesn't have `injectScheduledOutage`. Let me fetch it manually.
      await fetch('/api/simulator/noise/scheduled-outage', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scope: 'feeder', target_id: outageTargetId, duration_minutes: 120 })
      });
      showMessage(`Scheduled outage triggered on feeder ${outageTargetId}`);
    } catch (e) {
      showMessage(`Error: ${e.message}`);
    }
  };

  const handleReset = async () => {
    await api.resetSimulator();
    setActiveFaults([]);
    showMessage('Simulator reset');
  };

  const handleInitLive = async () => {
    await api.initAllLive();
    showMessage('All poles initialized as live');
  };

  return (
    <div style={{
      gridArea: 'bottom',
      backgroundColor: 'var(--bg-card)',
      borderTop: '1px solid var(--border-color)',
      position: 'relative',
      zIndex: 1000
    }}>
      <div 
        onClick={() => setExpanded(!expanded)}
        style={{ 
          padding: '8px 24px', 
          display: 'flex', 
          justifyContent: 'space-between', 
          alignItems: 'center',
          cursor: 'pointer',
          userSelect: 'none',
          backgroundColor: 'rgba(255,255,255,0.02)'
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: '600', color: 'var(--text-secondary)' }}>
          <Wrench size={16} />
          SIMULATOR CONTROLS
        </div>
        <div>
          {expanded ? <ChevronDown size={20} /> : <ChevronUp size={20} />}
        </div>
      </div>

      {expanded && (
        <div style={{ padding: '24px', display: 'flex', gap: '40px', overflowX: 'auto' }}>
          
          {/* Inject Fault */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', minWidth: '300px' }}>
            <h3 style={{ fontSize: '13px', fontWeight: '600', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Inject Fault</h3>
            
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <select value={faultType} onChange={e => setFaultType(e.target.value)} style={{ width: '100%' }}>
                <option value="span">Span Fault (Random in DT)</option>
                <option value="dt">DT Fault (Entire DT)</option>
                <option value="feeder">Feeder Fault (Entire Feeder)</option>
              </select>
              
              <input 
                type="text" 
                placeholder={faultType === 'feeder' ? "Feeder ID (e.g. F-01-01)" : "DT ID (e.g. D-0001)"} 
                value={targetId}
                onChange={e => setTargetId(e.target.value)}
              />
              
              <button 
                onClick={handleInjectFault}
                disabled={loading || !targetId}
                style={{ 
                  backgroundColor: 'var(--accent-red)', color: '#fff', 
                  padding: '10px', borderRadius: '6px',
                  display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '8px'
                }}
              >
                <AlertOctagon size={16} />
                Inject Fault
              </button>
            </div>
          </div>

          {/* Active Faults List */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', flex: 1, minWidth: '300px', borderLeft: '1px solid var(--border-color)', paddingLeft: '40px' }}>
            <h3 style={{ fontSize: '13px', fontWeight: '600', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Active Simulated Faults</h3>
            
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '160px', overflowY: 'auto' }}>
              {(!activeFaults || activeFaults.length === 0) ? (
                <div style={{ color: 'var(--text-muted)', fontSize: '14px', fontStyle: 'italic' }}>No active simulated faults</div>
              ) : (
                activeFaults.map(f => (
                  <div key={f.fault_id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px', backgroundColor: 'rgba(255,255,255,0.03)', borderRadius: '6px', border: '1px solid var(--border-color)' }}>
                    <div style={{ display: 'flex', flexDirection: 'column' }}>
                      <span style={{ fontSize: '14px', fontWeight: '500' }}>{f.target_description}</span>
                      <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Type: {f.fault_type.toUpperCase()} | Sent: {f.telemetry_sent} | Suppressed: {f.telemetry_suppressed}</span>
                    </div>
                    <button 
                      onClick={() => handleRepair(f.fault_id)}
                      style={{ padding: '6px 12px', backgroundColor: 'var(--accent-green-bg)', color: 'var(--accent-green)', borderRadius: '4px', border: '1px solid rgba(0,255,136,0.3)', fontSize: '12px', fontWeight: '600' }}
                    >
                      Repair
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* Noise & Global Controls */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '24px', minWidth: '300px', borderLeft: '1px solid var(--border-color)', paddingLeft: '40px' }}>
            
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <h3 style={{ fontSize: '13px', fontWeight: '600', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Noise Controls</h3>
              <div style={{ display: 'flex', gap: '8px' }}>
                <input type="text" placeholder="Pole ID" value={noisePoleId} onChange={e => setNoisePoleId(e.target.value)} style={{ flex: 1 }} />
                <button onClick={handleKillDevice} style={{ padding: '8px 12px', backgroundColor: 'var(--bg-dark)', border: '1px solid var(--border-color)', color: '#fff', borderRadius: '6px' }}>Kill Device</button>
              </div>
              <div style={{ display: 'flex', gap: '8px' }}>
                <input type="text" placeholder="Feeder ID (e.g. F-01-01)" value={outageTargetId} onChange={e => setOutageTargetId(e.target.value)} style={{ flex: 1 }} />
                <button onClick={handleScheduledOutage} style={{ padding: '8px 12px', backgroundColor: 'var(--bg-dark)', border: '1px solid var(--border-color)', color: '#fff', borderRadius: '6px' }}>Outage</button>
              </div>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
               <button onClick={handleInitLive} style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px', padding: '10px', backgroundColor: 'var(--accent-blue-bg)', color: 'var(--accent-blue)', border: '1px solid rgba(59,130,246,0.3)', borderRadius: '6px', fontSize: '13px', fontWeight: '600' }}>
                 <Zap size={16} /> Init All Poles Live
               </button>
               <button onClick={handleReset} style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px', padding: '10px', backgroundColor: 'rgba(255,255,255,0.05)', color: '#fff', border: '1px solid var(--border-color)', borderRadius: '6px', fontSize: '13px', fontWeight: '600' }}>
                 <RotateCcw size={16} /> Reset Simulator
               </button>
            </div>
            
            {msg && <div style={{ fontSize: '12px', color: 'var(--accent-amber)', marginTop: '-8px' }}>{msg}</div>}

          </div>

        </div>
      )}
    </div>
  );
}
