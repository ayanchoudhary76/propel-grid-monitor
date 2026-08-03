"""
SQLAlchemy model for fault tickets with full lifecycle state management.
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class FaultType(str, enum.Enum):
    span = "span"          # Fault in a single wire span between two poles
    dt = "dt"              # Fault at / near the distribution transformer
    feeder = "feeder"      # Feeder-level fault (upstream)
    unknown = "unknown"    # Fault type could not be determined


class TicketStatus(str, enum.Enum):
    detected = "detected"
    acknowledged = "acknowledged"
    crew_assigned = "crew_assigned"
    resolved = "resolved"
    verified = "verified"
    closed = "closed"


class TopologySource(str, enum.Enum):
    known = "known"        # Based on surveyed topology data
    inferred = "inferred"  # Inferred from telemetry patterns


class Ticket(Base):
    """
    A fault ticket created when the fault-detection engine identifies a grid anomaly.

    Lifecycle:
        detected → acknowledged → crew_assigned → resolved → verified → closed
    """

    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Fault classification
    fault_type: Mapped[FaultType] = mapped_column(Enum(FaultType), nullable=False)
    status: Mapped[TicketStatus] = mapped_column(
        Enum(TicketStatus), nullable=False, default=TicketStatus.detected, index=True
    )

    # Human-readable fault location
    fault_location_description: Mapped[str] = mapped_column(Text, nullable=False)

    # Geographic coordinates of the fault
    lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lon: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pincode: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    # Affected infrastructure — stored as JSON arrays of string IDs
    affected_pole_ids: Mapped[Optional[List[str]]] = mapped_column(
        JSON, nullable=True, comment="Ordered list of affected pole IDs"
    )

    # Fault span endpoints (for span faults)
    upstream_pole_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("poles.id", ondelete="SET NULL"),
        nullable=True,
        comment="Last energized pole upstream of fault",
    )
    downstream_pole_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("poles.id", ondelete="SET NULL"),
        nullable=True,
        comment="First de-energized pole downstream of fault",
    )

    # Infrastructure FKs
    dt_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("distribution_transformers.id", ondelete="SET NULL"),
        nullable=True,
    )
    feeder_id: Mapped[Optional[str]] = mapped_column(
        String(50), ForeignKey("feeders.id", ondelete="SET NULL"), nullable=True
    )

    # Impact estimate
    affected_downstream_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )

    # Confidence scoring
    confidence: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0,
        comment="Detection confidence in [0, 1]"
    )
    confidence_reason: Mapped[str] = mapped_column(
        Text, nullable=False, default="",
        comment="Human-readable explanation of the confidence score"
    )
    topology_source: Mapped[TopologySource] = mapped_column(
        Enum(TopologySource), nullable=False, default=TopologySource.inferred
    )

    # Lifecycle timestamps
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Audit timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    dt: Mapped[Optional["DistributionTransformer"]] = relationship(  # type: ignore[name-defined]
        "DistributionTransformer", back_populates="tickets"
    )
    feeder: Mapped[Optional["Feeder"]] = relationship(  # type: ignore[name-defined]
        "Feeder", back_populates="tickets"
    )

    def __repr__(self) -> str:
        return (
            f"<Ticket id={self.id} type={self.fault_type} "
            f"status={self.status} confidence={self.confidence:.2f}>"
        )
