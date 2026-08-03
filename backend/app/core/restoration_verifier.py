import asyncio
import json
import logging
from typing import Optional
from datetime import datetime, timezone, timedelta

import redis.asyncio as aioredis
from sqlalchemy import select

from app.core.topology import NetworkTopology
from app.models.ticket import Ticket, TicketStatus

logger = logging.getLogger(__name__)

class RestorationVerifier:
    def __init__(
        self,
        topology: NetworkTopology,
        redis_client: aioredis.Redis,
        db_session_factory
    ):
        self.topology = topology
        self.redis = redis_client
        self.db_session_factory = db_session_factory
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        """Start periodic check every 15 seconds."""
        self._task = asyncio.create_task(self._loop())
        logger.info("RestorationVerifier started")

    async def stop(self):
        """Graceful shutdown."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("RestorationVerifier stopped")

    async def _loop(self):
        while True:
            try:
                await asyncio.sleep(15)
                await self._check_restorations()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in RestorationVerifier: {e}", exc_info=True)

    async def _check_restorations(self):
        """
        For each ticket with status in (detected, acknowledged, crew_assigned, resolved):
        1. Query Redis for the state of all affected poles
        2. If ALL affected poles are now energized:
           - If status was 'resolved': move to 'verified', set verified_at = now()
           - If status was detected/acknowledged/crew_assigned: move to 'verified' 
           - Auto-close: if status is 'verified' and it's been verified for > 5 minutes, move to 'closed'
        """
        async with self.db_session_factory() as session:
            stmt = select(Ticket).where(Ticket.status != TicketStatus.closed)
            result = await session.execute(stmt)
            open_tickets = result.scalars().all()
            
            now = datetime.now(timezone.utc)
            
            for ticket in open_tickets:
                if ticket.status == TicketStatus.verified:
                    if ticket.verified_at and now - ticket.verified_at > timedelta(minutes=5):
                        ticket.status = TicketStatus.closed
                        ticket.closed_at = now
                        await session.commit()
                        logger.info(f"Ticket {ticket.id} auto-closed after 5 mins of verification.")
                        await self._publish_update(ticket)
                    continue

                if not ticket.affected_pole_ids:
                    continue
                    
                # Check Redis
                pipe = self.redis.pipeline()
                for pid in ticket.affected_pole_ids:
                    pipe.hget(f"pole:{pid}", "energized")
                results = await pipe.execute()
                
                # Check if ALL are energized
                # Ignore ones without telemetry (None)
                all_energized = True
                for res in results:
                    if res == "0":
                        all_energized = False
                        break
                        
                if all_energized:
                    old_status = ticket.status
                    ticket.status = TicketStatus.verified
                    ticket.verified_at = now
                    
                    if old_status != TicketStatus.resolved:
                        logger.info(f"Ticket {ticket.id} auto-resolved and verified from telemetry (was {old_status.value}).")
                    else:
                        logger.info(f"Ticket {ticket.id} verified from telemetry.")
                        
                    await session.commit()
                    await self._publish_update(ticket)
                    
    async def _publish_update(self, ticket: Ticket):
        update_dict = {
            "id": ticket.id,
            "status": ticket.status.value,
            "verified_at": ticket.verified_at.isoformat() if ticket.verified_at else None,
            "closed_at": ticket.closed_at.isoformat() if ticket.closed_at else None
        }
        await self.redis.publish("ticket_updates", json.dumps(update_dict))
