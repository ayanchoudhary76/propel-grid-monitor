"""
Synthetic power distribution network generator for the KSPDCL Fault Detection System.

Generates a realistic LT/11 kV distribution network for a Bangalore sub-division:
  4 substations (66/11 kV)
  → ~30 feeders
  → ~54 distribution transformers
  → ~3 000–4 000 LT poles (radial trees with branches)

Design note — two-pass pole insert:
  Pole.parent_pole_id is a self-referential FK.  To avoid row-level FK
  violations during bulk insert (PostgreSQL checks FKs per-statement by
  default) we insert all poles with parent_pole_id = NULL first, then
  execute a single bulk UPDATE via a VALUES clause.

Topology split:
  ~40 % of DTs have full topology (seq_on_line + parent_pole_id).
  ~60 % have poles with correct lat/lon but no wiring order.
"""
from __future__ import annotations

import asyncio
import math
import random
from typing import Dict, List, Optional, Tuple

from sqlalchemy import select, text

from app.database import AsyncSessionLocal, create_tables
from app.models.pole import (
    DistributionTransformer,
    Feeder,
    Pole,
    Substation,
)

# ── Static configuration ───────────────────────────────────────────────────────

SUBSTATION_CONFIGS: List[Dict] = [
    {
        "name": "Rajajinagar 66/11 kV Substation",
        "lat": 12.9900,
        "lon": 77.5530,
    },
    {
        "name": "Malleshwaram 66/11 kV Substation",
        "lat": 12.9760,
        "lon": 77.5630,
    },
    {
        "name": "Basavanagudi 66/11 kV Substation",
        "lat": 12.9300,
        "lon": 77.5750,
    },
    {
        "name": "BTM Layout 66/11 kV Substation",
        "lat": 12.9120,
        "lon": 77.6080,
    },
]

# Feeders per substation (total = 30)
FEEDER_COUNTS_PER_SS = [7, 8, 8, 7]

POLE_TYPES = ["LT-9m-PCC", "LT-8m-Steel", "LT-10m-PCC", "LT-8m-PCC"]
DT_CAPACITIES = [100, 160, 200, 250, 315, 500]
PINCODES: List[int] = list(range(560001, 560101))

# Step size in degrees: 30–50 m  (1° ≈ 111 km)
STEP_MIN = 0.00027   # ≈ 30 m
STEP_MAX = 0.00045   # ≈ 50 m

# DT offset from parent substation: 0.002–0.01°  (≈ 220 m – 1.1 km)
DT_OFFSET_MIN = 0.002
DT_OFFSET_MAX = 0.010

TOPOLOGY_FRACTION = 0.40   # 40 % of DTs have full topology


# ── Low-level geometry helpers ─────────────────────────────────────────────────

def _walk_step(
    rng: random.Random,
    lat: float,
    lon: float,
    direction_deg: float,
) -> Tuple[float, float, float]:
    """
    Advance one step along a radial walk with small angular noise.

    direction_deg is a compass bearing (0 = North, 90 = East).
    Returns (new_lat, new_lon, new_direction_deg).
    """
    step = rng.uniform(STEP_MIN, STEP_MAX)
    noise = rng.uniform(-8.0, 8.0)
    direction_deg = (direction_deg + noise) % 360.0
    theta = math.radians(direction_deg)
    return lat + step * math.cos(theta), lon + step * math.sin(theta), direction_deg


# ── Pole factory ───────────────────────────────────────────────────────────────

def _make_pole(
    rng: random.Random,
    counter: int,
    dt: DistributionTransformer,
    feeder_id: str,
    ss_num: int,
    lat: float,
    lon: float,
    has_topology: bool,
    seq: Optional[int],
) -> Pole:
    """
    Construct a single Pole ORM object.

    parent_pole_id is always set to None here; the caller is responsible for
    recording the (pole_id → parent_id) mapping and applying it in a second
    bulk-UPDATE pass to avoid self-referential FK constraint violations.
    """
    # 91 % of poles have an IoT device; 9 % are unmonitored
    device_id: Optional[str] = None
    if rng.random() > 0.09:
        device_id = f"KSPDB-SD{ss_num:02d}-{dt.id}-{counter}"

    # 97 % of poles have a pincode; 3 % are in unregistered areas
    pincode: Optional[str] = None
    if rng.random() > 0.03:
        pincode = str(rng.choice(PINCODES))

    ward_num = rng.randint(1, 198)   # BBMP has 198 wards

    return Pole(
        id=f"P-{counter:06d}",
        dt_id=dt.id,
        feeder_id=feeder_id,
        lat=round(lat, 7),
        lon=round(lon, 7),
        seq_on_line=seq,
        parent_pole_id=None,   # set in pass-2 bulk UPDATE
        pole_type=rng.choice(POLE_TYPES),
        has_topology=has_topology,
        ward=f"W-{ward_num:03d}",
        pincode=pincode,
        device_id=device_id,
    )


# ── Per-DT pole generation ─────────────────────────────────────────────────────

def _generate_dt_poles(
    rng: random.Random,
    dt: DistributionTransformer,
    feeder_id: str,
    ss_num: int,
    start_counter: int,
    has_topology: bool,
) -> Tuple[List[Pole], int, Dict[str, str]]:
    """
    Generate all poles for one DT: a main radial line + 1–3 lateral branches.

    Returns
    -------
    poles            : ordered list of Pole objects (parents before children)
    next_counter     : next available global pole counter
    parent_map       : {child_pole_id: parent_pole_id} for topology-enabled DTs
    """
    total_poles = rng.randint(20, 120)
    branch_count = rng.randint(1, 3)
    main_dir = rng.uniform(0.0, 360.0)

    # Reserve some poles for branches; keep at least 5 on the main line
    branch_reserve = min(branch_count * 15, total_poles // 3)
    main_count = max(5, total_poles - branch_reserve)

    poles: List[Pole] = []
    parent_map: Dict[str, str] = {}
    counter = start_counter
    seq = 1

    # ── Main line ──────────────────────────────────────────────────────────────
    lat, lon = dt.lat, dt.lon
    direction = main_dir
    last_main_id: Optional[str] = None   # tracks parent for topology

    for i in range(main_count):
        lat, lon, direction = _walk_step(rng, lat, lon, direction)
        pole_id = f"P-{counter:06d}"

        if has_topology and last_main_id is not None:
            parent_map[pole_id] = last_main_id

        pole = _make_pole(rng, counter, dt, feeder_id, ss_num, lat, lon, has_topology, seq if has_topology else None)
        poles.append(pole)
        last_main_id = pole_id
        counter += 1
        seq += 1

    # ── Branches / lateral spurs ───────────────────────────────────────────────
    remaining = total_poles - main_count

    # Choose branch-point poles from the main line (skip the first 2)
    if remaining > 0 and len(poles) > 3:
        available_bp = poles[2:]
        n_branches = min(branch_count, len(available_bp))
        branch_points = rng.sample(available_bp, n_branches)
        per_branch = max(5, remaining // n_branches)

        for bp in branch_points:
            if remaining <= 0:
                break
            this_len = min(
                rng.randint(5, max(5, per_branch + rng.randint(0, 5))),
                remaining,
            )
            # Lateral direction: 70–120° offset from the main direction
            side = rng.choice([-1, 1])
            b_dir = (main_dir + side * rng.uniform(70.0, 120.0)) % 360.0
            b_lat, b_lon = bp.lat, bp.lon

            # The branch's first pole hangs off the branch-point pole
            prev_branch_id: str = bp.id

            for j in range(this_len):
                b_lat, b_lon, b_dir = _walk_step(rng, b_lat, b_lon, b_dir)
                pole_id = f"P-{counter:06d}"

                if has_topology:
                    parent_map[pole_id] = prev_branch_id
                    prev_branch_id = pole_id

                pole = _make_pole(
                    rng, counter, dt, feeder_id, ss_num,
                    b_lat, b_lon, has_topology,
                    seq if has_topology else None,
                )
                poles.append(pole)
                counter += 1
                seq += 1
                remaining -= 1
                if remaining <= 0:
                    break

    return poles, counter, parent_map


# ── Main seeding function ──────────────────────────────────────────────────────

async def seed_database(seed: int = 42) -> None:
    """
    Populate the database with a synthetic power grid network.

    Idempotent — exits immediately if any Substation rows already exist.

    Parameters
    ----------
    seed : int
        RNG seed for reproducible generation (default 42).
    """
    async with AsyncSessionLocal() as session:
        # ── Idempotency guard ──────────────────────────────────────────────────
        existing = await session.execute(select(Substation).limit(1))
        if existing.scalar_one_or_none() is not None:
            print("Database already seeded — skipping.")
            return

        rng = random.Random(seed)

        # ── 1. Substations ────────────────────────────────────────────────────
        substations: List[Substation] = [
            Substation(name=cfg["name"], lat=cfg["lat"], lon=cfg["lon"])
            for cfg in SUBSTATION_CONFIGS
        ]
        session.add_all(substations)
        await session.flush()   # get auto-increment IDs

        # ── 2. Feeders ────────────────────────────────────────────────────────
        feeders: List[Feeder] = []
        for ss_idx, (ss, f_count) in enumerate(zip(substations, FEEDER_COUNTS_PER_SS)):
            for f_idx in range(f_count):
                feeders.append(Feeder(
                    id=f"F-{ss_idx + 1:02d}-{f_idx + 1:02d}",
                    substation_id=ss.id,
                    name=f"Feeder {f_idx + 1} — {ss.name.split()[0]}",
                ))
        session.add_all(feeders)
        await session.flush()

        # ── 3. Distribution Transformers ──────────────────────────────────────
        # Target ~50–55 DTs across 30 feeders:
        #   f_idx % 5 == 4  → 3 DTs   (6 feeders × 3 = 18)
        #   f_idx % 2 == 0  → 2 DTs   (12 feeders × 2 = 24)
        #   else            → 1 DT    (12 feeders × 1 = 12)
        #                              total ≈ 54 DTs

        dts: List[DistributionTransformer] = []
        dt_counter = 1
        ss_by_id: Dict[int, Tuple[int, Substation]] = {
            ss.id: (i, ss) for i, ss in enumerate(substations)
        }

        for f_idx, feeder in enumerate(feeders):
            if f_idx % 5 == 4:
                dt_in_feeder = 3
            elif f_idx % 2 == 0:
                dt_in_feeder = 2
            else:
                dt_in_feeder = 1

            _, ss = ss_by_id[feeder.substation_id]
            for _ in range(dt_in_feeder):
                d_lat = rng.uniform(DT_OFFSET_MIN, DT_OFFSET_MAX) * rng.choice([-1, 1])
                d_lon = rng.uniform(DT_OFFSET_MIN, DT_OFFSET_MAX) * rng.choice([-1, 1])
                cap = rng.choice(DT_CAPACITIES)
                dts.append(DistributionTransformer(
                    id=f"D-{dt_counter:04d}",
                    feeder_id=feeder.id,
                    lat=round(ss.lat + d_lat, 7),
                    lon=round(ss.lon + d_lon, 7),
                    capacity_kva=cap,
                    households_served=int(cap * rng.uniform(1.0, 1.5)),
                ))
                dt_counter += 1

        session.add_all(dts)
        await session.flush()

        # ── 4. Poles ──────────────────────────────────────────────────────────
        n_dts = len(dts)
        # Randomly choose ~40 % of DTs to have full topology
        topology_dt_indices = set(
            rng.sample(range(n_dts), k=round(n_dts * TOPOLOGY_FRACTION))
        )

        feeder_by_id: Dict[str, Feeder] = {f.id: f for f in feeders}
        ss_num_by_ss_id: Dict[int, int] = {ss.id: i + 1 for i, ss in enumerate(substations)}

        all_poles: List[Pole] = []
        all_parent_map: Dict[str, str] = {}   # child_id -> parent_id (across all DTs)
        pole_counter = 1

        for dt_idx, dt in enumerate(dts):
            has_topology = dt_idx in topology_dt_indices
            feeder = feeder_by_id[dt.feeder_id]
            ss_num = ss_num_by_ss_id[feeder.substation_id]

            dt_poles, pole_counter, parent_map = _generate_dt_poles(
                rng=rng,
                dt=dt,
                feeder_id=dt.feeder_id,
                ss_num=ss_num,
                start_counter=pole_counter,
                has_topology=has_topology,
            )
            all_poles.extend(dt_poles)
            all_parent_map.update(parent_map)

        # Pass 1 — insert all poles with parent_pole_id = NULL
        # (avoids self-referential FK violations on non-deferred constraints)
        BATCH_INSERT = 500
        print(f"  Inserting {len(all_poles)} poles in batches of {BATCH_INSERT}…", flush=True)
        for i in range(0, len(all_poles), BATCH_INSERT):
            session.add_all(all_poles[i : i + BATCH_INSERT])
            await session.flush()

        # Pass 2 — bulk-update parent_pole_id for topology-enabled poles
        if all_parent_map:
            pairs = list(all_parent_map.items())
            BATCH_UPDATE = 300
            print(
                f"  Setting {len(pairs)} parent_pole_id links "
                f"in batches of {BATCH_UPDATE}…",
                flush=True,
            )
            for i in range(0, len(pairs), BATCH_UPDATE):
                batch = pairs[i : i + BATCH_UPDATE]
                # Single SQL statement per batch via VALUES clause
                values_sql = ", ".join(
                    f"('{child_id}', '{parent_id}')" for child_id, parent_id in batch
                )
                await session.execute(text(
                    "UPDATE poles "
                    "SET parent_pole_id = v.parent_id "
                    "FROM (VALUES " + values_sql + ") AS v(pole_id, parent_id) "
                    "WHERE poles.id = v.pole_id"
                ))

        await session.commit()

        # ── Summary ────────────────────────────────────────────────────────────
        topo_poles = sum(1 for p in all_poles if p.has_topology)
        no_topo_poles = len(all_poles) - topo_poles
        topo_dts = len(topology_dt_indices)

        print(
            f"✓ Created {len(substations)} substations, "
            f"{len(feeders)} feeders, "
            f"{len(dts)} DTs ({topo_dts} with topology, {n_dts - topo_dts} without), "
            f"{len(all_poles)} poles "
            f"({topo_poles} with topology, {no_topo_poles} without)"
        )


# ── Standalone entry point ─────────────────────────────────────────────────────

if __name__ == "__main__":
    async def _main() -> None:
        print("KSPDCL Network Seed — connecting to database…")
        await create_tables()
        await seed_database()
        print("Done.")

    asyncio.run(_main())
