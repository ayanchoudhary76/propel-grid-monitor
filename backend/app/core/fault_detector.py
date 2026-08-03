import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import redis.asyncio as aioredis
from sqlalchemy import select, and_

from app.core.topology import NetworkTopology
from app.models.ticket import Ticket, FaultType, TicketStatus, TopologySource

logger = logging.getLogger(__name__)

@dataclass
class FaultBoundary:
    upstream_pole_id: str
    downstream_pole_id: str
    lat: float
    lon: float
    pincode: Optional[str]
    affected_count: int
    confidence: float
    confidence_reason: str
    topology_source: str

class FaultDetector:
    def __init__(
        self,
        topology: NetworkTopology,
        redis_client: aioredis.Redis,
        db_session_factory
    ):
        self.topology = topology
        self.redis = redis_client
        self.db_session_factory = db_session_factory
        self._listener_task: Optional[asyncio.Task] = None
        self._debounce_tasks: Dict[str, asyncio.Task] = {}
        self.debounce_seconds = 30.0

    async def start(self):
        """Start the pub/sub listener as a background task."""
        self._listener_task = asyncio.create_task(self._listen())
        logger.info("FaultDetector started")

    async def stop(self):
        """Graceful shutdown."""
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
        for task in self._debounce_tasks.values():
            task.cancel()
        logger.info("FaultDetector stopped")

    async def _listen(self):
        pubsub = self.redis.pubsub()
        await pubsub.subscribe("pole_state_changes")
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        await self._on_pole_state_change(data)
                    except Exception as e:
                        logger.error(f"Error processing pole state change: {e}", exc_info=True)
        except asyncio.CancelledError:
            await pubsub.unsubscribe("pole_state_changes")
            await pubsub.close()

    async def _on_pole_state_change(self, message: dict):
        """Called for each pole state change. Starts/extends debounce window."""
        event = message.get("event")
        if event != "power_lost":
            return

        pole_id = message.get("pole_id")
        if not pole_id:
            return
            
        dt_id = self.topology.pole_to_dt.get(pole_id)
        if not dt_id:
            return

        if dt_id in self._debounce_tasks:
            self._debounce_tasks[dt_id].cancel()
        
        self._debounce_tasks[dt_id] = asyncio.create_task(self._debounce_timer(dt_id))

    async def _debounce_timer(self, dt_id: str):
        try:
            await asyncio.sleep(self.debounce_seconds)
            # Remove from dict before executing so subsequent faults restart timer
            self._debounce_tasks.pop(dt_id, None)
            await self._analyze_dt(dt_id)
        except asyncio.CancelledError:
            pass

    async def _analyze_dt(self, dt_id: str):
        """Called after debounce window. Runs the full detection algorithm for one DT."""
        logger.info(f"Analyzing DT {dt_id} for faults")
        poles = self.topology.get_poles_for_dt(dt_id)
        if not poles:
            return

        # Query Redis for the current state of ALL poles under that DT
        pole_states: Dict[str, bool] = {}
        # We can pipeline for performance
        pipe = self.redis.pipeline()
        for p in poles:
            pipe.hget(f"pole:{p.pole_id}", "energized")
        results = await pipe.execute()
        
        for p, res in zip(poles, results):
            # None means state unknown (e.g. no device), True="1", False="0"
            if res is not None:
                pole_states[p.pole_id] = (res == "1")
                
        # Check Feeder Fault first (Case C)
        feeder_id = poles[0].feeder_id
        is_feeder_fault = await self._analyze_feeder(feeder_id)
        if is_feeder_fault:
            return

        # Handle sensor issues (Case D)
        dead_sensors = await self._detect_dead_sensors(dt_id, pole_states)
        for ds in dead_sensors:
            logger.warning(f"Sensor issue detected for pole {ds}")
            await self.redis.set(f"pole:{ds}:sensor_suspect", "true")
            
        # Treat suspect sensors as 'unknown' so they don't break boundary logic
        for ds in dead_sensors:
            if ds in pole_states:
                del pole_states[ds]

        all_known_dark = all(not state for pid, state in pole_states.items() if pid in pole_states)
        any_known_live = any(state for pid, state in pole_states.items() if pid in pole_states)

        # Case B - DT fault: ALL poles under the DT are dark (or have no device and neighbors are dark), and none are live.
        if all_known_dark and not any_known_live and len(pole_states) > 0:
            dt_node = self.topology.transformers.get(dt_id)
            if dt_node:
                total_poles = dt_node.total_poles
                fault_info = {
                    "fault_type": FaultType.dt,
                    "fault_location_description": f"Distribution Transformer {dt_id} is down",
                    "lat": dt_node.lat,
                    "lon": dt_node.lon,
                    "pincode": poles[0].pincode if poles else None,
                    "affected_pole_ids": [p.pole_id for p in poles],
                    "upstream_pole_id": None,
                    "downstream_pole_id": None,
                    "dt_id": dt_id,
                    "feeder_id": dt_node.feeder_id,
                    "affected_downstream_count": total_poles,
                    "confidence": 0.85,
                    "confidence_reason": f"All {len(pole_states)} reporting sensors under DT {dt_id} are dark.",
                    "topology_source": TopologySource(dt_node.topology_source)
                }
                await self._create_ticket(fault_info)
            return

        # Case A - Span fault: Some live, some dark
        boundaries = await self._find_fault_boundaries(dt_id, pole_states)
        for b in boundaries:
            dt_node = self.topology.transformers.get(dt_id)
            affected_ids = self.topology.get_downstream_poles(b.downstream_pole_id)
            affected_ids.insert(0, b.downstream_pole_id)
            
            fault_info = {
                "fault_type": FaultType.span,
                "fault_location_description": f"Fault between {b.upstream_pole_id} and {b.downstream_pole_id}",
                "lat": b.lat,
                "lon": b.lon,
                "pincode": b.pincode,
                "affected_pole_ids": affected_ids,
                "upstream_pole_id": b.upstream_pole_id,
                "downstream_pole_id": b.downstream_pole_id,
                "dt_id": dt_id,
                "feeder_id": dt_node.feeder_id if dt_node else None,
                "affected_downstream_count": b.affected_count,
                "confidence": b.confidence,
                "confidence_reason": b.confidence_reason,
                "topology_source": TopologySource(b.topology_source)
            }
            await self._create_ticket(fault_info)

    async def _analyze_feeder(self, feeder_id: str) -> bool:
        """Check if all DTs on a feeder are dark → feeder-level fault."""
        dts = self.topology.feeder_dts.get(feeder_id, [])
        if not dts:
            return False

        pipe = self.redis.pipeline()
        for dt_id in dts:
            poles = self.topology.get_poles_for_dt(dt_id)
            for p in poles:
                pipe.hget(f"pole:{p.pole_id}", "energized")
                
        results = await pipe.execute()
        
        any_live = False
        has_any_telemetry = False
        
        for res in results:
            if res is not None:
                has_any_telemetry = True
                if res == "1":
                    any_live = True
                    break
                    
        if any_live or not has_any_telemetry:
            return False

        # All reporting poles on the feeder are dark -> feeder fault
        dt_node = self.topology.transformers.get(dts[0])
        
        feeder_poles = self.topology.get_poles_for_feeder(feeder_id)
        affected_ids = [p.pole_id for p in feeder_poles]
        
        fault_info = {
            "fault_type": FaultType.feeder,
            "fault_location_description": f"Feeder {feeder_id} is down",
            "lat": dt_node.lat if dt_node else 0.0,
            "lon": dt_node.lon if dt_node else 0.0,
            "pincode": dt_node.poles[dt_node.root_poles[0]].pincode if dt_node and dt_node.root_poles else None,
            "affected_pole_ids": affected_ids,
            "upstream_pole_id": None,
            "downstream_pole_id": None,
            "dt_id": None,
            "feeder_id": feeder_id,
            "affected_downstream_count": len(feeder_poles),
            "confidence": 0.95,
            "confidence_reason": f"All reporting sensors across {len(dts)} DTs on feeder {feeder_id} are dark.",
            "topology_source": TopologySource.known
        }
        await self._create_ticket(fault_info)
        return True

    async def _find_fault_boundaries(self, dt_id: str, pole_states: Dict[str, bool]) -> List[FaultBoundary]:
        """Walk the tree and find live→dark boundary edges."""
        boundaries = []
        dt_node = self.topology.transformers.get(dt_id)
        if not dt_node:
            return boundaries

        def find_last_known_state(current_id: str, default_state: bool) -> Tuple[bool, str]:
            """Returns (is_live, last_known_pole_id) by looking upwards."""
            curr = current_id
            while curr is not None:
                if curr in pole_states:
                    return pole_states[curr], curr
                node = self.topology.poles.get(curr)
                if not node:
                    break
                curr = node.parent_id
            return default_state, dt_id

        visited = set()
        queue = list(dt_node.root_poles)
        
        while queue:
            pid = queue.pop(0)
            if pid in visited:
                continue
            visited.add(pid)
            
            node = self.topology.poles.get(pid)
            if not node:
                continue
                
            queue.extend(node.children)
            
            if pid in pole_states and not pole_states[pid]:
                is_live, last_live_pid = find_last_known_state(node.parent_id, True)
                if is_live:
                    last_live_node = self.topology.poles.get(last_live_pid)
                    
                    if last_live_node:
                        lat_mid = (last_live_node.lat + node.lat) / 2.0
                        lon_mid = (last_live_node.lon + node.lon) / 2.0
                    else:
                        # Fallback if last_live_pid is the DT (not a pole in self.topology.poles)
                        lat_mid = (dt_node.lat + node.lat) / 2.0
                        lon_mid = (dt_node.lon + node.lon) / 2.0
                        
                    downstream_count = len(self.topology.get_downstream_poles(pid)) + 1
                    
                    top_src = node.topology_source
                    last_live_src = last_live_node.topology_source if last_live_node else "known"
                    
                    if last_live_src == "inferred" or top_src == "inferred":
                        conf = 0.6
                        reason = f"Boundary on inferred topology between {last_live_pid} and {pid} — wiring order may be approximate."
                    else:
                        conf = 0.9
                        reason = f"Boundary detected between live {last_live_pid} and dark {pid} on known topology."
                        
                    path = self.topology.get_upstream_path(pid)
                    missing_devices = []
                    for path_pid in path:
                        if path_pid == last_live_pid:
                            break
                        if path_pid != pid and path_pid not in pole_states:
                            missing_devices.append(path_pid)
                            
                    if missing_devices:
                        reason = f"Fault between {last_live_pid} and {pid} ({', '.join(missing_devices)} have no sensor/unknown state)."
                        
                    boundaries.append(
                        FaultBoundary(
                            upstream_pole_id=last_live_pid,
                            downstream_pole_id=pid,
                            lat=lat_mid,
                            lon=lon_mid,
                            pincode=node.pincode,
                            affected_count=downstream_count,
                            confidence=conf,
                            confidence_reason=reason,
                            topology_source=top_src
                        )
                    )
                    for child in self.topology.get_downstream_poles(pid):
                        visited.add(child)

        return boundaries

    async def _detect_dead_sensors(self, dt_id: str, pole_states: Dict[str, bool]) -> List[str]:
        """Find poles that are dark but have live children → sensor issues."""
        dead_sensors = []
        for pid, is_live in pole_states.items():
            if not is_live:
                downstream = self.topology.get_downstream_poles(pid)
                for child in downstream:
                    if child in pole_states and pole_states[child]:
                        dead_sensors.append(pid)
                        break
        return dead_sensors

    async def _create_ticket(self, fault_info: dict) -> Optional[Ticket]:
        """Insert ticket into DB, publish to Redis."""
        async with self.db_session_factory() as session:
            stmt = select(Ticket).where(Ticket.status != TicketStatus.closed)
            
            if fault_info["fault_type"] == FaultType.span:
                stmt = stmt.where(
                    and_(
                        Ticket.upstream_pole_id == fault_info["upstream_pole_id"],
                        Ticket.downstream_pole_id == fault_info["downstream_pole_id"]
                    )
                )
            elif fault_info["fault_type"] == FaultType.dt:
                stmt = stmt.where(Ticket.dt_id == fault_info["dt_id"])
            elif fault_info["fault_type"] == FaultType.feeder:
                stmt = stmt.where(Ticket.feeder_id == fault_info["feeder_id"])
                
            result = await session.execute(stmt)
            existing_ticket = result.scalars().first()
            
            if existing_ticket:
                existing_ticket.affected_downstream_count = fault_info["affected_downstream_count"]
                existing_ticket.confidence = fault_info["confidence"]
                existing_ticket.confidence_reason = fault_info["confidence_reason"]
                await session.commit()
                await session.refresh(existing_ticket)
                ticket = existing_ticket
            else:
                ticket = Ticket(**fault_info)
                session.add(ticket)
                await session.commit()
                await session.refresh(ticket)
                
            ticket_dict = {
                "id": ticket.id,
                "fault_type": ticket.fault_type.value,
                "status": ticket.status.value,
                "fault_location_description": ticket.fault_location_description,
                "lat": ticket.lat,
                "lon": ticket.lon,
                "pincode": ticket.pincode,
                "dt_id": ticket.dt_id,
                "feeder_id": ticket.feeder_id,
                "detected_at": ticket.detected_at.isoformat() if ticket.detected_at else None
            }
            await self.redis.publish("new_tickets", json.dumps(ticket_dict))
            return ticket
