import asyncio
import logging
import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from app.api.ingest import TelemetryPayload, ingest_batch
from app.core.scheduled_outages import ScheduledOutageManager
from app.core.topology import NetworkTopology, PoleNode
from app.database import AsyncSessionLocal
from app.models.telemetry import EventType

logger = logging.getLogger(__name__)


@dataclass
class SimulatedFault:
    fault_id: str
    fault_type: str
    target_description: str
    affected_pole_ids: List[str]
    affected_poles_with_device: int
    telemetry_sent: int
    telemetry_suppressed: int
    injected_at: datetime


class FaultSimulator:
    def __init__(self, topology: NetworkTopology, redis_client, outage_manager: ScheduledOutageManager):
        self.topology = topology
        self.redis = redis_client
        self.outage_manager = outage_manager
        self.active_faults: Dict[str, SimulatedFault] = {}
        self._seq_counters: Dict[str, int] = {}
        self.rng = random.Random(42)  # For reproducible jitter/skew

    def _next_seq(self, device_id: str) -> int:
        self._seq_counters[device_id] = self._seq_counters.get(device_id, 1000) + 1
        return self._seq_counters[device_id]

    def _get_fw(self, device_id: str) -> str:
        # ~8% are fw 1.2.x, else 1.3.x
        if hash(device_id) % 100 < 8:
            return "1.2.0"
        return "1.3.1"

    async def _send_batch(self, payloads: List[TelemetryPayload]):
        if not payloads:
            return
        async with AsyncSessionLocal() as db:
            await ingest_batch(payloads=payloads, db=db, redis=self.redis)

    async def _generate_telemetry(
        self, affected_poles: List[PoleNode], is_restoration: bool = False
    ) -> Tuple[int, int]:
        """
        Generate telemetry for affected poles and send it.
        Returns (telemetry_sent, telemetry_suppressed).
        """
        payloads: List[TelemetryPayload] = []
        sent = 0
        suppressed = 0
        now = datetime.now(timezone.utc)

        for pole in affected_poles:
            if not pole.device_id:
                continue

            fw = self._get_fw(pole.device_id)
            skew = timedelta(seconds=self.rng.randint(-90, 90))
            jitter = timedelta(seconds=self.rng.uniform(0, 5))
            event_time = now + skew + jitter

            if is_restoration:
                # Restoration: Boot -> Power Restored
                boot_time = event_time
                restored_time = event_time + timedelta(seconds=self.rng.uniform(15, 25))

                payloads.append(TelemetryPayload(
                    device_id=pole.device_id,
                    pole_id=pole.pole_id,
                    event=EventType.boot,
                    energized=True,
                    ts=boot_time,
                    seq=self._next_seq(pole.device_id),
                    battery_mv=self.rng.randint(3500, 4200),
                    rssi=self.rng.randint(-90, -50),
                    fw=fw
                ))
                payloads.append(TelemetryPayload(
                    device_id=pole.device_id,
                    pole_id=pole.pole_id,
                    event=EventType.power_restored,
                    energized=True,
                    ts=restored_time,
                    seq=self._next_seq(pole.device_id),
                    battery_mv=self.rng.randint(3500, 4200),
                    rssi=self.rng.randint(-90, -50),
                    fw=fw
                ))
                sent += 2
            else:
                # Fault: Power Lost
                if fw.startswith("1.2"):
                    suppressed += 1
                elif self.rng.random() < 0.3:
                    suppressed += 1
                else:
                    payloads.append(TelemetryPayload(
                        device_id=pole.device_id,
                        pole_id=pole.pole_id,
                        event=EventType.power_lost,
                        energized=False,
                        ts=event_time,
                        seq=self._next_seq(pole.device_id),
                        battery_mv=self.rng.randint(3500, 4200),
                        rssi=self.rng.randint(-90, -50),
                        fw=fw
                    ))
                    sent += 1

        await self._send_batch(payloads)
        return sent, suppressed

    async def inject_span_fault(self, pole_id_upstream: str, pole_id_downstream: str) -> SimulatedFault:
        affected_pole_ids = [pole_id_downstream] + self.topology.get_downstream_poles(pole_id_downstream)
        affected_poles = [self.topology.poles[pid] for pid in affected_pole_ids if pid in self.topology.poles]
        
        sent, suppressed = await self._generate_telemetry(affected_poles, is_restoration=False)
        
        fault = SimulatedFault(
            fault_id=str(uuid.uuid4()),
            fault_type="span",
            target_description=f"Span between {pole_id_upstream} and {pole_id_downstream}",
            affected_pole_ids=affected_pole_ids,
            affected_poles_with_device=sum(1 for p in affected_poles if p.device_id),
            telemetry_sent=sent,
            telemetry_suppressed=suppressed,
            injected_at=datetime.now(timezone.utc)
        )
        self.active_faults[fault.fault_id] = fault
        return fault

    async def inject_dt_fault(self, dt_id: str) -> SimulatedFault:
        affected_poles = self.topology.get_poles_for_dt(dt_id)
        affected_pole_ids = [p.pole_id for p in affected_poles]

        sent, suppressed = await self._generate_telemetry(affected_poles, is_restoration=False)

        fault = SimulatedFault(
            fault_id=str(uuid.uuid4()),
            fault_type="dt",
            target_description=f"DT {dt_id}",
            affected_pole_ids=affected_pole_ids,
            affected_poles_with_device=sum(1 for p in affected_poles if p.device_id),
            telemetry_sent=sent,
            telemetry_suppressed=suppressed,
            injected_at=datetime.now(timezone.utc)
        )
        self.active_faults[fault.fault_id] = fault
        return fault

    async def inject_feeder_fault(self, feeder_id: str) -> SimulatedFault:
        affected_poles = self.topology.get_poles_for_feeder(feeder_id)
        affected_pole_ids = [p.pole_id for p in affected_poles]

        sent, suppressed = await self._generate_telemetry(affected_poles, is_restoration=False)

        fault = SimulatedFault(
            fault_id=str(uuid.uuid4()),
            fault_type="feeder",
            target_description=f"Feeder {feeder_id}",
            affected_pole_ids=affected_pole_ids,
            affected_poles_with_device=sum(1 for p in affected_poles if p.device_id),
            telemetry_sent=sent,
            telemetry_suppressed=suppressed,
            injected_at=datetime.now(timezone.utc)
        )
        self.active_faults[fault.fault_id] = fault
        return fault

    async def repair_fault(self, fault_id: str) -> dict:
        if fault_id not in self.active_faults:
            raise ValueError(f"Fault {fault_id} not found.")

        fault = self.active_faults[fault_id]
        affected_poles = [self.topology.poles[pid] for pid in fault.affected_pole_ids if pid in self.topology.poles]
        
        sent, _ = await self._generate_telemetry(affected_poles, is_restoration=True)
        del self.active_faults[fault_id]
        
        return {
            "fault_id": fault_id,
            "telemetry_sent": sent,
            "status": "repaired"
        }

    async def kill_device(self, pole_id: str) -> dict:
        pole = self.topology.poles.get(pole_id)
        if not pole or not pole.device_id:
            raise ValueError(f"Pole {pole_id} not found or has no device.")
        
        # Stop sending heartbeats by marking it dark in Redis directly
        # Wait, the prompt says: "Set the pole's Redis state to dark (stop sending heartbeats)"
        # "But do NOT affect any other poles"
        
        # Let's just update Redis directly, similar to ingest.py, or we can send a power_lost event? 
        # "Simulate a device dying while power is fine. Set the pole's Redis state to dark"
        # If we just delete it from poles:live and add to poles:dark, that works. But wait, if it dies, it shouldn't send power_lost! It should just be moved to dark?
        # Actually, if we just wait, it will become dark eventually. But to force it for the test, maybe we manually update Redis. Or we could just send a power_lost event to trigger dark? But device dying means it doesn't send power_lost. Wait, dead sensor detection detects it if it misses heartbeats, but the prompt says: "Set the pole's Redis state to dark... This should trigger the dead sensor detection (dark pole with live children)".
        
        # Let's set its last_seen to a long time ago in Redis, and maybe the fault detector does the rest?
        # No, the fault detector reads from Redis and expects it to be in `poles:dark` or just `energized=0`? 
        # Let's just push a payload with `energized=False`? But that's power lost. The prompt says "Set the pole's Redis state to dark (stop sending heartbeats)".
        # Let's just hset energized=0 and move it to poles:dark. 
        from app.api.ingest import POLE_HASH_KEY, POLES_LIVE_KEY, POLES_DARK_KEY, STATE_CHANGE_CHANNEL, _build_state_change_event
        
        pipe = self.redis.pipeline(transaction=False)
        pipe.hset(POLE_HASH_KEY.format(pole_id), "energized", "0")
        pipe.sadd(POLES_DARK_KEY, pole_id)
        pipe.srem(POLES_LIVE_KEY, pole_id)
        
        # We need to trigger the state change so the fault detector picks it up.
        now = datetime.now(timezone.utc)
        payload = TelemetryPayload(
            device_id=pole.device_id,
            pole_id=pole_id,
            event=EventType.heartbeat,  # It didn't really happen, but we simulate the effect
            energized=False,
            ts=now,
            seq=self._next_seq(pole.device_id),
            battery_mv=0,
            rssi=-100,
            fw=self._get_fw(pole.device_id)
        )
        msg = _build_state_change_event(payload, new_energized=False)
        pipe.publish(STATE_CHANGE_CHANNEL, msg)
        await pipe.execute()

        return {
            "pole_id": pole_id,
            "expected_behavior": "should NOT create a fault ticket (dead sensor)"
        }

    async def inject_scheduled_outage(self, scope: str, target_id: str, duration_minutes: int = 120, reason: str = "Load shedding") -> dict:
        start_time = datetime.now(timezone.utc) - timedelta(minutes=5)
        end_time = start_time + timedelta(minutes=duration_minutes)
        outage = self.outage_manager.create_outage(
            scope=scope,
            target_id=target_id,
            start_time=start_time,
            end_time=end_time,
            reason=reason
        )

        affected_poles = []
        if scope == "feeder":
            affected_poles = self.topology.get_poles_for_feeder(target_id)
        elif scope == "dt":
            affected_poles = self.topology.get_poles_for_dt(target_id)
        elif scope == "pole":
            pole = self.topology.poles.get(target_id)
            if pole:
                affected_poles = [pole]

        sent, suppressed = await self._generate_telemetry(affected_poles, is_restoration=False)

        return {
            "outage_id": outage.outage_id,
            "telemetry_sent": sent,
            "expected_behavior": "Should NOT create fault tickets because outage manager will suppress them."
        }

    async def inject_duplicate_messages(self, pole_id: str, count: int = 5) -> dict:
        pole = self.topology.poles.get(pole_id)
        if not pole or not pole.device_id:
            raise ValueError(f"Pole {pole_id} not found or has no device.")

        seq = self._next_seq(pole.device_id)
        payload = TelemetryPayload(
            device_id=pole.device_id,
            pole_id=pole_id,
            event=EventType.heartbeat,
            energized=True,
            ts=datetime.now(timezone.utc),
            seq=seq,
            battery_mv=4000,
            rssi=-70,
            fw=self._get_fw(pole.device_id)
        )
        
        # Send same payload multiple times
        await self._send_batch([payload for _ in range(count)])
        
        return {
            "pole_id": pole_id,
            "duplicates_sent": count,
            "expected_behavior": "All but the first should be silently ignored (DB constraint)."
        }

    async def inject_stale_message(self, pole_id: str) -> dict:
        pole = self.topology.poles.get(pole_id)
        if not pole or not pole.device_id:
            raise ValueError(f"Pole {pole_id} not found or has no device.")

        # Ensure current seq is advanced
        current_seq = self._next_seq(pole.device_id)
        # Advance it by sending a normal heartbeat first
        normal = TelemetryPayload(
            device_id=pole.device_id,
            pole_id=pole_id,
            event=EventType.heartbeat,
            energized=True,
            ts=datetime.now(timezone.utc),
            seq=current_seq,
            battery_mv=4000,
            rssi=-70,
            fw=self._get_fw(pole.device_id)
        )
        await self._send_batch([normal])

        stale_seq = current_seq - 5
        stale_payload = TelemetryPayload(
            device_id=pole.device_id,
            pole_id=pole_id,
            event=EventType.power_lost, # trying to trigger fault
            energized=False,
            ts=datetime.now(timezone.utc) - timedelta(hours=1),
            seq=stale_seq,
            battery_mv=4000,
            rssi=-70,
            fw=self._get_fw(pole.device_id)
        )
        await self._send_batch([stale_payload])

        return {
            "pole_id": pole_id,
            "stale_seq_sent": stale_seq,
            "current_seq": current_seq,
            "expected_behavior": "Should be recorded in DB but ignored by Redis (no state change)."
        }

    async def init_all_live(self) -> dict:
        """Send heartbeats for ALL poles with devices to establish baseline."""
        payloads: List[TelemetryPayload] = []
        now = datetime.now(timezone.utc)
        
        for pole in self.topology.poles.values():
            if not pole.device_id:
                continue
            skew = timedelta(seconds=self.rng.randint(-90, 90))
            payloads.append(TelemetryPayload(
                device_id=pole.device_id,
                pole_id=pole.pole_id,
                event=EventType.heartbeat,
                energized=True,
                ts=now + skew,
                seq=self._next_seq(pole.device_id),
                battery_mv=self.rng.randint(3800, 4200),
                rssi=self.rng.randint(-85, -50),
                fw=self._get_fw(pole.device_id)
            ))
            
        # Send in chunks of 500
        for i in range(0, len(payloads), 500):
            await self._send_batch(payloads[i:i+500])
            
        return {
            "poles_initialized": len(payloads),
            "status": "success"
        }

    async def reset(self) -> dict:
        """Repair all faults, clear tickets, reset redis."""
        try:
            for fault_id in list(self.active_faults.keys()):
                await self.repair_fault(fault_id)
                
            async with AsyncSessionLocal() as session:
                from app.models.ticket import Ticket
                from sqlalchemy import delete
                await session.execute(delete(Ticket))
                await session.commit()
                
            # Redis flush in chunks to avoid max-arguments error
            keys_to_del = await self.redis.keys("pole:*") + await self.redis.keys("poles:*")
            if keys_to_del:
                chunk_size = 500
                for i in range(0, len(keys_to_del), chunk_size):
                    await self.redis.delete(*keys_to_del[i:i+chunk_size])
                
            # Clear outage manager
            self.outage_manager.active_outages.clear()
            
            # Reset counters
            self._seq_counters.clear()
            
            return {"status": "reset complete"}
        except Exception as e:
            import traceback
            logger.error(f"Error in reset: {e}")
            logger.error(traceback.format_exc())
            return {"status": "error", "error": str(e)}
