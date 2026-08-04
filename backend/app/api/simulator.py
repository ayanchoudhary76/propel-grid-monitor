import random
from typing import Optional, List, Dict
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.simulator import FaultSimulator, SimulatedFault


router = APIRouter(tags=["simulator"])

def get_simulator(request: Request) -> FaultSimulator:
    return request.app.state.simulator


class SpanFaultReq(BaseModel):
    upstream_pole_id: Optional[str] = None
    downstream_pole_id: Optional[str] = None
    dt_id: Optional[str] = None

class DtFaultReq(BaseModel):
    dt_id: str

class FeederFaultReq(BaseModel):
    feeder_id: str

class RepairReq(BaseModel):
    fault_id: str

class KillDeviceReq(BaseModel):
    pole_id: str

class ScheduledOutageReq(BaseModel):
    scope: str
    target_id: str
    duration_minutes: int = 120
    reason: str = "Load shedding"

class DuplicateReq(BaseModel):
    pole_id: str
    count: int = 5

class StaleReq(BaseModel):
    pole_id: str


@router.post("/simulator/fault/span")
async def simulate_span_fault(req: SpanFaultReq, sim: FaultSimulator = Depends(get_simulator)):
    if req.dt_id:
        poles = sim.topology.get_poles_for_dt(req.dt_id)
        if not poles:
            raise HTTPException(404, "No poles for DT")
        
        # A span fault is detectable only when at least one affected pole has
        # a device.  Do not randomly select an unmonitored leaf: it would show
        # up as an active simulated fault but could never create an incident.
        spans = []
        for p in poles:
            for child_id in p.children:
                if sim.topology.get_subtree_device_count(child_id) > 0:
                    spans.append((p.pole_id, child_id))
                
        if not spans:
            raise HTTPException(400, "No observable spans found in DT")
            
        up, down = random.choice(spans)
        try:
            return await sim.inject_span_fault(up, down)
        except ValueError as e:
            raise HTTPException(422, str(e))
    
    if req.upstream_pole_id and req.downstream_pole_id:
        try:
            return await sim.inject_span_fault(req.upstream_pole_id, req.downstream_pole_id)
        except ValueError as e:
            raise HTTPException(422, str(e))
        
    raise HTTPException(400, "Must provide dt_id or both upstream_pole_id and downstream_pole_id")


@router.post("/simulator/fault/dt")
async def simulate_dt_fault(req: DtFaultReq, sim: FaultSimulator = Depends(get_simulator)):
    try:
        return await sim.inject_dt_fault(req.dt_id)
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.post("/simulator/fault/feeder")
async def simulate_feeder_fault(req: FeederFaultReq, sim: FaultSimulator = Depends(get_simulator)):
    try:
        return await sim.inject_feeder_fault(req.feeder_id)
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.post("/simulator/repair")
async def repair_fault(req: RepairReq, sim: FaultSimulator = Depends(get_simulator)):
    try:
        return await sim.repair_fault(req.fault_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/simulator/noise/kill-device")
async def kill_device(req: KillDeviceReq, sim: FaultSimulator = Depends(get_simulator)):
    try:
        return await sim.kill_device(req.pole_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/simulator/noise/scheduled-outage")
async def scheduled_outage(req: ScheduledOutageReq, sim: FaultSimulator = Depends(get_simulator)):
    return await sim.inject_scheduled_outage(
        req.scope, req.target_id, req.duration_minutes, req.reason
    )


@router.post("/simulator/noise/duplicate")
async def inject_duplicate(req: DuplicateReq, sim: FaultSimulator = Depends(get_simulator)):
    try:
        return await sim.inject_duplicate_messages(req.pole_id, req.count)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/simulator/noise/stale")
async def inject_stale(req: StaleReq, sim: FaultSimulator = Depends(get_simulator)):
    try:
        return await sim.inject_stale_message(req.pole_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/simulator/active-faults")
async def get_active_faults(sim: FaultSimulator = Depends(get_simulator)):
    return list(sim.active_faults.values())


@router.post("/simulator/reset")
async def reset_simulator(sim: FaultSimulator = Depends(get_simulator)):
    return await sim.reset()


@router.post("/simulator/init-all-live")
async def init_all_live(sim: FaultSimulator = Depends(get_simulator)):
    return await sim.init_all_live()
