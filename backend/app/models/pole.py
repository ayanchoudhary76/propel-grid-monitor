"""
SQLAlchemy models for the grid topology:
  Substation → Feeder → DistributionTransformer → Pole (tree)
"""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Substation(Base):
    """High-voltage / 11 kV substation that feeds one or more feeders."""

    __tablename__ = "substations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)

    # Relationships
    feeders: Mapped[List["Feeder"]] = relationship(
        "Feeder", back_populates="substation", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Substation id={self.id} name={self.name!r}>"


class Feeder(Base):
    """11 kV feeder circuit originating from a substation."""

    __tablename__ = "feeders"

    # Natural key like "F-07-03"
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    substation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("substations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Relationships
    substation: Mapped["Substation"] = relationship(
        "Substation", back_populates="feeders"
    )
    distribution_transformers: Mapped[List["DistributionTransformer"]] = relationship(
        "DistributionTransformer", back_populates="feeder", cascade="all, delete-orphan"
    )
    poles: Mapped[List["Pole"]] = relationship(
        "Pole", back_populates="feeder", cascade="all, delete-orphan"
    )
    tickets: Mapped[List["Ticket"]] = relationship(  # type: ignore[name-defined]
        "Ticket", back_populates="feeder"
    )

    def __repr__(self) -> str:
        return f"<Feeder id={self.id!r} name={self.name!r}>"


class DistributionTransformer(Base):
    """Distribution transformer (DT) that steps down 11 kV to 415 V / 230 V."""

    __tablename__ = "distribution_transformers"

    # Natural key like "D-0112"
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    feeder_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("feeders.id", ondelete="CASCADE"), nullable=False
    )
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    capacity_kva: Mapped[int] = mapped_column(Integer, nullable=False)
    households_served: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Relationships
    feeder: Mapped["Feeder"] = relationship(
        "Feeder", back_populates="distribution_transformers"
    )
    poles: Mapped[List["Pole"]] = relationship(
        "Pole", back_populates="dt", cascade="all, delete-orphan"
    )
    tickets: Mapped[List["Ticket"]] = relationship(  # type: ignore[name-defined]
        "Ticket", back_populates="dt"
    )

    def __repr__(self) -> str:
        return f"<DistributionTransformer id={self.id!r} capacity={self.capacity_kva} kVA>"


class Pole(Base):
    """
    Low-tension (LT) distribution pole.

    seq_on_line  – position along the LT line from the DT (1-indexed).
                   NULL when topology is not precisely known.
    parent_pole_id – the upstream pole; NULL for the first pole off the DT.
    has_topology   – True when seq_on_line is present (denormalised flag for
                     fast filtering in the fault-localisation engine).
    """

    __tablename__ = "poles"
    __table_args__ = (
        UniqueConstraint("device_id", name="uq_poles_device_id"),
    )

    # Natural key like "P-024431"
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    dt_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("distribution_transformers.id", ondelete="CASCADE"),
        nullable=False,
    )
    feeder_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("feeders.id", ondelete="CASCADE"), nullable=False
    )
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)

    # Topology
    seq_on_line: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    parent_pole_id: Mapped[Optional[str]] = mapped_column(
        String(50), ForeignKey("poles.id", ondelete="SET NULL"), nullable=True
    )
    pole_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="distribution"
    )
    has_topology: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Location metadata
    ward: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    pincode: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    # IoT device bound to this pole
    device_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Relationships
    dt: Mapped["DistributionTransformer"] = relationship(
        "DistributionTransformer", back_populates="poles"
    )
    feeder: Mapped["Feeder"] = relationship("Feeder", back_populates="poles")
    parent_pole: Mapped[Optional["Pole"]] = relationship(
        "Pole", remote_side="Pole.id", back_populates="child_poles", foreign_keys=[parent_pole_id]
    )
    child_poles: Mapped[List["Pole"]] = relationship(
        "Pole", back_populates="parent_pole", foreign_keys=[parent_pole_id]
    )
    telemetry_events: Mapped[List["TelemetryEvent"]] = relationship(  # type: ignore[name-defined]
        "TelemetryEvent", back_populates="pole"
    )

    def __repr__(self) -> str:
        return f"<Pole id={self.id!r} seq={self.seq_on_line}>"
