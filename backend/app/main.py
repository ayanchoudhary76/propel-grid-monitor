"""
FastAPI application entry point for the Karnataka State Power Distribution Board
Real-Time Fault Detection System.

Startup sequence
----------------
1. Create all DB tables  (idempotent — CREATE TABLE IF NOT EXISTS)
2. Seed synthetic network data  (no-op if Substation rows already exist)
3. Initialise async Redis connection pool
4. Build in-memory network topology graph

Shutdown sequence
-----------------
5. Close Redis connection pool gracefully

Re-running ``docker compose up`` is safe: the seed and table-creation steps
are both idempotent so no data is duplicated.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.ingest import router as ingest_router
from app.api.network import router as network_router
from app.api.pole_state import router as pole_state_router
from app.core.redis_client import close_redis, init_redis
from app.core.topology import NetworkTopology, build_topology
from app.database import AsyncSessionLocal, create_tables
from app.seed.generate_network import seed_database


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ────────────────────────────────────────────────────────────────
    await create_tables()
    await seed_database()
    await init_redis()

    # Build the in-memory topology graph (the most important startup step).
    # Uses a dedicated session that is closed immediately after.
    async with AsyncSessionLocal() as session:
        app.state.topology = await build_topology(session)

    yield
    # ── Shutdown ───────────────────────────────────────────────────────────────
    await close_redis()


app = FastAPI(
    title="Karnataka State Power Distribution Board — Fault Detection API",
    description=(
        "Real-time power grid fault detection and localisation system. "
        "Ingests IoT telemetry from distribution poles, localises faults to "
        "individual wire spans, and manages the complete ticket lifecycle."
    ),
    version="0.4.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# ---------------------------------------------------------------------------
# CORS — allow all origins in development
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(health_router)                  # GET  /api/health
app.include_router(network_router)                 # GET  /api/network/*
app.include_router(ingest_router, prefix="/api")   # POST /api/telemetry, /api/telemetry/batch
app.include_router(pole_state_router)              # GET  /api/poles/*


# ---------------------------------------------------------------------------
# Topology dependency — inject into any route that needs the live graph
# ---------------------------------------------------------------------------

def get_topology(request: Request) -> NetworkTopology:
    """
    FastAPI dependency: return the shared in-memory :class:`NetworkTopology`.

    Usage::

        @router.get("/my-route")
        async def my_handler(topo: NetworkTopology = Depends(get_topology)):
            ...
    """
    return request.app.state.topology


@app.get("/", tags=["root"])
async def root():
    """API root — links to key endpoints."""
    return {
        "message": "Karnataka State Power Distribution Board — Fault Detection API",
        "docs": "/api/docs",
        "health": "/api/health",
        "network_stats": "/api/network/stats",
        "topology_summary": "/api/network/topology-summary",
        "telemetry_ingest": "/api/telemetry",
        "dark_poles": "/api/poles/dark",
    }
