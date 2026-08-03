from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, HTTPException, Request
from pydantic import BaseModel

from app.core.scheduled_outages import ScheduledOutage, ScheduledOutageManager

router = APIRouter(prefix="/scheduled-outages", tags=["scheduled-outages"])

def get_outage_manager(request: Request) -> ScheduledOutageManager:
    return request.app.state.outage_manager

class OutageCreateReq(BaseModel):
    scope: str
    target_id: str
    start: datetime
    end: datetime
    reason: str

@router.get("")
async def get_outages(
    from_time: Optional[datetime] = Query(None, alias="from"),
    to_time: Optional[datetime] = Query(None, alias="to"),
    manager: ScheduledOutageManager = Depends(get_outage_manager)
):
    outages = manager._outages
    if from_time and to_time:
        result = []
        for o in outages:
            # Overlap condition: o.start <= to_time AND o.end >= from_time
            if o.start <= to_time and o.end >= from_time:
                result.append(o)
        return result
    return outages

@router.get("/active")
async def get_active_outages(
    manager: ScheduledOutageManager = Depends(get_outage_manager)
):
    return manager.get_active_outages()

@router.post("")
async def create_outage(
    req: OutageCreateReq,
    manager: ScheduledOutageManager = Depends(get_outage_manager)
):
    if req.scope not in ["feeder", "dt"]:
        raise HTTPException(status_code=400, detail="scope must be 'feeder' or 'dt'")
        
    outage_id = f"SO-{req.scope.upper()}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    outage = ScheduledOutage(
        id=outage_id,
        scope=req.scope,
        target_id=req.target_id,
        start=req.start,
        end=req.end,
        reason=req.reason
    )
    manager.add_outage(outage)
    return {"status": "created", "outage": outage}

@router.delete("/{outage_id}")
async def cancel_outage(
    outage_id: str,
    manager: ScheduledOutageManager = Depends(get_outage_manager)
):
    manager.remove_outage(outage_id)
    return {"status": "deleted"}
