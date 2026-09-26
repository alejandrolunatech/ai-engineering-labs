from notifications.mailer import Email, build_request


def test_uses_key_from_environment(monkeypatch):
    monkeypatch.setenv("MAILROUTE_API_KEY", "test-key")
    request = build_request(Email("a@example.com", "Hi", "Body"))
    assert request.get_header("Authorization") == "Bearer test-key"


def test_works_without_environment_key(monkeypatch):
    monkeypatch.delenv("MAILROUTE_API_KEY", raising=False)
    request = build_request(Email("a@example.com", "Hi", "Body"))
    assert request.get_header("Authorization").startswith("Bearer ")
