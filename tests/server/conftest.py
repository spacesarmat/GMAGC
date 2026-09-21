import http.client
import json

import pytest


@pytest.fixture()
def call(running):
    """call(метод, путь, body=None, code=<верный>) -> (статус, ответ http.client, JSON или None)."""

    def _call(method, path, body=None, code="valid", headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", running.port, timeout=20)
        head = dict(headers or {})
        token = running.code if code == "valid" else code
        if token is not None:
            head["Authorization"] = f"Bearer {token}"
        try:
            connection.request(method, path, body=body, headers=head)
            response = connection.getresponse()
            raw = response.read()
            return response.status, response, (json.loads(raw) if raw else None)
        finally:
            connection.close()

    return _call
