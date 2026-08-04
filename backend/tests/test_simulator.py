from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api.simulator import SpanFaultReq, simulate_span_fault
from app.core.scheduled_outages import ScheduledOutage, ScheduledOutageManager
from app.core.simulator import FaultSimulator


@pytest.mark.asyncio
async def test_random_span_fault_uses_an_observable_subtree(topology_with_gaps):
    """The UI path must not choose a leaf that cannot send fault telemetry."""
    # Make P-005 an unmonitored leaf.  It is a valid edge but not a valid
    # simulator target because there is no device in its downstream subtree.
    topology_with_gaps.poles["P-005"].device_id = None
    simulator = MagicMock()
    simulator.topology = topology_with_gaps
    simulator.inject_span_fault = AsyncMock(return_value={"fault_id": "fault-1"})

    result = await simulate_span_fault(SpanFaultReq(dt_id="DT-TEST"), simulator)

    assert result == {"fault_id": "fault-1"}
    upstream, downstream = simulator.inject_span_fault.await_args.args
    assert upstream in topology_with_gaps.poles
    assert topology_with_gaps.get_subtree_device_count(downstream) > 0


@pytest.mark.asyncio
async def test_direct_span_fault_without_a_device_is_rejected(topology_with_gaps):
    """Direct API users receive an actionable error instead of a stuck fault."""
    topology_with_gaps.poles["P-005"].device_id = None
    simulator = FaultSimulator(
        topology=topology_with_gaps,
        redis_client=MagicMock(),
        outage_manager=MagicMock(),
    )

    with pytest.raises(ValueError, match="no monitored poles"):
        await simulator.inject_span_fault("P-004", "P-005")


@pytest.mark.asyncio
async def test_random_span_fault_reports_when_no_observable_span_exists(topology_with_gaps):
    for pole in topology_with_gaps.poles.values():
        pole.device_id = None
    simulator = MagicMock()
    simulator.topology = topology_with_gaps

    with pytest.raises(HTTPException) as exc_info:
        await simulate_span_fault(SpanFaultReq(dt_id="DT-TEST"), simulator)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "No observable spans found in DT"


@pytest.mark.asyncio
async def test_fault_injection_delivers_all_affected_device_states(simple_linear_topology):
    simulator = FaultSimulator(
        topology=simple_linear_topology,
        redis_client=MagicMock(),
        outage_manager=MagicMock(),
    )
    simulator._send_batch = AsyncMock()
    affected_poles = simple_linear_topology.get_poles_for_dt("DT-TEST")

    sent, suppressed = await simulator._generate_telemetry(
        affected_poles, guarantee_delivery=True
    )

    assert sent == len(affected_poles)
    assert suppressed == 0
    payloads = simulator._send_batch.await_args.args[0]
    assert len(payloads) == len(affected_poles)


def test_simulator_sequence_numbers_do_not_restart_at_the_deduplication_floor(
    simple_linear_topology,
):
    simulator = FaultSimulator(
        topology=simple_linear_topology,
        redis_client=MagicMock(),
        outage_manager=MagicMock(),
    )

    first = simulator._next_seq("DEV-P-001")
    second = simulator._next_seq("DEV-P-001")

    assert first > 1_000
    assert second > first


def test_scheduled_outage_manager_can_be_cleared():
    manager = ScheduledOutageManager()
    manager.add_outage(ScheduledOutage(
        id="SO-TEST", scope="dt", target_id="DT-TEST",
        start=None, end=None, reason="Test",
    ))

    manager.clear()

    assert manager._outages == []
