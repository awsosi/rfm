"""
Shared helpers for the PolkaSQL (SQL Anywhere 17) web services.

SQL Anywhere answers RAW web services in the database character set,
Windows-1250 on PolkaSQL, unless the client negotiates otherwise.
``httpx.Response.json()`` always decodes UTF-8, so a product name such as
``RĘKAWICZKI 7X000310 AF29587-UC001`` (``Ę`` is byte 0xCA in cp1250) raised
``UnicodeDecodeError`` and was reported as "cannot connect to PolkaSQL".
"""

import json

import httpx

# Sent with every request so the server can answer in UTF-8; polka_json()
# copes with a server that ignores it.
POLKA_HEADERS = {"Accept": "application/json", "Accept-Charset": "utf-8"}

_FALLBACK_CHARSET = "cp1250"


def polka_json(response: httpx.Response):
    """Decode a PolkaSQL JSON body: declared charset, else UTF-8, else cp1250."""
    raw = response.content
    if response.charset_encoding:
        return json.loads(raw.decode(response.charset_encoding))
    try:
        return json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError:
        return json.loads(raw.decode(_FALLBACK_CHARSET))
