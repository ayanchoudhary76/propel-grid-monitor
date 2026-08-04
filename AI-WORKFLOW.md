# AI Workflow

## Tools Used
- **Claude 3.5 Sonnet / Gemini 1.5 Pro**: Used as the primary reasoning engines for architectural design, code generation, and test scaffolding.

## Delegation vs Hand-Written
- **Delegated**: Boilerplate setup (FastAPI CRUD, Dockerfile, docker-compose.yml), UI component scaffolding (React/Vite setup, Tailwind/CSS baseline), mock data generation for the simulator, and the majority of standard CRUD API endpoints.
- **Hand-Written / Heavily Guided**: The core deterministic fault localization algorithm (BFS tree walk), the geometric inference logic, race condition handling in Redis, and the complex unit tests for edge cases (clock skew, message loss).

## Concrete AI Failures
1. **Missing Imports**: The AI generated `simulator.py` but missed the `from typing import Tuple` import, causing a runtime crash on startup.
2. **Message Loss Hallucination**: When prompted to handle 30% message loss for a DT fault, the AI initially produced logic that triggered 13 individual span tickets instead of waiting for the debounce to cluster them into a single DT ticket. I had to manually enforce the topological grouping rules.
3. **Map Rendering Bug**: The AI's React component for Leaflet attempted to render inferred lines using an invalid SVG stroke-dasharray format, causing the lines to disappear entirely on the frontend until manually corrected.

## Code Generation Estimate
Roughly **90%** of the raw syntax and lines of code were AI-generated. However, the architectural design, algorithmic rules, and debugging of race conditions were driven by human prompts and manual intervention.

## Prompt-by-Prompt Workflow
1. **Initial Scaffold**: "Generate a FastAPI backend with PostgreSQL and Redis, and a Vite React frontend. Provide the docker-compose.yml."
2. **Schema Definition**: "Create SQLAlchemy models for Substation, Feeder, DT, Pole, TelemetryEvent, and Ticket. Ensure parent_pole_id is a nullable foreign key."
3. **Ingestion Layer**: "Write the POST /api/telemetry endpoint. Implement deduplication using device_id and seq in Redis."
4. **Core Algorithm (Iterative)**:
   - *Prompt 1*: "Write a background task that listens to Redis. Perform a BFS on the pole tree to find edges where parent is LIVE and child is DARK."
   - *Prompt 2*: "Refine the logic: If a pole is DARK but its child is LIVE, flag it as a dead sensor instead of a fault."
   - *Prompt 3*: "Add a 30-second debounce window per DT before running the BFS."
5. **Simulator**: "Create a simulator script that injects faults. Simulate 70% delivery success, clock skew up to 90s, and jitter."
6. **Frontend Map**: "Build a React component using Leaflet. Fetch the topology from /api/topology/tree and draw lines. Style the map darkly for a control room."
7. **Refinement & Testing**: "Write pytest unit tests for the BFS logic, specifically testing the dead sensor case and the feeder fault escalation."
