from dtm_buildsheet.app.routes.quickbooks import _estimate_call


def test_estimate_route_boundary_returns_safe_reference():
    def fail():
        raise RuntimeError("secret third-party response")

    result = _estimate_call("creation", fail)

    assert result["ok"] is False
    assert result["error"] == "estimate_request_failed"
    assert len(result["reference"]) == 8
    assert "secret" not in result["detail"]
