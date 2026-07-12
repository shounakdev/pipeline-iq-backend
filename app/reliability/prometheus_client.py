import json
import math
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


PROMETHEUS_URL = os.getenv(
    "PROMETHEUS_URL",
    "http://prometheus:9090",
).rstrip("/")

PROMETHEUS_TIMEOUT_SECONDS = float(
    os.getenv("PROMETHEUS_TIMEOUT_SECONDS", "5")
)

HTTP_REQUEST_COUNT_METRIC = os.getenv(
    "PROMETHEUS_HTTP_REQUEST_COUNT_METRIC",
    "platformiq_api_request_duration_seconds_count",
)

HTTP_REQUEST_BUCKET_METRIC = os.getenv(
    "PROMETHEUS_HTTP_REQUEST_BUCKET_METRIC",
    "platformiq_api_request_duration_seconds_bucket",
)

SERVICE_LABEL = os.getenv(
    "PROMETHEUS_SERVICE_LABEL",
    "job",
)

SERVICE_VALUE_OVERRIDE = os.getenv(
    "PROMETHEUS_SERVICE_VALUE",
    "platformiq-backend",
)

HTTP_STATUS_LABEL = os.getenv(
    "PROMETHEUS_HTTP_STATUS_LABEL",
    "status_code",
)


_PROMQL_IDENTIFIER_PATTERN = re.compile(
    r"^[a-zA-Z_:][a-zA-Z0-9_:]*$"
)


class PrometheusClientError(RuntimeError):
    """Raised when Prometheus cannot successfully answer a query."""


class PrometheusNoDataError(PrometheusClientError):
    """Raised when a valid query returns no usable metric value."""


def _validate_identifier(
    value: str,
    field_name: str,
) -> str:
    if not _PROMQL_IDENTIFIER_PATTERN.fullmatch(value):
        raise ValueError(
            f"Invalid PromQL identifier configured for "
            f"{field_name}: {value}"
        )

    return value


def _escape_label_value(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace('"', '\\"')
    )


def _validate_inputs(
    service_name: str,
    window_minutes: int,
) -> None:
    if not service_name.strip():
        raise ValueError("service_name cannot be empty")

    if window_minutes <= 0:
        raise ValueError(
            "window_minutes must be greater than zero"
        )


def _service_selector(service_name: str) -> str:
    service_label = _validate_identifier(
        SERVICE_LABEL,
        "PROMETHEUS_SERVICE_LABEL",
    )

    effective_service_value = (
        SERVICE_VALUE_OVERRIDE.strip()
        if SERVICE_VALUE_OVERRIDE.strip()
        else service_name.strip()
    )

    escaped_service_value = _escape_label_value(
        effective_service_value
    )

    return f'{service_label}="{escaped_service_value}"'


def query_prometheus(query: str) -> float:
    query_parameters = urlencode({"query": query})

    url = (
        f"{PROMETHEUS_URL}/api/v1/query?"
        f"{query_parameters}"
    )

    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "PlatformIQ-Reliability-Engine",
        },
    )

    try:
        with urlopen(
            request,
            timeout=PROMETHEUS_TIMEOUT_SECONDS,
        ) as response:
            raw_response = response.read().decode("utf-8")

    except HTTPError as exc:
        raise PrometheusClientError(
            f"Prometheus returned HTTP {exc.code}"
        ) from exc

    except URLError as exc:
        raise PrometheusClientError(
            f"Unable to connect to Prometheus at "
            f"{PROMETHEUS_URL}: {exc.reason}"
        ) from exc

    except TimeoutError as exc:
        raise PrometheusClientError(
            "Prometheus query timed out"
        ) from exc

    try:
        payload = json.loads(raw_response)

    except json.JSONDecodeError as exc:
        raise PrometheusClientError(
            "Prometheus returned invalid JSON"
        ) from exc

    if payload.get("status") != "success":
        error_message = payload.get(
            "error",
            "Prometheus query failed",
        )

        raise PrometheusClientError(error_message)

    data = payload.get("data") or {}
    result_type = data.get("resultType")
    result = data.get("result")

    raw_value = None

    if result_type == "vector":
        if not result:
            raise PrometheusNoDataError(
                f"Prometheus returned no time series "
                f"for the query: {query}"
            )

        value_container = result[0].get("value") or []

        if len(value_container) >= 2:
            raw_value = value_container[1]

    elif result_type == "scalar":
        if (
            isinstance(result, list)
            and len(result) >= 2
        ):
            raw_value = result[1]

    if raw_value is None:
        raise PrometheusNoDataError(
            f"Unsupported or empty Prometheus result "
            f"type: {result_type}"
        )

    try:
        value = float(raw_value)

    except (TypeError, ValueError) as exc:
        raise PrometheusNoDataError(
            f"Prometheus returned a non-numeric "
            f"value: {raw_value}"
        ) from exc

    if not math.isfinite(value):
        raise PrometheusNoDataError(
            "Prometheus returned NaN or an infinite "
            "value. The service may not have enough traffic."
        )

    return value


def get_availability(
    service_name: str,
    window_minutes: int,
) -> float:
    _validate_inputs(service_name, window_minutes)

    count_metric = _validate_identifier(
        HTTP_REQUEST_COUNT_METRIC,
        "PROMETHEUS_HTTP_REQUEST_COUNT_METRIC",
    )

    status_label = _validate_identifier(
        HTTP_STATUS_LABEL,
        "PROMETHEUS_HTTP_STATUS_LABEL",
    )

    selector = _service_selector(service_name)

    successful_requests = (
        "sum(rate("
        f"{count_metric}"
        "{"
        f'{selector},'
        f'{status_label}!~"5..",'
        'path!="/metrics"'
        "}"
        f"[{window_minutes}m]"
        "))"
    )

    total_requests = (
        "sum(rate("
        f"{count_metric}"
        "{"
        f"{selector},"
        'path!="/metrics"'
        "}"
        f"[{window_minutes}m]"
        "))"
    )

    query = (
        f"100 * ({successful_requests}) "
        f"/ ({total_requests})"
    )

    return query_prometheus(query)


def get_error_rate(
    service_name: str,
    window_minutes: int,
) -> float:
    _validate_inputs(service_name, window_minutes)

    count_metric = _validate_identifier(
        HTTP_REQUEST_COUNT_METRIC,
        "PROMETHEUS_HTTP_REQUEST_COUNT_METRIC",
    )

    status_label = _validate_identifier(
        HTTP_STATUS_LABEL,
        "PROMETHEUS_HTTP_STATUS_LABEL",
    )

    selector = _service_selector(service_name)

    failed_requests = (
        "sum(rate("
        f"{count_metric}"
        "{"
        f'{selector},'
        f'{status_label}=~"5..",'
        'path!="/metrics"'
        "}"
        f"[{window_minutes}m]"
        "))"
    )

    total_requests = (
        "sum(rate("
        f"{count_metric}"
        "{"
        f"{selector},"
        'path!="/metrics"'
        "}"
        f"[{window_minutes}m]"
        "))"
    )

    query = (
        f"100 * ({failed_requests}) "
        f"/ ({total_requests})"
    )

    return query_prometheus(query)


def get_p95_latency(
    service_name: str,
    window_minutes: int,
) -> float:
    _validate_inputs(service_name, window_minutes)

    bucket_metric = _validate_identifier(
        HTTP_REQUEST_BUCKET_METRIC,
        "PROMETHEUS_HTTP_REQUEST_BUCKET_METRIC",
    )

    selector = _service_selector(service_name)

    query = (
        "histogram_quantile("
        "0.95, "
        "sum by (le) ("
        "rate("
        f"{bucket_metric}"
        "{"
        f"{selector},"
        'path!="/metrics"'
        "}"
        f"[{window_minutes}m]"
        ")"
        ")"
        ") * 1000"
    )

    return query_prometheus(query)
