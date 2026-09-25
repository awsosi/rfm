"""
PolkaSQL answers in its database charset (Windows-1250), not UTF-8.

Regression: PUSH of ``RĘKAWICZKI 7X000310 AF29587-UC001`` was refused with
"cannot connect to PolkaSQL" because ``response.json()`` hit byte 0xCA (``Ę``)
and raised ``UnicodeDecodeError``, although the service had answered
``valid: true``.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from api.services import catalog_validation_service
from api.services.polka import polka_json

NAME = "RĘKAWICZKI 7X000310 AF29587-UC001"
TG_ID = "RĘKAWICZKI 7X000310 AF29587"


def body(charset):
    # Same field order and spacing as RFM_sp_ValidateProductName builds it
    return (
        '{"success": true,"valid": true,"error": null,'
        f'"catalog_name": "{NAME}","matched_name": "{NAME}",'
        f'"product_id": 123,"tg_id": "{TG_ID}","suggestions": []}}'
    ).encode(charset)


@pytest.mark.parametrize("content_type, charset", [
    ("text/plain", "cp1250"),                        # no charset declared
    ("text/plain; charset=windows-1250", "cp1250"),  # declared
    ("application/json", "utf-8"),                   # UTF-8 body
    ("text/plain; charset=UTF-8", "cp1250"),         # label does not match the body
])
def test_polka_json_decodes_polish_names(content_type, charset):
    response = httpx.Response(200, headers={"Content-Type": content_type}, content=body(charset))
    data = polka_json(response)
    assert data["catalog_name"] == NAME
    assert data["tg_id"] == TG_ID


def test_cp1250_body_is_not_utf8():
    # Pins the failure mode: the byte at position 63 is the 'Ę'
    raw = body("cp1250")
    assert raw[63] == 0xCA
    with pytest.raises(UnicodeDecodeError):
        json.loads(raw)


@pytest.fixture
def polka_server():
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            # With Accept-Charset: utf-8 PolkaSQL stops matching Polish names
            assert "Accept-Charset" not in self.headers
            received.append(parse_qs(urlparse(self.path).query)["CatalogName"][0])
            payload = body("cp1250")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/RFM_ValidateProductName", received
    server.shutdown()


async def test_validate_and_lookup_accept_cp1250(polka_server, monkeypatch):
    url, received = polka_server

    async def config(_db):
        return {"catalog_validation_enabled": "true", "catalog_validation_url": url,
                "catalog_validation_api_key": "key"}

    monkeypatch.setattr(catalog_validation_service, "_get_validation_config", config)

    result = await catalog_validation_service.validate_catalog_name(NAME, db=None)
    assert result.valid and result.reason is None
    assert result.tg_id == TG_ID

    assert await catalog_validation_service.lookup_tg_id(NAME, db=None) == (TG_ID, None)
    assert received == [NAME, NAME]
