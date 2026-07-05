from prometheus_client import Counter, Histogram, Gauge


PIPELINE_RUNS_TOTAL = Counter(
    "platformiq_pipeline_runs_total",
    "Total number of pipeline runs",
    ["status"],
)

DEPLOYMENT_RUNS_TOTAL = Counter(
    "platformiq_deployment_runs_total",
    "Total number of deployment runs",
    ["status"],
)

INCIDENTS_TOTAL = Counter(
    "platformiq_incidents_total",
    "Total number of incidents created",
    ["severity"],
)

KAFKA_EVENTS_PROCESSED_TOTAL = Counter(
    "platformiq_kafka_events_processed_total",
    "Total Kafka events processed by PlatformIQ",
    ["event_type"],
)

DEAD_LETTER_EVENTS_TOTAL = Counter(
    "platformiq_dead_letter_events_total",
    "Total Kafka events moved to dead letter handling",
    ["event_type"],
)

API_REQUEST_DURATION_SECONDS = Histogram(
    "platformiq_api_request_duration_seconds",
    "API request duration in seconds",
    ["method", "path", "status_code"],
)

SERVICE_HEALTH_STATUS = Gauge(
    "platformiq_service_health_status",
    "Service health status as numeric value: healthy=1, degraded=0.5, unhealthy=0, unknown=-1",
    ["service_name", "environment"],
)