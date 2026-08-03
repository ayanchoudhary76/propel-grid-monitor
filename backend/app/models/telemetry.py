"""
SQLAlchemy model for IoT telemetry events received from pole-mounted devices.
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class EventType(str, enum.Enum):
    heartbeat = "heartbeat"
    power_lost = "power_lost"
    power_restored = "power_restored"
    boot = "boot"


class TelemetryEvent(Base):
    """
    A single telemetry packet sent by an IoT device mounted on a distribution pole.

    The (device_id, seq) unique constraint is used for idempotent ingestion —
    duplicate packets from re-transmits are silently ignored.
    """

    __tablename__ = "telemetry_events"
    __table_args__ = (
        UniqueConstraint("device_id", "seq", name="uq_telemetry_device_seq"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Device / pole identifiers
    device_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    pole_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("poles.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Payload
    event: Mapped[EventType] = mapped_column(Enum(EventType), nullable=False)
    energized: Mapped[bool] = mapped_column(Boolean, nullable=False)

    # Timestamps
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="Device-reported UTC timestamp"
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="Server-side ingestion timestamp",
    )

    # Sequencing & diagnostics
    seq: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="Monotonic sequence number from device"
    )
    battery_mv: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="Battery voltage in millivolts"
    )
    rssi: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="RSSI in dBm (negative)"
    )
    fw: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="Firmware version string"
    )

    # Relationships
    pole: Mapped["Pole"] = relationship(  # type: ignore[name-defined]
        "Pole", back_populates="telemetry_events"
    )

    def __repr__(self) -> str:
        return (
            f"<TelemetryEvent id={self.id} device={self.device_id!r} "
            f"event={self.event} energized={self.energized} ts={self.ts}>"
        )
