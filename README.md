# KSPDB Real-Time Power Grid Fault Detection

A real-time telemetry ingestion and fault localization system for electricity distribution networks.

## Quick Start
```bash
docker compose up --build
```

- **Public URL**: [https://propel-grid-monitor.onrender.com](https://propel-grid-monitor.onrender.com)
- **Demo Video**: [TO BE FILLED]

> ⚠️ **Free tier** — first load may take 30-60 seconds as the server wakes from sleep.

## Overview
This system monitors power distribution poles in real-time using IoT telemetry data. It automatically detects power outages, pinpoints the exact wire span or equipment where the fault occurred, and generates actionable repair tickets for field crews. By differentiating between actual faults, scheduled maintenance, and dead sensors, it significantly reduces noise and operator fatigue.

## UI Screenshot
![Operator Dashboard Placeholder](https://via.placeholder.com/800x450.png?text=Operator+Console+Dashboard+Map)
*(The dashboard features a dark-themed Leaflet map showing grid topology, an active incident list, and a detailed ticket panel.)*

## Documentation
- [Architecture Details](ARCHITECTURE.md)
- [Deployment Guide](DEPLOYMENT.md)
- [Design Decisions](DECISIONS.md)
- [AI Workflow](AI-WORKFLOW.md)

## Tech Stack
- **Backend**: Python 3.11, FastAPI
- **Frontend**: React 18, Vite
- **Database**: PostgreSQL 15
- **In-Memory Store / Message Broker**: Redis 7
- **Mapping**: Leaflet / OpenStreetMap
- **Containerization**: Docker, Docker Compose

## Running Tests
To run the backend unit tests for localization logic:
```bash
cd backend
pytest
```

## Fault Simulator
The system includes a realistic fault simulator to inject telemetry data and simulate outages. 
You can use the operator console UI or the backend simulator scripts to:
- Inject span, DT (Distribution Transformer), or feeder faults.
- Simulate a 70% power loss delivery with silence (FW 1.2), clock skew (±90s), and jitter (0-5s).
- Inject noise and simulate dead sensors.
- Resolve faults by restoring power telemetry to affected poles.
