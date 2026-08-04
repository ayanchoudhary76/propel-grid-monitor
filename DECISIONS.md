# Architectural Decisions Log

## 1. Geometric inference for missing topology
- **Chosen**: Greedy nearest-neighbor walk with bearing-based branch detection.
- **Rejected**: Assuming complete data (unrealistic), degrading to DT-level only for unmapped areas (loses granularity).
- **Why**: 60% of the grid lacks explicit wiring data. Geometric inference provides a "best guess" that is usually actionable for field crews, provided we communicate the lower confidence score (0.6) clearly in the UI.

## 2. 30-second debounce window
- **Chosen**: Debounce topology state evaluation for 30 seconds after the first event in a DT.
- **Rejected**: Immediate alerting (too noisy, jittery telemetry triggers false positives), longer windows (delays response times).
- **Why**: Devices experience clock skew (±90s) and jitter. 30 seconds allows enough time for the bulk of a large outage's telemetry to arrive before traversing the tree, preventing fragmented ticket creation.

## 3. Polling vs WebSockets
- **Chosen**: HTTP Polling (5s interval) from the React frontend.
- **Rejected**: WebSockets for real-time UI updates.
- **Why**: WebSockets introduce significant deployment complexity on free-tier hosting (timeout issues, proxy configurations, load balancing). 5-second polling provides near real-time feel for operators while keeping the infrastructure stateless and robust.

## 4. Graph traversal for localization
- **Chosen**: Deterministic BFS tree walk to find live/dark boundaries.
- **Rejected**: LLM-based detection or complex ML models.
- **Why**: Graph traversal is deterministic, instant, completely free, and 100% explainable. LLMs are too slow, non-deterministic, and expensive for raw fault localization.

## 5. PostgreSQL + Redis
- **Chosen**: Relational DB for persistence, Redis for state and pub/sub.
- **Rejected**: Pure DB approach (storing all state in Postgres).
- **Why**: Real-time telemetry ingestion (thousands of events per minute) would cause heavy write locks and read latency on Postgres. Redis handles the high-throughput state tracking and background task triggering efficiently.

## 6. Python/FastAPI vs Node.js
- **Chosen**: Python 3.11 with FastAPI.
- **Rejected**: Node.js/Express.
- **Why**: Fastest stack for the developer given the algorithmic nature of the BFS traversal and data processing. FastAPI provides excellent async support and automatic OpenAPI documentation.

## Assumptions Made
- The brief mentioned a "fictional Karnataka utility" but was ambiguous on exact hardware specs. Assumed devices transmit via HTTP POST instead of MQTT for simplicity of ingestion architecture.
- Assumed "restoration verified from telemetry" means all poles originally marked dark must report live status before auto-closing.

## What I would do with two more weeks
- Implement MQTT ingestion natively for lower IoT overhead.
- Build a more sophisticated historical analytics dashboard (MTTR metrics).
- Implement spatial indexing (PostGIS) to improve the performance of geometric inference for massive grids.

## What is currently wrong or fragile
- **Message Loss Edge Case**: If exactly 30-40% of telemetry messages are lost during a feeder-level fault, the 30s debounce might process a fragmented tree, creating multiple false span tickets instead of recognizing the overarching fault.
- **Inference in Dense Areas**: The geometric inference algorithm struggles in dense, overlapping urban topologies where lines run parallel but belong to different feeders.
