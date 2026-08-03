import React, { useState } from 'react';
import { TopBar } from './components/TopBar';
import { IncidentList } from './components/IncidentList';
import { Map } from './components/Map';
import { TicketDetail } from './components/TicketDetail';
import { SimulatorPanel } from './components/SimulatorPanel';

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
  );
}

export default App;
