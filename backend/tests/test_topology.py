def test_known_topology_preserves_parent_child(simple_linear_topology):
    topo = simple_linear_topology
    assert topo.poles["P-001"].parent_id is None
    assert topo.poles["P-002"].parent_id == "P-001"
    assert "P-002" in topo.poles["P-001"].children

def test_downstream_poles(simple_linear_topology):
    topo = simple_linear_topology
    downstream = topo.get_downstream_poles("P-002")
    # Linear chain P-001 -> P-002 -> P-003 -> P-004 -> P-005
    assert set(downstream) == {"P-003", "P-004", "P-005"}

def test_upstream_path(simple_linear_topology):
    topo = simple_linear_topology
    path = topo.get_upstream_path("P-005")
    # Path includes self up to root
    assert path == ["P-005", "P-004", "P-003", "P-002", "P-001"]

def test_get_span_adjacent(simple_linear_topology):
    topo = simple_linear_topology
    span = topo.get_span("P-002", "P-003")
    assert span == ("P-002", "P-003")
    
    # Should work in reverse order too
    span_rev = topo.get_span("P-003", "P-002")
    assert span_rev == ("P-002", "P-003")

def test_get_span_non_adjacent(simple_linear_topology):
    topo = simple_linear_topology
    span = topo.get_span("P-001", "P-004")
    assert span is None

def test_branching_downstream(branching_topology):
    topo = branching_topology
    # DT-TEST → P-001 → P-002 → P-003 → P-004
    #                              └──→ P-005 → P-006  (branch)
    downstream = topo.get_downstream_poles("P-003")
    assert set(downstream) == {"P-004", "P-005", "P-006"}
