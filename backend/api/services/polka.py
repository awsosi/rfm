"""
Shared helpers for the PolkaSQL (SQL Anywhere 17) web services.

SQL Anywhere answers RAW web services in the database character set,
Windows-1250 on PolkaSQL, unless the client negotiates otherwise.
``httpx.Response.json()`` always decodes UTF-8, so a product name such as
``RĘKAWICZKI 7X000310 AF29587-UC001`` (``Ę`` is byte 0xCA in cp1250) raised
``UnicodeDecodeError`` and was reported as "cannot connect to PolkaSQL".

Do not send ``Accept-Charset``: with ``Accept-Charset: utf-8`` PolkaSQL no
longer matched ``RĘKAWICZKI 104458 0-12L``, which it matches without the
header. Its ``charset=UTF-8`` label is not trusted either.
"""

import json

import httpx

POLKA_HEADERS = {"Accept": "application/json"}

_FALLBACK_CHARSET = "cp1250"


def polka_json(response: httpx.Response):
    """Decode a PolkaSQL JSON body: declared charset (else UTF-8), else cp1250."""
    raw = response.content
    try:
        return json.loads(raw.decode(response.charset_encoding or "utf-8"))
    except UnicodeDecodeError:
        return json.loads(raw.decode(_FALLBACK_CHARSET))
