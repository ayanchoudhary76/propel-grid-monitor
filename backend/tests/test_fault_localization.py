import pytest
from unittest.mock import AsyncMock, MagicMock
from app.core.fault_detector import FaultDetector
from app.models.ticket import FaultType

@pytest.fixture
def fault_detector(simple_linear_topology):
    redis_mock = MagicMock()
    pipe_mock = MagicMock()
    pipe_mock.execute = AsyncMock()
    # Need to make execute() return a list of results
    redis_mock.pipeline.return_value = pipe_mock
    
    outage_manager_mock = MagicMock()
    outage_manager_mock.is_under_scheduled_outage.return_value = False
    
    db_factory_mock = MagicMock()
    
    fd = FaultDetector(
        topology=simple_linear_topology,
        redis_client=redis_mock,
        db_session_factory=db_factory_mock,
        outage_manager=outage_manager_mock
    )
    # Mock _create_ticket to easily inspect what faults are detected
    fd._create_ticket = AsyncMock()
    return fd

@pytest.mark.asyncio
async def test_span_fault_linear_known_topology(fault_detector, simple_linear_topology):
    fd = fault_detector
    pole_states = {
        "P-001": True,
        "P-002": True,
        "P-003": False,
        "P-004": False,
        "P-005": False
    }
    boundaries = await fd._find_fault_boundaries("DT-TEST", pole_states)
    assert len(boundaries) == 1
    b = boundaries[0]
    assert b.upstream_pole_id == "P-002"
    assert b.downstream_pole_id == "P-003"
    assert b.confidence == 0.9

@pytest.mark.asyncio
async def test_span_fault_at_root(fault_detector, simple_linear_topology):
    # Set P-001 dark, everything else dark
    pole_states = {
        "P-001": False,
        "P-002": False,
        "P-003": False,
        "P-004": False,
        "P-005": False
    }
    # find_fault_boundaries will detect boundary at (DT, P-001)
    boundaries = await fault_detector._find_fault_boundaries("DT-TEST", pole_states)
    assert len(boundaries) == 1
    b = boundaries[0]
    assert b.upstream_pole_id == "DT-TEST"
    assert b.downstream_pole_id == "P-001"
    
@pytest.mark.asyncio
async def test_span_fault_at_tip(fault_detector, simple_linear_topology):
    pole_states = {
        "P-001": True,
        "P-002": True,
        "P-003": True,
        "P-004": True,
        "P-005": False
    }
    boundaries = await fault_detector._find_fault_boundaries("DT-TEST", pole_states)
    assert len(boundaries) == 1
    b = boundaries[0]
    assert b.upstream_pole_id == "P-004"
    assert b.downstream_pole_id == "P-005"
    assert b.affected_count == 1

@pytest.mark.asyncio
async def test_span_fault_on_branch(branching_topology):
    fd = FaultDetector(branching_topology, AsyncMock(), MagicMock(), MagicMock())
    pole_states = {
        "P-001": True,
        "P-002": True,
        "P-003": True,
        "P-004": True,  # Main line live
        "P-005": False, # Branch dark
        "P-006": False
    }
    boundaries = await fd._find_fault_boundaries("DT-TEST", pole_states)
    assert len(boundaries) == 1
    b = boundaries[0]
    assert b.upstream_pole_id == "P-003"
    assert b.downstream_pole_id == "P-005"

@pytest.mark.asyncio
async def test_one_fault_produces_one_ticket(simple_linear_topology):
    fd = FaultDetector(simple_linear_topology, AsyncMock(), MagicMock(), MagicMock())
    # All downstream of P-002 are dark
    pole_states = {
        "P-001": True,
        "P-002": True,
        "P-003": False,
        "P-004": False,
        "P-005": False
    }
    boundaries = await fd._find_fault_boundaries("DT-TEST", pole_states)
    # Should be exactly 1 boundary, not 3
    assert len(boundaries) == 1

@pytest.mark.asyncio
async def test_multiple_simultaneous_faults(branching_topology):
    fd = FaultDetector(branching_topology, AsyncMock(), MagicMock(), MagicMock())
    # Branch broken at P-005, and main line broken at P-004
    pole_states = {
        "P-001": True,
        "P-002": True,
        "P-003": True,
        "P-004": False,
        "P-005": False,
        "P-006": False
    }
    boundaries = await fd._find_fault_boundaries("DT-TEST", pole_states)
    # Two separate boundaries
    assert len(boundaries) == 2
    pairs = {(b.upstream_pole_id, b.downstream_pole_id) for b in boundaries}
    assert pairs == {("P-003", "P-004"), ("P-003", "P-005")}

@pytest.mark.asyncio
async def test_multiple_faults_different_dts(multi_dt_feeder_topology):
    fd = FaultDetector(multi_dt_feeder_topology, AsyncMock(), MagicMock(), MagicMock())
    
    # Fault on DT-A
    pole_states_a = {"P-A01": True, "P-A02": False, "P-A03": False}
    b_a = await fd._find_fault_boundaries("DT-A", pole_states_a)
    assert len(b_a) == 1
    
    # Fault on DT-B
    pole_states_b = {"P-B01": True, "P-B02": True, "P-B03": False}
    b_b = await fd._find_fault_boundaries("DT-B", pole_states_b)
    assert len(b_b) == 1

@pytest.mark.asyncio
async def test_dead_sensor_not_a_fault(fault_detector, simple_linear_topology):
    pole_states = {
        "P-001": True,
        "P-002": True,
        "P-003": False, # Dark, but children are live
        "P-004": True,
        "P-005": True
    }
    dead_sensors = await fault_detector._detect_dead_sensors("DT-TEST", pole_states)
    assert "P-003" in dead_sensors
    assert len(dead_sensors) == 1
    
    # If a sensor is dead, we delete it from pole_states before finding boundaries
    del pole_states["P-003"]
    boundaries = await fault_detector._find_fault_boundaries("DT-TEST", pole_states)
    # No fault boundaries should be found
    assert len(boundaries) == 0

@pytest.mark.asyncio
async def test_dead_sensor_at_leaf(fault_detector, simple_linear_topology):
    pole_states = {
        "P-001": True,
        "P-002": True,
        "P-003": True,
        "P-004": True,
        "P-005": False # Leaf node is dark
    }
    dead_sensors = await fault_detector._detect_dead_sensors("DT-TEST", pole_states)
    # Without downstream live nodes, it cannot be confirmed as a dead sensor
    assert "P-005" not in dead_sensors
    
    # It will be detected as a span fault at the tip
    boundaries = await fault_detector._find_fault_boundaries("DT-TEST", pole_states)
    assert len(boundaries) == 1
    assert boundaries[0].downstream_pole_id == "P-005"

@pytest.mark.asyncio
async def test_dt_fault_all_poles_dark(fault_detector, simple_linear_topology):
    # Mock redis to return "0" (dark) for all poles
    fault_detector.redis.pipeline.return_value.execute.return_value = ["0", "0", "0", "0", "0"]
    fault_detector.topology = simple_linear_topology
    fault_detector._analyze_feeder = AsyncMock(return_value=False)
    
    await fault_detector._analyze_dt("DT-TEST")
    
    # _create_ticket should be called with FaultType.dt
    fault_detector._create_ticket.assert_called_once()
    fault_info = fault_detector._create_ticket.call_args[0][0]
    assert fault_info["fault_type"] == FaultType.dt

@pytest.mark.asyncio
async def test_feeder_fault_all_dts_dark(fault_detector, multi_dt_feeder_topology):
    fault_detector.topology = multi_dt_feeder_topology
    # 6 poles total across 2 DTs, all return "0"
    fault_detector.redis.pipeline.return_value.execute.return_value = ["0"] * 6
    
    is_feeder_fault = await fault_detector._analyze_feeder("F-TEST")
    assert is_feeder_fault is True
    
    fault_detector._create_ticket.assert_called_once()
    fault_info = fault_detector._create_ticket.call_args[0][0]
    assert fault_info["fault_type"] == FaultType.feeder

@pytest.mark.asyncio
async def test_fault_boundary_through_deviceless_poles(topology_with_gaps):
    fd = FaultDetector(topology_with_gaps, AsyncMock(), MagicMock(), MagicMock())
    # P-002 and P-003 have no devices, so they aren't in pole_states
    pole_states = {
        "P-001": True,
        "P-004": False,
        "P-005": False
    }
    boundaries = await fd._find_fault_boundaries("DT-TEST", pole_states)
    assert len(boundaries) == 1
    b = boundaries[0]
    # The last known live was P-001, the first known dark is P-004
    assert b.upstream_pole_id == "P-001"
    assert b.downstream_pole_id == "P-004"
    assert "P-002" in b.confidence_reason
    assert "P-003" in b.confidence_reason

@pytest.mark.asyncio
async def test_known_topology_high_confidence(simple_linear_topology):
    fd = FaultDetector(simple_linear_topology, AsyncMock(), MagicMock(), MagicMock())
    pole_states = {"P-001": True, "P-002": False}
    boundaries = await fd._find_fault_boundaries("DT-TEST", pole_states)
    assert boundaries[0].confidence >= 0.85

@pytest.mark.asyncio
async def test_inferred_topology_lower_confidence(inferred_topology):
    fd = FaultDetector(inferred_topology, AsyncMock(), MagicMock(), MagicMock())
    pole_states = {"P-001": True, "P-002": False}
    boundaries = await fd._find_fault_boundaries("DT-TEST", pole_states)
    assert boundaries[0].confidence <= 0.7

@pytest.mark.asyncio
async def test_scheduled_outage_suppresses_ticket(fault_detector, simple_linear_topology):
    fault_detector.topology = simple_linear_topology
    # Mock redis to return "0" (dark) for all poles (would normally be DT fault)
    fault_detector.redis.pipeline.return_value.execute.return_value = ["0", "0", "0", "0", "0"]
    
    # Active scheduled outage
    fault_detector.outage_manager.is_under_scheduled_outage.return_value = True
    
    await fault_detector._analyze_dt("DT-TEST")
    
    # Ticket should NOT be created
    fault_detector._create_ticket.assert_not_called()

@pytest.mark.asyncio
async def test_outage_buffer_window():
    # test_outage_buffer_window: poles go dark 30 minutes after scheduled end (within ±40min buffer)
    # The buffer window is implemented in is_under_scheduled_outage. We just test the outage manager's behavior.
    from app.core.scheduled_outages import ScheduledOutageManager, ScheduledOutage
    from datetime import datetime, timedelta, timezone
    
    manager = ScheduledOutageManager()
    now = datetime.now(timezone.utc)
    
    # Create an outage that ended 30 minutes ago
    start = now - timedelta(hours=2)
    end = now - timedelta(minutes=30)
    manager.add_outage(ScheduledOutage(id="SO-1", scope="dt", target_id="DT-TEST", start=start, end=end, reason="Test"))
    
    # Should still be considered under outage because 30m < 40m buffer
    assert manager.is_under_scheduled_outage(dt_id="DT-TEST") is True
    
    # If ended 50 minutes ago, should NOT be suppressed
    end2 = now - timedelta(minutes=50)
    manager.add_outage(ScheduledOutage(id="SO-2", scope="dt", target_id="DT-TEST2", start=start, end=end2, reason="Test2"))
    
    assert manager.is_under_scheduled_outage(dt_id="DT-TEST2") is False
