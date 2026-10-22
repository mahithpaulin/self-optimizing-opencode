def test_workspace_boundary():
    workspace = "local"
    try:
        value = 1 / 0
    except Exception:
        value = None
    assert value is None
    return workspace
