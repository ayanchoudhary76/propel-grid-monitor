import React, { useState, Component } from 'react';
import { TopBar } from './components/TopBar';
import { IncidentList } from './components/IncidentList';
import { Map } from './components/Map';
import { TicketDetail } from './components/TicketDetail';
import { SimulatorPanel } from './components/SimulatorPanel';

class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }
  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }
  componentDidCatch(error, info) {
    console.error('React Error Boundary caught:', error, info);
  }
  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          padding: '40px', color: '#ff4444', backgroundColor: '#0a0a0f',
          minHeight: '100vh', fontFamily: 'monospace'
        }}>
          <h1>⚠️ UI Error</h1>
          <pre style={{ color: '#ffaa00', whiteSpace: 'pre-wrap' }}>
            {this.state.error?.toString()}
          </pre>
          <button onClick={() => window.location.reload()}
            style={{ marginTop: '20px', padding: '10px 20px', background: '#ff4444', color: '#fff', border: 'none', borderRadius: '8px', cursor: 'pointer' }}>
            Reload
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

function App() {
  const [selectedTicketId, setSelectedTicketId] = useState(null);

  const handleSelectTicket = (id) => {
    setSelectedTicketId(id);
  };

  const handleCloseTicket = () => {
    setSelectedTicketId(null);
  };

  const handleActionComplete = () => {
    // We could trigger a re-fetch, but IncidentList and Map have usePolling,
    // so they will update naturally. We just let it ride.
  };

  return (
    <ErrorBoundary>
      <div className="app-container">
        <TopBar />
        
        <IncidentList 
          selectedTicketId={selectedTicketId} 
          onSelectTicket={handleSelectTicket} 
        />
        
        <Map 
          selectedTicketId={selectedTicketId} 
          onSelectTicket={handleSelectTicket} 
        />
        
        <TicketDetail 
          ticketId={selectedTicketId} 
          onClose={handleCloseTicket}
          onActionComplete={handleActionComplete}
        />
        
        <SimulatorPanel />
      </div>
    </ErrorBoundary>
  );
}

export default App;

