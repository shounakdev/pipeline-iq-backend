from app.rca.collectors.redaction import REDACTED, redact_evidence


def test_redacts_sensitive_keys():
    evidence = {
        "authorization": "Bearer abc123",
        "password": "super-secret",
        "safe": "hello",
    }

    redacted = redact_evidence(evidence)

    assert redacted["authorization"] == REDACTED
    assert redacted["password"] == REDACTED
    assert redacted["safe"] == "hello"


def test_redacts_database_urls_inside_strings():
    evidence = {
        "log": "failed connecting to postgres://user:pass@localhost:5432/app"
    }

    redacted = redact_evidence(evidence)

    assert "postgres://" not in redacted["log"]
    assert REDACTED in redacted["log"]
    
def test_redacts_large_request_response_bodies():
    evidence = {
        "request_body": {"card": "1234"},
        "response_body": "very large response",
        "message": "safe",
    }

    redacted = redact_evidence(evidence)

    assert redacted["request_body"] == "[REDACTED_LARGE_BODY]"
    assert redacted["response_body"] == "[REDACTED_LARGE_BODY]"
    assert redacted["message"] == "safe"