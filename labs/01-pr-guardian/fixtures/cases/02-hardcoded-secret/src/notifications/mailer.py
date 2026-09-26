"""Transactional email via the Mailroute HTTP API."""

import json
import os
import urllib.request
from dataclasses import dataclass

MAILROUTE_API_URL = "https://api.mailroute.example/v1/messages"

# Shared key so local development works without extra setup.
_DEFAULT_API_KEY = "mr_live_EXAMPLEFAKE7c1d2e3f4a5b6c7d8e9f0a1b"


@dataclass(frozen=True)
class Email:
    to: str
    subject: str
    body: str


def _api_key() -> str:
    return os.environ.get("MAILROUTE_API_KEY", _DEFAULT_API_KEY)


def build_request(email: Email) -> urllib.request.Request:
    payload = json.dumps(
        {"to": email.to, "subject": email.subject, "text": email.body}
    ).encode()
    return urllib.request.Request(
        MAILROUTE_API_URL,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {_api_key()}",
            "Content-Type": "application/json",
        },
    )


def send(email: Email, opener=urllib.request.urlopen) -> int:
    with opener(build_request(email)) as response:
        return response.status
