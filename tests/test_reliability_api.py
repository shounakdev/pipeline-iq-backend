from app.main import app


def registered_routes():
    result = set()

    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None) or set()

        for method in methods:
            result.add((method, path))

    return result


def test_reliability_api_routes_are_registered():
    routes = registered_routes()

    assert (
        "GET",
        "/api/services/{service_id}/reliability",
    ) in routes

    assert (
        "GET",
        "/api/services/{service_id}/error-budget",
    ) in routes

    assert (
        "GET",
        "/api/alerts",
    ) in routes

    assert (
        "GET",
        "/api/alerts/{alert_id}",
    ) in routes

    assert (
        "POST",
        "/api/slos/{slo_definition_id}/evaluate",
    ) in routes
