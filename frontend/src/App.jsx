import { useState, useEffect } from 'react'
import { MapContainer, TileLayer, Marker, Popup, CircleMarker, Tooltip } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import L from 'leaflet'

// Fix default Leaflet icon paths broken by Vite bundling
delete L.Icon.Default.prototype._getIconUrl
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
  iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
})

// ── Bangalore city centre ───────────────────────────────────────────────────
const BANGALORE_CENTER = [12.9716, 77.5946]
const INITIAL_ZOOM = 12

// ── Placeholder grid data (will be replaced by real API data) ───────────────
const PLACEHOLDER_SUBSTATIONS = [
  { id: 1, name: 'Hebbal Substation',         lat: 13.0358, lon: 77.5970 },
  { id: 2, name: 'Jayanagar Substation',      lat: 12.9250, lon: 77.5938 },
  { id: 3, name: 'Whitefield Substation',     lat: 12.9698, lon: 77.7500 },
  { id: 4, name: 'Rajajinagar Substation',    lat: 12.9900, lon: 77.5530 },
]

const PLACEHOLDER_POLES = [
  // Hebbal cluster
  { id: 'P-001', lat: 13.0300, lon: 77.5960, energized: true,  dt: 'D-0101' },
  { id: 'P-002', lat: 13.0280, lon: 77.5975, energized: false, dt: 'D-0101' },
  { id: 'P-003', lat: 13.0260, lon: 77.5990, energized: false, dt: 'D-0101' },
  { id: 'P-004', lat: 13.0310, lon: 77.5945, energized: true,  dt: 'D-0102' },
  // Jayanagar cluster
  { id: 'P-010', lat: 12.9270, lon: 77.5930, energized: true,  dt: 'D-0201' },
  { id: 'P-011', lat: 12.9260, lon: 77.5950, energized: true,  dt: 'D-0201' },
  { id: 'P-012', lat: 12.9240, lon: 77.5960, energized: true,  dt: 'D-0202' },
  // Whitefield cluster
  { id: 'P-020', lat: 12.9700, lon: 77.7480, energized: true,  dt: 'D-0301' },
  { id: 'P-021', lat: 12.9690, lon: 77.7510, energized: false, dt: 'D-0301' },
]

const PLACEHOLDER_TICKETS = [
  {
    id: 1,
    fault_type: 'span',
    status: 'detected',
    fault_location_description: 'Span fault between P-001 and P-002 on Feeder F-01-01',
    lat: 13.0290,
    lon: 77.5967,
    affected_downstream_count: 142,
    confidence: 0.92,
    feeder_id: 'F-01-01',
    detected_at: new Date(Date.now() - 8 * 60 * 1000).toISOString(),
  },
  {
    id: 2,
    fault_type: 'dt',
    status: 'crew_assigned',
    fault_location_description: 'DT fault at D-0301 — Whitefield sector',
    lat: 12.9695,
    lon: 77.7495,
    affected_downstream_count: 87,
    confidence: 0.78,
    feeder_id: 'F-03-02',
    detected_at: new Date(Date.now() - 34 * 60 * 1000).toISOString(),
  },
  {
    id: 3,
    fault_type: 'unknown',
    status: 'acknowledged',
    fault_location_description: 'Unknown fault — Rajajinagar zone, investigating',
    lat: 12.9880,
    lon: 77.5520,
    affected_downstream_count: 63,
    confidence: 0.45,
    feeder_id: 'F-04-01',
    detected_at: new Date(Date.now() - 72 * 60 * 1000).toISOString(),
  },
]

// ── Helpers ─────────────────────────────────────────────────────────────────
function timeAgo(isoString) {
  const diffMs = Date.now() - new Date(isoString).getTime()
  const mins = Math.floor(diffMs / 60000)
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  return `${hrs}h ${mins % 60}m ago`
}

function faultTypeLabel(ft) {
  const labels = { span: 'Wire Span', dt: 'DT Fault', feeder: 'Feeder', unknown: 'Unknown' }
  return labels[ft] ?? ft
}

// ── Sub-components ──────────────────────────────────────────────────────────

function Header({ tickets }) {
  const active   = tickets.filter(t => !['closed', 'resolved', 'verified'].includes(t.status))
  const critical = tickets.filter(t => t.status === 'detected')
  const resolved = tickets.filter(t => ['resolved', 'verified', 'closed'].includes(t.status))

  return (
    <header className="header">
      <div className="header-logo">
        <div className="header-logo-icon">⚡</div>
        <div className="header-title">
          <h1>Power Grid Fault Detection System</h1>
          <span>Karnataka State Power Distribution Board</span>
        </div>
      </div>

      <div className="header-divider" />

      <div className="header-badge live">
        <span className="dot" />
        Live
      </div>

      <div className="header-spacer" />

      <div className="header-stats">
        <div className="stat-chip danger">
          <span className="value">{critical.length}</span>
          <span className="label">Critical</span>
        </div>
        <div className="stat-chip warning">
          <span className="value">{active.length}</span>
          <span className="label">Active</span>
        </div>
        <div className="stat-chip success">
          <span className="value">{resolved.length}</span>
          <span className="label">Resolved</span>
        </div>
      </div>
    </header>
  )
}

function Legend() {
  return (
    <div className="map-overlay bottom-left">
      <div className="glass-panel legend-panel">
        <h3>Legend</h3>
        <div className="legend-item">
          <div className="legend-dot energized" />
          <span className="legend-label">Pole — Energized</span>
        </div>
        <div className="legend-item">
          <div className="legend-dot fault" />
          <span className="legend-label">Pole — De-energized / Fault</span>
        </div>
        <div className="legend-item">
          <div className="legend-dot transformer" />
          <span className="legend-label">Distribution Transformer</span>
        </div>
        <div className="legend-item">
          <div className="legend-dot unknown" />
          <span className="legend-label">Substation</span>
        </div>
      </div>
    </div>
  )
}

function RegionInfo() {
  return (
    <div className="map-overlay top-left">
      <div className="glass-panel region-panel">
        <div className="region-name">Bengaluru Urban District</div>
        <div className="region-sub">12.9716° N · 77.5946° E</div>
      </div>
    </div>
  )
}

function TicketCard({ ticket }) {
  return (
    <div className="ticket-card">
      <div className="ticket-card-top">
        <span className="ticket-id">#{String(ticket.id).padStart(4, '0')}</span>
        <span className={`ticket-status ${ticket.status}`}>{ticket.status.replace('_', ' ')}</span>
      </div>
      <div className="ticket-location">{ticket.fault_location_description}</div>
      <div className="ticket-meta">
        <span className="meta-tag">{faultTypeLabel(ticket.fault_type)}</span>
        <span className="meta-tag">~{ticket.affected_downstream_count} affected</span>
        <span className="meta-tag">{Math.round(ticket.confidence * 100)}% conf.</span>
        <span className="meta-tag">{timeAgo(ticket.detected_at)}</span>
      </div>
    </div>
  )
}

function Sidebar({ tickets }) {
  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <span>🎫</span>
        <h2>Active Fault Tickets</h2>
      </div>
      <div className="sidebar-body">
        {tickets.length === 0 ? (
          <div className="empty-state">
            <div className="icon">✅</div>
            <p>No active faults detected.<br />All grid segments are nominal.</p>
          </div>
        ) : (
          tickets.map(t => <TicketCard key={t.id} ticket={t} />)
        )}
      </div>
    </aside>
  )
}

// ── Main App ─────────────────────────────────────────────────────────────────
export default function App() {
  const [tickets]     = useState(PLACEHOLDER_TICKETS)
  const [poles]       = useState(PLACEHOLDER_POLES)
  const [substations] = useState(PLACEHOLDER_SUBSTATIONS)

  // Custom DT icon
  const dtIcon = L.divIcon({
    className: '',
    html: `<div style="
      width:14px;height:14px;border-radius:3px;
      background:#f59e0b;border:2px solid #fbbf24;
      box-shadow:0 0 8px rgba(245,158,11,0.6);
    "></div>`,
    iconAnchor: [7, 7],
  })

  // Substation icon
  const substationIcon = L.divIcon({
    className: '',
    html: `<div style="
      width:18px;height:18px;border-radius:50%;
      background:#64748b;border:2px solid #94a3b8;
      box-shadow:0 0 6px rgba(100,116,139,0.4);
      display:flex;align-items:center;justify-content:center;
      font-size:9px;color:#e2e8f0;font-weight:700;
    ">S</div>`,
    iconAnchor: [9, 9],
  })

  // Fault ticket icon
  const faultIcon = L.divIcon({
    className: '',
    html: `<div style="
      width:22px;height:22px;border-radius:50%;
      background:rgba(239,68,68,0.9);border:2px solid #fca5a5;
      display:flex;align-items:center;justify-content:center;
      font-size:12px;
      box-shadow:0 0 12px rgba(239,68,68,0.5);
      animation: pulse 1.5s ease-in-out infinite;
    ">⚠</div>`,
    iconAnchor: [11, 11],
  })

  return (
    <div className="app-shell">
      <Header tickets={tickets} />

      <div className="main-content">
        {/* ── Map ── */}
        <div className="map-container">
          <MapContainer
            center={BANGALORE_CENTER}
            zoom={INITIAL_ZOOM}
            style={{ height: '100%', width: '100%' }}
            zoomControl={true}
            attributionControl={true}
          >
            {/* OpenStreetMap tiles — dark-mode filter applied via CSS */}
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              maxZoom={19}
            />

            {/* Substations */}
            {substations.map(s => (
              <Marker key={s.id} position={[s.lat, s.lon]} icon={substationIcon}>
                <Popup>
                  <strong>{s.name}</strong><br />
                  <small>{s.lat.toFixed(4)}° N, {s.lon.toFixed(4)}° E</small>
                </Popup>
                <Tooltip direction="top" offset={[0, -10]} permanent={false}>
                  {s.name}
                </Tooltip>
              </Marker>
            ))}

            {/* Distribution Poles */}
            {poles.map(p => (
              <CircleMarker
                key={p.id}
                center={[p.lat, p.lon]}
                radius={5}
                pathOptions={{
                  fillColor:   p.energized ? '#22c55e' : '#ef4444',
                  fillOpacity: 0.9,
                  color:       p.energized ? '#4ade80' : '#fca5a5',
                  weight:      1.5,
                }}
              >
                <Popup>
                  <strong>Pole {p.id}</strong><br />
                  Status: <b style={{ color: p.energized ? 'green' : 'red' }}>
                    {p.energized ? 'Energized ✅' : 'De-energized ❌'}
                  </b><br />
                  DT: {p.dt}
                </Popup>
                <Tooltip direction="top" offset={[0, -6]}>{p.id}</Tooltip>
              </CircleMarker>
            ))}

            {/* Active Fault Tickets */}
            {tickets
              .filter(t => t.lat && t.lon)
              .map(t => (
                <Marker
                  key={t.id}
                  position={[t.lat, t.lon]}
                  icon={faultIcon}
                >
                  <Popup>
                    <strong>Fault #{String(t.id).padStart(4, '0')}</strong><br />
                    <b>Type:</b> {faultTypeLabel(t.fault_type)}<br />
                    <b>Status:</b> {t.status}<br />
                    <b>Affected:</b> ~{t.affected_downstream_count} poles<br />
                    <b>Confidence:</b> {Math.round(t.confidence * 100)}%<br />
                    <b>Detected:</b> {timeAgo(t.detected_at)}<br />
                    <hr style={{ margin: '6px 0' }} />
                    <small>{t.fault_location_description}</small>
                  </Popup>
                  <Tooltip direction="top" offset={[0, -12]} permanent={false}>
                    ⚠ Fault #{t.id} · {t.status}
                  </Tooltip>
                </Marker>
              ))}
          </MapContainer>

          {/* Overlay panels */}
          <RegionInfo />
          <Legend />
        </div>

        {/* ── Sidebar ── */}
        <Sidebar tickets={tickets} />
      </div>
    </div>
  )
}
