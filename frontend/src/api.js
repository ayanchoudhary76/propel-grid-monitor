const API_BASE = '/api';

export const api = {
  // Network
  getStats: () => fetch(`${API_BASE}/network/stats`).then(r => r.json()),
  getTransformers: () => fetch(`${API_BASE}/network/transformers`).then(r => r.json()),
  getPoles: (dtId) => fetch(`${API_BASE}/network/poles${dtId ? `?dt_id=${dtId}` : ''}`).then(r => r.json()),
  getTopology: (dtId) => fetch(`${API_BASE}/network/topology/${dtId}`).then(r => r.json()),
  getTopologySummary: () => fetch(`${API_BASE}/network/topology-summary`).then(r => r.json()),
  
  // Pole state
  getDarkPoles: () => fetch(`${API_BASE}/poles/dark`).then(r => r.json()),
  getPoleState: (poleId) => fetch(`${API_BASE}/poles/state/${poleId}`).then(r => r.json()),
  
  // Tickets
  getActiveTickets: () => fetch(`${API_BASE}/tickets?active=true`).then(r => r.json()),
  getTicket: (id) => fetch(`${API_BASE}/tickets/${id}`).then(r => r.json()),
  acknowledgeTicket: (id) => fetch(`${API_BASE}/tickets/${id}/acknowledge`, { method: 'PATCH' }).then(r => r.json()),
  assignCrew: (id) => fetch(`${API_BASE}/tickets/${id}/assign-crew`, { method: 'PATCH' }).then(r => r.json()),
  resolveTicket: (id) => fetch(`${API_BASE}/tickets/${id}/resolve`, { method: 'PATCH' }).then(r => r.json()),
  
  // Scheduled outages
  getActiveOutages: () => fetch(`${API_BASE}/scheduled-outages/active`).then(r => r.json()),
  
  // Simulator
  injectSpanFault: (body) => fetch(`${API_BASE}/simulator/fault/span`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) }).then(r => r.json()),
  injectDtFault: (body) => fetch(`${API_BASE}/simulator/fault/dt`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) }).then(r => r.json()),
  injectFeederFault: (body) => fetch(`${API_BASE}/simulator/fault/feeder`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) }).then(r => r.json()),
  repairFault: (faultId) => fetch(`${API_BASE}/simulator/repair`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ fault_id: faultId }) }).then(r => r.json()),
  killDevice: (poleId) => fetch(`${API_BASE}/simulator/noise/kill-device`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ pole_id: poleId }) }).then(r => r.json()),
  getActiveFaults: () => fetch(`${API_BASE}/simulator/active-faults`).then(r => r.json()),
  resetSimulator: () => fetch(`${API_BASE}/simulator/reset`, { method: 'POST' }).then(r => r.json()),
  initAllLive: () => fetch(`${API_BASE}/simulator/init-all-live`, { method: 'POST' }).then(r => r.json()),
};
