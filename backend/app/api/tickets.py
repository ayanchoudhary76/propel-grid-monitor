from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as aioredis
from datetime import datetime, timezone

from app.database import get_db
from app.core.redis_client import get_redis_dep
from app.models.ticket import Ticket, TicketStatus

router = APIRouter(prefix="/tickets", tags=["tickets"])

@router.get("")
async def list_tickets(
    status: Optional[TicketStatus] = Query(None),
    active: Optional[bool] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Ticket).order_by(Ticket.detected_at.desc())
    if status:
        stmt = stmt.where(Ticket.status == status)
    if active:
        stmt = stmt.where(Ticket.status != TicketStatus.closed)
        
    result = await db.execute(stmt)
    tickets = result.scalars().all()
    return tickets

@router.get("/active-count")
async def active_ticket_count(db: AsyncSession = Depends(get_db)):
    stmt = select(func.count()).where(Ticket.status != TicketStatus.closed)
    result = await db.execute(stmt)
    count = result.scalar_one()
    return {"active_count": count}

@router.get("/{ticket_id}")
async def get_ticket(ticket_id: int, db: AsyncSession = Depends(get_db)):
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket

@router.patch("/{ticket_id}/acknowledge")
async def acknowledge_ticket(ticket_id: int, db: AsyncSession = Depends(get_db)):
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    if ticket.status == TicketStatus.detected:
        ticket.status = TicketStatus.acknowledged
        ticket.acknowledged_at = datetime.now(timezone.utc)
        await db.commit()
    return {"status": "ok", "ticket_status": ticket.status}

@router.patch("/{ticket_id}/assign-crew")
async def assign_crew_ticket(ticket_id: int, db: AsyncSession = Depends(get_db)):
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    if ticket.status in [TicketStatus.detected, TicketStatus.acknowledged]:
        ticket.status = TicketStatus.crew_assigned
        await db.commit()
    return {"status": "ok", "ticket_status": ticket.status}

@router.patch("/{ticket_id}/resolve")
async def resolve_ticket(
    ticket_id: int, 
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis_dep)
):
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
        
    if ticket.affected_pole_ids:
        # Check Redis if they are all energized
        pipe = redis.pipeline()
        for pid in ticket.affected_pole_ids:
            pipe.hget(f"pole:{pid}", "energized")
        results = await pipe.execute()
        
        dark_count = sum(1 for r in results if r == "0")
        if dark_count > 0:
            total = len(ticket.affected_pole_ids)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot resolve: {dark_count} of {total} poles still dark"
            )
            
    ticket.status = TicketStatus.resolved
    ticket.resolved_at = datetime.now(timezone.utc)
    await db.commit()
    return {"status": "ok", "ticket_status": ticket.status}
