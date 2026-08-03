import React, { useEffect, useState, useRef } from 'react';
import { MapContainer, TileLayer, Marker, Popup, Polyline, useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { api } from '../api';
import { usePolling } from '../hooks/usePolling';

// Fix leaflet icon issue in React
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
  iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
});

// Custom icons
const createIcon = (className) => L.divIcon({
  className: `map-marker ${className}`,
  iconSize: [12, 12],
  iconAnchor: [6, 6]
});

const dtIcon = L.divIcon({
  className: 'map-marker marker-dt',
  iconSize: [16, 16],
  iconAnchor: [8, 8]
});

const faultIcon = L.divIcon({
  className: 'map-marker marker-red',
  iconSize: [18, 18],
  iconAnchor: [9, 9]
});

const greenIcon = createIcon('marker-green');
const redIcon = createIcon('marker-red');
const grayIcon = createIcon('marker-gray');
const orangeIcon = createIcon('marker-orange');

// Component to handle map zooming/panning
function MapController({ center, zoom }) {
  const map = useMap();
  useEffect(() => {
    if (center) {
      map.flyTo(center, zoom, { duration: 1.5 });
    }
  }, [center, zoom, map]);
  return null;
}

export function Map({ selectedTicketId, onSelectTicket }) {
  const [dts, setDts] = useState([]);
  const [selectedDtId, setSelectedDtId] = useState(null);
  const [poles, setPoles] = useState([]);
  const [topology, setTopology] = useState(null);
  
  const { data: darkPolesSet } = usePolling(async () => {
    const list = await api.getDarkPoles();
    return new Set(list);
  }, 5000);
  
  const { data: activeTickets } = usePolling(api.getActiveTickets, 5000);

  const [mapCenter, setMapCenter] = useState([12.9716, 77.5946]);
  const [mapZoom, setMapZoom] = useState(12);

  // Initial load of DTs
  useEffect(() => {
    api.getTransformers().then(data => setDts(data));
  }, []);

  // When a ticket is selected, select its DT and pan to the fault location
  useEffect(() => {
    if (selectedTicketId && activeTickets) {
      const ticket = activeTickets.find(t => t.ticket_id === selectedTicketId);
      if (ticket) {
        setMapCenter([ticket.lat, ticket.lon]);
        setMapZoom(16);
        if (ticket.dt_id && ticket.dt_id !== selectedDtId) {
          setSelectedDtId(ticket.dt_id);
        }
      }
    }
  }, [selectedTicketId, activeTickets]);

  // When selected DT changes, load its poles and topology
  useEffect(() => {
    if (selectedDtId) {
      Promise.all([
        api.getPoles(selectedDtId),
        api.getTopology(selectedDtId)
      ]).then(([pData, tData]) => {
        setPoles(pData);
        setTopology(tData);
      });
    } else {
      setPoles([]);
      setTopology(null);
    }
  }, [selectedDtId]);

  // Build topology lines
  const lines = [];
  if (topology) {
    const isKnown = topology.topology_source === 'known';
    Object.values(topology.poles).forEach(node => {
      if (node.parent_id && topology.poles[node.parent_id]) {
        const parent = topology.poles[node.parent_id];
        lines.push({
          id: `${parent.pole_id}-${node.pole_id}`,
          positions: [
            [parent.lat, parent.lon],
            [node.lat, node.lon]
          ],
          isKnown
        });
      }
    });
  }

  const getPoleIcon = (pole) => {
    if (!pole.device_id) return grayIcon;
    if (darkPolesSet && darkPolesSet.has(pole.pole_id)) return redIcon; // Currently dark
    return greenIcon; // Assuming energized if it has a device and isn't in dark poles list
  };

  return (
    <div style={{ gridArea: 'map', position: 'relative' }}>
      <MapContainer 
        center={[12.9716, 77.5946]} 
        zoom={12} 
        style={{ height: '100%', width: '100%' }}
        zoomControl={false}
      >
        <TileLayer
          url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
          attribution='&copy; OpenStreetMap contributors &copy; CARTO'
        />
        
        <MapController center={mapCenter} zoom={mapZoom} />

        {/* Topology Lines */}
        {lines.map(line => (
          <Polyline 
            key={line.id} 
            positions={line.positions} 
            color={line.isKnown ? "#4b5563" : "#4b5563"} 
            weight={2} 
            dashArray={line.isKnown ? null : "4,4"} 
            opacity={0.6}
          />
        ))}

        {/* DT Markers */}
        {dts.map(dt => (
          <Marker 
            key={dt.id} 
            position={[dt.lat, dt.lon]} 
            icon={dtIcon}
            eventHandlers={{
              click: () => {
                setSelectedDtId(dt.id);
                setMapCenter([dt.lat, dt.lon]);
                setMapZoom(15);
              }
            }}
          >
            <Popup>
              <div style={{ fontWeight: '600' }}>Transformer {dt.id}</div>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Capacity: {dt.capacity_kva} kVA</div>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Feeder: {dt.feeder_id}</div>
            </Popup>
          </Marker>
        ))}

        {/* Pole Markers (only for selected DT) */}
        {poles.map(pole => (
          <Marker 
            key={pole.pole_id} 
            position={[pole.lat, pole.lon]} 
            icon={getPoleIcon(pole)}
          >
            <Popup>
              <div style={{ fontWeight: '600', marginBottom: '4px' }}>Pole {pole.pole_id}</div>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>DT: {pole.dt_id}</div>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                Device: {pole.device_id ? <span style={{ color: 'var(--text-primary)' }}>{pole.device_id}</span> : 'None'}
              </div>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '4px' }}>
                Status: {darkPolesSet?.has(pole.pole_id) ? <span style={{ color: 'var(--accent-red)' }}>Dark</span> : pole.device_id ? <span style={{ color: 'var(--accent-green)' }}>Energized</span> : 'Unknown'}
              </div>
            </Popup>
          </Marker>
        ))}

        {/* Fault Markers (from active tickets) */}
        {activeTickets?.map(ticket => (
          <Marker 
            key={`fault-${ticket.ticket_id}`} 
            position={[ticket.lat, ticket.lon]} 
            icon={faultIcon}
            eventHandlers={{
              click: () => onSelectTicket(ticket.ticket_id)
            }}
          />
        ))}

      </MapContainer>
    </div>
  );
}
