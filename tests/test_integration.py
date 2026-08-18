from biaoshu_gen.nodes import DEFAULT_NODES, NODE_NAMES


def test_all_nodes_registered_no_stubs():
    for name in NODE_NAMES:
        fn = DEFAULT_NODES[name]
        assert callable(fn)
        assert not fn.__name__.endswith("_stub"), f"{name} 仍是 stub"


def test_nodes_cover_all_twelve():
    assert len(NODE_NAMES) == 12
    assert set(NODE_NAMES) == set(DEFAULT_NODES.keys())
