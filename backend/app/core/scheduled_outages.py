import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional


@dataclass
class ScheduledOutage:
    id: str                    # e.g. "SO-2026-07-29-014"
    scope: str                 # "feeder" or "dt"
    target_id: str             # feeder_id or dt_id
    start: datetime            # planned start (UTC)
    end: datetime              # planned end (UTC)
    reason: str                # e.g. "Load shedding", "Planned maintenance"


class ScheduledOutageManager:
    def __init__(self):
        self._outages: List[ScheduledOutage] = []

    def add_outage(self, outage: ScheduledOutage):
        """Add a scheduled outage (called from simulator or API)."""
        self._outages.append(outage)

    def remove_outage(self, outage_id: str):
        """Remove/cancel a scheduled outage."""
        self._outages = [o for o in self._outages if o.id != outage_id]

    def get_active_outages(self, at_time: Optional[datetime] = None) -> List[ScheduledOutage]:
        """Return outages active at the given time (default: now) including buffer."""
        if at_time is None:
            at_time = datetime.now(timezone.utc)
            
        active = []
        for o in self._outages:
            start_buffer = o.start - timedelta(minutes=40)
            end_buffer = o.end + timedelta(minutes=40)
            if start_buffer <= at_time <= end_buffer:
                active.append(o)
        return active

    def is_under_scheduled_outage(self, feeder_id: str = None, dt_id: str = None, at_time: Optional[datetime] = None) -> bool:
        """
        Check if a feeder or DT is currently under a scheduled outage.
        """
        if at_time is None:
            at_time = datetime.now(timezone.utc)
            
        for o in self._outages:
            start_buffer = o.start - timedelta(minutes=40)
            end_buffer = o.end + timedelta(minutes=40)
            
            if start_buffer <= at_time <= end_buffer:
                if dt_id and o.scope == "dt" and o.target_id == dt_id:
                    return True
                if feeder_id and o.scope == "feeder" and o.target_id == feeder_id:
                    return True
                    
        return False

    def get_outages_for_target(self, target_id: str) -> List[ScheduledOutage]:
        """Get all scheduled outages (past, present, future) for a target."""
        return [o for o in self._outages if o.target_id == target_id]

    def seed_sample_outages(self, feeder_ids: List[str], dt_ids: List[str]):
        """
        Create some sample scheduled outages for demo/testing:
        - 2-3 feeder-level load shedding windows (2-3 hours each)
        - 3-4 DT-level maintenance windows (1-2 hours each)
        - Spread across the next 24 hours
        """
        now = datetime.now(timezone.utc)
        
        # Seed feeder outages
        num_feeders = min(random.randint(2, 3), len(feeder_ids))
        if num_feeders > 0:
            selected_feeders = random.sample(feeder_ids, num_feeders)
            for i, fid in enumerate(selected_feeders):
                start = now + timedelta(hours=random.randint(1, 20))
                end = start + timedelta(hours=random.randint(2, 3))
                self.add_outage(ScheduledOutage(
                    id=f"SO-FEEDER-{now.strftime('%Y%m%d')}-{i}",
                    scope="feeder",
                    target_id=fid,
                    start=start,
                    end=end,
                    reason="Load shedding"
                ))

        # Seed DT outages
        num_dts = min(random.randint(3, 4), len(dt_ids))
        if num_dts > 0:
            selected_dts = random.sample(dt_ids, num_dts)
            for i, dtid in enumerate(selected_dts):
                start = now + timedelta(hours=random.randint(1, 20))
                end = start + timedelta(hours=random.randint(1, 2))
                self.add_outage(ScheduledOutage(
                    id=f"SO-DT-{now.strftime('%Y%m%d')}-{i}",
                    scope="dt",
                    target_id=dtid,
                    start=start,
                    end=end,
                    reason="Planned maintenance"
                ))
