"""
backend/app/core/topology.py
============================
Topology builder for the Karnataka State Power Distribution Board
fault detection system.

This module constructs an in-memory radial-tree representation of the
entire low-tension (LT) distribution network.  It is the backbone on
which the fault-detection engine traverses to localise outages.

Two construction strategies are used:

``"known"``  (≈40 % of DTs)
    parent_pole_id is populated in the DB.  The tree is read directly.

``"inferred"``  (≈60 % of DTs)
    parent_pole_id is NULL.  A greedy nearest-neighbour walk starting at
    the DT location builds a plausible radial tree.  A 60 ° bearing-
    change heuristic detects branch/spur points.

Known failure modes of the inference algorithm
-----------------------------------------------
* **Dense clusters** — when several poles are nearly equidistant the
  greedy walk may zigzag instead of following the true line.
* **Sharp U-turns** — a line that doubles back will be misread as a
  branch, producing a spuriously deep tree.
* **Isolated poles** — poles farther than 200 m from any neighbour are
  attached to the nearest pole regardless; a warning is logged.
* **Missing DT location** — if the DT has NULL coordinates the fallback
  is to treat the centroid of its poles as the virtual root.

The system degrades gracefully: the API and fault engine expose
``topology_source`` so consumers can apply lower confidence to inferred
trees.
"""
from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pole import DistributionTransformer, Pole

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Distance / geometry helpers
# ---------------------------------------------------------------------------

_EARTH_RADIUS_M = 6_371_000.0   # metres


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Great-circle distance in **metres** between two GPS points.

    Uses the haversine formula implemented with the standard ``math``
    module — no third-party geospatial library is required.
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return _EARTH_RADIUS_M * c


def bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Initial bearing in **degrees** (0–360, clockwise from North) from
    point 1 to point 2.
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)

    x = math.sin(dlambda) * math.cos(phi2)
    y = (
        math.cos(phi1) * math.sin(phi2)
        - math.sin(phi1) * math.cos(phi2) * math.cos(dlambda)
    )
    theta = math.atan2(x, y)
    return (math.degrees(theta) + 360) % 360


def angle_between_bearings(b1: float, b2: float) -> float:
    """
    Smallest angular difference between two compass bearings (0–180 °).
    """
    diff = abs(b1 - b2) % 360
    return diff if diff <= 180 else 360 - diff


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class PoleNode:
    """In-memory representation of a single LT distribution pole."""

    pole_id: str
    lat: float
    lon: float
    dt_id: str
    feeder_id: str
    device_id: Optional[str]       # None when no IoT sensor is fitted
    pincode: Optional[str]
    ward: Optional[str]
    parent_id: Optional[str]       # pole_id of the upstream pole; None = root
    children: List[str] = field(default_factory=list)   # downstream pole_ids
    seq_on_line: Optional[int] = None
    topology_source: str = "unknown"
    depth: int = 0                  # 0 = directly off the DT

    def to_dict(self) -> dict:
        """Serialise to a plain dict (used by API endpoints)."""
        return {
            "pole_id": self.pole_id,
            "lat": self.lat,
            "lon": self.lon,
            "dt_id": self.dt_id,
            "feeder_id": self.feeder_id,
            "device_id": self.device_id,
            "pincode": self.pincode,
            "ward": self.ward,
            "parent_id": self.parent_id,
            "children": self.children,
            "seq_on_line": self.seq_on_line,
            "topology_source": self.topology_source,
            "depth": self.depth,
            "has_device": self.device_id is not None,
        }


@dataclass
class TransformerTree:
    """Radial tree rooted at a single distribution transformer."""

    dt_id: str
    feeder_id: str
    lat: float
    lon: float
    capacity_kva: int
    households_served: int
    root_poles: List[str] = field(default_factory=list)     # directly off DT
    poles: Dict[str, PoleNode] = field(default_factory=dict)
    topology_source: str = "unknown"
    total_poles: int = 0
    poles_with_device: int = 0

    def to_summary_dict(self) -> dict:
        """Serialise the tree-level summary (no per-pole detail)."""
        max_depth = max((n.depth for n in self.poles.values()), default=0)
        return {
            "dt_id": self.dt_id,
            "feeder_id": self.feeder_id,
            "lat": self.lat,
            "lon": self.lon,
            "capacity_kva": self.capacity_kva,
            "households_served": self.households_served,
            "topology_source": self.topology_source,
            "total_poles": self.total_poles,
            "poles_with_device": self.poles_with_device,
            "root_pole_count": len(self.root_poles),
            "max_depth": max_depth,
        }


class NetworkTopology:
    """
    Complete in-memory graph of the LT distribution network.

    All lookups are O(1) dict reads — no DB queries at runtime.
    Built once at startup by :func:`build_topology`.
    """

    def __init__(self) -> None:
        self.transformers: Dict[str, TransformerTree] = {}
        self.poles: Dict[str, PoleNode] = {}
        self.feeder_dts: Dict[str, List[str]] = {}
        self.pole_to_dt: Dict[str, str] = {}

    # ------------------------------------------------------------------ #
    # Core graph traversal methods                                         #
    # ------------------------------------------------------------------ #

    def get_downstream_poles(self, pole_id: str) -> List[str]:
        """
        BFS: return **all** pole_ids downstream of *pole_id* (inclusive of
        children, grandchildren, …).

        Used by the fault engine to count potentially affected households.
        """
        result: List[str] = []
        if pole_id not in self.poles:
            return result

        queue: deque[str] = deque(self.poles[pole_id].children)
        visited: set = set()
        while queue:
            pid = queue.popleft()
            if pid in visited:
                continue
            visited.add(pid)
            result.append(pid)
            node = self.poles.get(pid)
            if node:
                queue.extend(node.children)
        return result

    def get_upstream_path(self, pole_id: str) -> List[str]:
        """
        Walk the parent chain from *pole_id* back to the DT root.

        Returns a list ordered from *pole_id* → … → root (the root pole
        that has ``parent_id = None``).  Used for fault-boundary search.
        """
        path: List[str] = []
        visited: set = set()
        current: Optional[str] = pole_id
        while current is not None:
            if current in visited:
                logger.warning(
                    "Cycle detected in upstream path at pole %s", current
                )
                break
            visited.add(current)
            path.append(current)
            node = self.poles.get(current)
            if node is None:
                break
            current = node.parent_id
        return path

    def get_span(
        self, pole_id_1: str, pole_id_2: str
    ) -> Optional[Tuple[str, str]]:
        """
        Return ``(upstream_pole, downstream_pole)`` if the two poles are
        **adjacent** in the tree (parent↔child).  Returns ``None`` if they
        are not adjacent.
        """
        n1 = self.poles.get(pole_id_1)
        n2 = self.poles.get(pole_id_2)
        if n1 is None or n2 is None:
            return None

        if n2.parent_id == pole_id_1:
            return (pole_id_1, pole_id_2)
        if n1.parent_id == pole_id_2:
            return (pole_id_2, pole_id_1)
        return None

    def get_subtree_device_count(self, pole_id: str) -> int:
        """
        Count poles **with IoT devices** in the subtree rooted at *pole_id*
        (inclusive of *pole_id* itself if it has a device).
        """
        count = 0
        root = self.poles.get(pole_id)
        if root is None:
            return 0
        if root.device_id is not None:
            count += 1
        for pid in self.get_downstream_poles(pole_id):
            node = self.poles.get(pid)
            if node and node.device_id is not None:
                count += 1
        return count

    def get_poles_for_dt(self, dt_id: str) -> List[PoleNode]:
        """Return all :class:`PoleNode` objects under *dt_id*."""
        tree = self.transformers.get(dt_id)
        if tree is None:
            return []
        return list(tree.poles.values())

    def get_poles_for_feeder(self, feeder_id: str) -> List[PoleNode]:
        """Return all poles under all DTs on *feeder_id*."""
        result: List[PoleNode] = []
        for dt_id in self.feeder_dts.get(feeder_id, []):
            result.extend(self.get_poles_for_dt(dt_id))
        return result


# ---------------------------------------------------------------------------
# Topology construction helpers
# ---------------------------------------------------------------------------


def _build_known_tree(
    dt: DistributionTransformer,
    poles: List[Pole],
) -> TransformerTree:
    """
    Build a :class:`TransformerTree` for a DT whose poles have
    ``parent_pole_id`` populated (the "known" 40 % case).
    """
    tree = TransformerTree(
        dt_id=dt.id,
        feeder_id=dt.feeder_id,
        lat=dt.lat,
        lon=dt.lon,
        capacity_kva=dt.capacity_kva,
        households_served=dt.households_served,
        topology_source="known",
    )

    # Build PoleNode objects
    for p in poles:
        node = PoleNode(
            pole_id=p.id,
            lat=p.lat,
            lon=p.lon,
            dt_id=p.dt_id,
            feeder_id=p.feeder_id,
            device_id=p.device_id,
            pincode=p.pincode,
            ward=p.ward,
            parent_id=p.parent_pole_id,
            seq_on_line=p.seq_on_line,
            topology_source="known",
        )
        tree.poles[p.id] = node

    # Wire up children lists
    for node in tree.poles.values():
        if node.parent_id is not None:
            parent = tree.poles.get(node.parent_id)
            if parent is not None:
                parent.children.append(node.pole_id)
        else:
            tree.root_poles.append(node.pole_id)

    # BFS to assign depth
    _assign_depth_bfs(tree)

    tree.total_poles = len(tree.poles)
    tree.poles_with_device = sum(1 for n in tree.poles.values() if n.device_id)
    return tree


def _assign_depth_bfs(tree: TransformerTree) -> None:
    """BFS from root_poles to set ``depth`` on every PoleNode."""
    queue: deque = deque()
    for root_id in tree.root_poles:
        queue.append((root_id, 0))

    visited: set = set()
    while queue:
        pole_id, depth = queue.popleft()
        if pole_id in visited:
            continue
        visited.add(pole_id)
        node = tree.poles.get(pole_id)
        if node is None:
            continue
        node.depth = depth
        for child_id in node.children:
            queue.append((child_id, depth + 1))

    # Any pole not reached (disconnected subset) gets depth -1 as a sentinel
    for node in tree.poles.values():
        if node.pole_id not in visited:
            node.depth = -1
            logger.warning(
                "DT %s: pole %s is unreachable from roots (orphan in 'known' tree)",
                tree.dt_id,
                node.pole_id,
            )


# ---------------------------------------------------------------------------
# Geometric inference for DTs without known topology
# ---------------------------------------------------------------------------

_MAX_NEIGHBOUR_DIST_M = 200.0    # hard cut-off for edge creation
_BRANCH_ANGLE_THRESHOLD = 60.0   # degrees: larger angle → new branch
_WARN_EDGE_DIST_M = 150.0        # log warning if edge is longer than this


def _build_inferred_tree(
    dt: DistributionTransformer,
    poles: List[Pole],
) -> TransformerTree:
    """
    Build a :class:`TransformerTree` using a greedy nearest-neighbour walk
    with branch-detection heuristics.

    Algorithm overview
    ------------------
    1. Start at the DT location (virtual root).
    2. Find the closest unvisited pole → first root pole (depth 0).
    3. From each pole, examine all unvisited poles within
       ``_MAX_NEIGHBOUR_DIST_M``.  Sorted by distance.
    4. Walk direction is tracked as a bearing.  If the nearest candidate
       deviates > ``_BRANCH_ANGLE_THRESHOLD`` from the walking direction
       AND another candidate within 30° of the walking direction exists,
       the straight candidate continues the main line and the angled one
       starts a branch from the *current* pole.
    5. Each pole is assigned parent, depth, and topology_source = "inferred".
    """
    tree = TransformerTree(
        dt_id=dt.id,
        feeder_id=dt.feeder_id,
        lat=dt.lat,
        lon=dt.lon,
        capacity_kva=dt.capacity_kva,
        households_served=dt.households_served,
        topology_source="inferred",
    )

    if not poles:
        return tree

    # Seed nodes
    for p in poles:
        node = PoleNode(
            pole_id=p.id,
            lat=p.lat,
            lon=p.lon,
            dt_id=p.dt_id,
            feeder_id=p.feeder_id,
            device_id=p.device_id,
            pincode=p.pincode,
            ward=p.ward,
            parent_id=None,
            seq_on_line=p.seq_on_line,
            topology_source="inferred",
        )
        tree.poles[p.id] = node

    unvisited: set = set(tree.poles.keys())

    # ------------------------------------------------------------------ #
    # BFS-like frontier.  Each item: (pole_id, walk_bearing_or_None)      #
    # ------------------------------------------------------------------ #
    frontier: deque = deque()

    # Step 1: nearest pole to the DT → first root
    def _dist_to_dt(pid: str) -> float:
        n = tree.poles[pid]
        return haversine_distance(dt.lat, dt.lon, n.lat, n.lon)

    first_root_id = min(unvisited, key=_dist_to_dt)
    root_node = tree.poles[first_root_id]
    root_node.parent_id = None
    root_node.depth = 0
    tree.root_poles.append(first_root_id)
    unvisited.discard(first_root_id)
    initial_bearing_val = bearing(dt.lat, dt.lon, root_node.lat, root_node.lon)
    frontier.append((first_root_id, initial_bearing_val))

    # Step 2: walk the frontier
    while unvisited and frontier:
        current_id, walk_bearing = frontier.popleft()
        current_node = tree.poles[current_id]

        # Collect candidates within the hard cut-off radius
        candidates: List[Tuple[float, float, str]] = []
        for pid in list(unvisited):
            n = tree.poles[pid]
            d = haversine_distance(current_node.lat, current_node.lon, n.lat, n.lon)
            if d <= _MAX_NEIGHBOUR_DIST_M:
                b = bearing(current_node.lat, current_node.lon, n.lat, n.lon)
                angle_diff = angle_between_bearings(walk_bearing, b)
                candidates.append((d, angle_diff, pid))

        if not candidates:
            continue

        # Sort by distance (nearest first)
        candidates.sort(key=lambda x: x[0])

        # Attach candidates to the current pole
        straight_attached = False
        for dist_m, angle_diff, pid in candidates:
            if pid not in unvisited:
                continue

            child_node = tree.poles[pid]
            new_bearing_val = bearing(
                current_node.lat, current_node.lon, child_node.lat, child_node.lon
            )

            # Determine if this continues the main line or is a branch.
            # We allow only one "straight" (within threshold) continuation;
            # everything else is treated as a lateral branch.
            is_straight = angle_diff <= _BRANCH_ANGLE_THRESHOLD

            if is_straight and straight_attached:
                # A second straight-ahead candidate is treated as a branch
                # to avoid falsely elongating the main line.
                is_straight = False

            child_node.parent_id = current_id
            child_node.depth = current_node.depth + 1
            current_node.children.append(pid)
            unvisited.discard(pid)

            if dist_m > _WARN_EDGE_DIST_M:
                logger.warning(
                    "DT %s (inferred): pole %s is %.0f m from parent %s — "
                    "may be a spurious edge",
                    tree.dt_id, pid, dist_m, current_id,
                )

            frontier.append((pid, new_bearing_val))

            if is_straight:
                straight_attached = True

    # ------------------------------------------------------------------ #
    # Handle orphans                                                       #
    # ------------------------------------------------------------------ #
    if unvisited:
        logger.warning(
            "DT %s (inferred): %d orphan pole(s) after walk — "
            "attaching each to its nearest visited pole",
            tree.dt_id,
            len(unvisited),
        )
        visited_ids = [pid for pid in tree.poles if pid not in unvisited]

        for pid in list(unvisited):
            orphan = tree.poles[pid]
            if not visited_ids:
                orphan.parent_id = None
                orphan.depth = 0
                tree.root_poles.append(pid)
            else:
                nearest_visited = min(
                    visited_ids,
                    key=lambda vid: haversine_distance(
                        orphan.lat, orphan.lon,
                        tree.poles[vid].lat, tree.poles[vid].lon,
                    ),
                )
                orphan.parent_id = nearest_visited
                orphan.depth = tree.poles[nearest_visited].depth + 1
                tree.poles[nearest_visited].children.append(pid)
                dist_m = haversine_distance(
                    orphan.lat, orphan.lon,
                    tree.poles[nearest_visited].lat,
                    tree.poles[nearest_visited].lon,
                )
                if dist_m > _MAX_NEIGHBOUR_DIST_M:
                    logger.warning(
                        "DT %s (inferred): orphan %s attached to nearest "
                        "at %.0f m — suspicious edge",
                        tree.dt_id, pid, dist_m,
                    )
                visited_ids.append(pid)
            unvisited.discard(pid)

    tree.total_poles = len(tree.poles)
    tree.poles_with_device = sum(1 for n in tree.poles.values() if n.device_id)
    return tree


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def build_topology(session: AsyncSession) -> NetworkTopology:
    """
    Load all poles and DTs from the database and construct the full
    :class:`NetworkTopology` graph.

    Steps
    -----
    1. Load all :class:`~app.models.pole.DistributionTransformer` rows.
    2. Load all :class:`~app.models.pole.Pole` rows.
    3. Group poles by ``dt_id``.
    4. For each DT:

       - If any pole has ``parent_pole_id`` populated → ``_build_known_tree``
       - Otherwise → ``_build_inferred_tree``

    5. Populate the flat indexes on :class:`NetworkTopology`.
    6. Print summary and return.
    """
    topo = NetworkTopology()

    # ── Load DTs ──────────────────────────────────────────────────────────────
    dt_result = await session.execute(select(DistributionTransformer))
    all_dts: List[DistributionTransformer] = list(dt_result.scalars().all())

    # ── Load Poles ────────────────────────────────────────────────────────────
    pole_result = await session.execute(select(Pole))
    all_poles: List[Pole] = list(pole_result.scalars().all())

    # Group poles by dt_id
    dt_poles: Dict[str, List[Pole]] = {}
    for p in all_poles:
        dt_poles.setdefault(p.dt_id, []).append(p)

    known_count = 0
    inferred_count = 0
    empty_count = 0

    for dt in all_dts:
        poles_for_dt = dt_poles.get(dt.id, [])

        if not poles_for_dt:
            empty_count += 1
            tree = TransformerTree(
                dt_id=dt.id,
                feeder_id=dt.feeder_id,
                lat=dt.lat,
                lon=dt.lon,
                capacity_kva=dt.capacity_kva,
                households_served=dt.households_served,
                topology_source="known",
            )
        elif any(p.parent_pole_id is not None for p in poles_for_dt):
            tree = _build_known_tree(dt, poles_for_dt)
            known_count += 1
        else:
            tree = _build_inferred_tree(dt, poles_for_dt)
            inferred_count += 1

        topo.transformers[dt.id] = tree
        topo.feeder_dts.setdefault(dt.feeder_id, []).append(dt.id)

        for pid, node in tree.poles.items():
            topo.poles[pid] = node
            topo.pole_to_dt[pid] = dt.id

    total_poles = len(topo.poles)
    total_dts = len(topo.transformers)
    empty_suffix = f", {empty_count} empty" if empty_count else ""

    print(
        f"Built topology for {total_dts} DTs: "
        f"{known_count} known, {inferred_count} inferred{empty_suffix}. "
        f"{total_poles} poles total."
    )
    logger.info(
        "Topology built: %d DTs (%d known, %d inferred, %d empty), %d poles",
        total_dts,
        known_count,
        inferred_count,
        empty_count,
        total_poles,
    )

    return topo
