import pytest
from app.core.topology import NetworkTopology, PoleNode, TransformerTree

def _build_linear_topology(source: str):
    topo = NetworkTopology()
    dt_id = "DT-TEST"
    feeder_id = "F-TEST"
    
    tree = TransformerTree(
        dt_id=dt_id, feeder_id=feeder_id, lat=12.0, lon=77.0,
        capacity_kva=100, households_served=50,
        topology_source=source, total_poles=5, poles_with_device=5
    )
    
    poles = []
    for i in range(1, 6):
        pid = f"P-00{i}"
        parent_id = f"P-00{i-1}" if i > 1 else None
        node = PoleNode(
            pole_id=pid, lat=12.0 + i*0.001, lon=77.0, dt_id=dt_id, feeder_id=feeder_id,
            device_id=f"DEV-{pid}", pincode="560001", ward="W-001",
            parent_id=parent_id, seq_on_line=i, topology_source=source, depth=i-1
        )
        poles.append(node)

    for i in range(4):
        poles[i].children = [poles[i+1].pole_id]

    tree.root_poles = [poles[0].pole_id]
    
    for p in poles:
        tree.poles[p.pole_id] = p
        topo.poles[p.pole_id] = p
        topo.pole_to_dt[p.pole_id] = dt_id
        
    topo.transformers[dt_id] = tree
    topo.feeder_dts[feeder_id] = [dt_id]
    
    return topo

@pytest.fixture
def simple_linear_topology():
    return _build_linear_topology("known")

@pytest.fixture
def inferred_topology():
    return _build_linear_topology("inferred")

@pytest.fixture
def branching_topology():
    topo = NetworkTopology()
    dt_id = "DT-TEST"
    feeder_id = "F-TEST"
    
    tree = TransformerTree(
        dt_id=dt_id, feeder_id=feeder_id, lat=12.0, lon=77.0,
        capacity_kva=100, households_served=50,
        topology_source="known", total_poles=6, poles_with_device=6
    )
    
    # DT-TEST → P-001 → P-002 → P-003 → P-004
    #                              └──→ P-005 → P-006  (branch)
    parent_map = {
        "P-001": None,
        "P-002": "P-001",
        "P-003": "P-002",
        "P-004": "P-003",
        "P-005": "P-003",
        "P-006": "P-005"
    }
    
    poles = {}
    for pid, parent in parent_map.items():
        poles[pid] = PoleNode(
            pole_id=pid, lat=12.0, lon=77.0, dt_id=dt_id, feeder_id=feeder_id,
            device_id=f"DEV-{pid}", pincode="560001", ward="W-001",
            parent_id=parent, topology_source="known"
        )
        topo.poles[pid] = poles[pid]
        topo.pole_to_dt[pid] = dt_id
        tree.poles[pid] = poles[pid]
        
    for pid, p in poles.items():
        if p.parent_id:
            poles[p.parent_id].children.append(pid)
        else:
            tree.root_poles.append(pid)
            
    topo.transformers[dt_id] = tree
    topo.feeder_dts[feeder_id] = [dt_id]
    
    return topo

@pytest.fixture
def topology_with_gaps():
    topo = NetworkTopology()
    dt_id = "DT-TEST"
    feeder_id = "F-TEST"
    
    tree = TransformerTree(
        dt_id=dt_id, feeder_id=feeder_id, lat=12.0, lon=77.0,
        capacity_kva=100, households_served=50,
        topology_source="known", total_poles=5, poles_with_device=3
    )
    
    poles = {}
    parent_map = {
        "P-001": None,
        "P-002": "P-001",
        "P-003": "P-002",
        "P-004": "P-003",
        "P-005": "P-004"
    }
    has_device = {"P-001": True, "P-002": False, "P-003": False, "P-004": True, "P-005": True}
    
    for pid, parent in parent_map.items():
        poles[pid] = PoleNode(
            pole_id=pid, lat=12.0, lon=77.0, dt_id=dt_id, feeder_id=feeder_id,
            device_id=f"DEV-{pid}" if has_device[pid] else None, 
            pincode="560001", ward="W-001",
            parent_id=parent, topology_source="known"
        )
        topo.poles[pid] = poles[pid]
        topo.pole_to_dt[pid] = dt_id
        tree.poles[pid] = poles[pid]
        
    for pid, p in poles.items():
        if p.parent_id:
            poles[p.parent_id].children.append(pid)
        else:
            tree.root_poles.append(pid)
            
    topo.transformers[dt_id] = tree
    topo.feeder_dts[feeder_id] = [dt_id]
    
    return topo

@pytest.fixture
def multi_dt_feeder_topology():
    topo = NetworkTopology()
    feeder_id = "F-TEST"
    topo.feeder_dts[feeder_id] = ["DT-A", "DT-B"]
    
    for dt_prefix in ["A", "B"]:
        dt_id = f"DT-{dt_prefix}"
        tree = TransformerTree(
            dt_id=dt_id, feeder_id=feeder_id, lat=12.0, lon=77.0,
            capacity_kva=100, households_served=50,
            topology_source="known", total_poles=3, poles_with_device=3
        )
        
        poles = {}
        parent_map = {
            f"P-{dt_prefix}01": None,
            f"P-{dt_prefix}02": f"P-{dt_prefix}01",
            f"P-{dt_prefix}03": f"P-{dt_prefix}02"
        }
        
        for pid, parent in parent_map.items():
            poles[pid] = PoleNode(
                pole_id=pid, lat=12.0, lon=77.0, dt_id=dt_id, feeder_id=feeder_id,
                device_id=f"DEV-{pid}", pincode="560001", ward="W-001",
                parent_id=parent, topology_source="known"
            )
            topo.poles[pid] = poles[pid]
            topo.pole_to_dt[pid] = dt_id
            tree.poles[pid] = poles[pid]
            
        for pid, p in poles.items():
            if p.parent_id:
                poles[p.parent_id].children.append(pid)
            else:
                tree.root_poles.append(pid)
                
        topo.transformers[dt_id] = tree
        
    return topo
