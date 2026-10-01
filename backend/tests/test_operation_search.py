"""
Operation history search: every word must appear in the catalog path or the
user name. Prod, 2026-10-01: "BUTY FU" listed every BUTY catalog (fuzzy OR
match, sorted by date), so the two that were wanted got lost among them.
"""

import re
from types import SimpleNamespace

import pytest

from api.services.elasticsearch_service import ElasticsearchService, search_terms

OPERATIONS = [
    (1935, "A:/DO KATALOGU/Natalia/BUTY CHELSEA PERF BOOT 0-BROWN OTH SUEDE OTHER PRINT", "mizn"),
    (1933, "A:/DO KATALOGU/Natalia/BUTY 1203A537 0-026", "mizn"),
    (1895, "A:/DO KATALOGU/Natalia/BUTY KI0437 M-CREWHT PRLOIN KHATHR", "mizn"),
    (1747, "A:/DO KATALOGU/Natalia/BUTY FU1479 A00VLMPMB-900", "mizn"),
    (1745, "A:/DO KATALOGU/Natalia/BUTY FU1569 A00BSTSV2-801", "mizn"),
    (1741, "A:/DO KATALOGU/Lena/BUTY CARTER W093FF-DARK BROWN", "vzle"),
    (1607, "A:/DO KATALOGU/Lena/SKARPETY JV7410 0-WHITE", "vzle"),
    (1500, "A:/DO KATALOGU/Lena/SZALIK 1*2?3 TEST", "vzle"),
]


def _wildcard_regex(pattern):
    """Elasticsearch wildcard syntax: * and ? are wildcards, backslash escapes."""
    out, i = "", 0
    while i < len(pattern):
        c = pattern[i]
        if c == "\\":
            i += 1
            out += re.escape(pattern[i])
        elif c == "*":
            out += ".*"
        elif c == "?":
            out += "."
        else:
            out += re.escape(c)
        i += 1
    return re.compile(out, re.IGNORECASE | re.DOTALL)


def _matches(query, doc):
    """Evaluate the bool/wildcard query the service builds against one document."""
    if "match_all" in query:
        return True
    for clause in query["bool"]["must"]:
        if "term" in clause:
            (field, value), = clause["term"].items()
            if doc.get(field) != value:
                return False
            continue
        hits = 0
        for should in clause["bool"]["should"]:
            (field, spec), = should["wildcard"].items()
            value = doc.get(field.removesuffix(".keyword"))
            hits += bool(value and _wildcard_regex(spec["value"]).fullmatch(value))
        if hits < clause["bool"]["minimum_should_match"]:
            return False
    return True


@pytest.fixture
def search(monkeypatch):
    docs = [
        {"operation_id": op_id, "source_path": path, "user_name": user,
         "operation_type": "PUSH", "status": "COMPLETED"}
        for op_id, path, user in OPERATIONS
    ]

    class FakeClient:
        async def search(self, index, query, from_, size, sort):
            hits = [{"_source": dict(d), "_score": 1.0} for d in docs if _matches(query, d)]
            return {"hits": {"total": {"value": len(hits)}, "hits": hits}}

    monkeypatch.setattr(ElasticsearchService, "is_enabled", property(lambda self: True))
    service = ElasticsearchService()
    service._client = FakeClient()

    async def run(q, **filters):
        result = await service.search_operations(query=q, filters=filters or None)
        return sorted((h["operation_id"] for h in result["hits"]), reverse=True)

    return run


@pytest.mark.parametrize("q, expected", [
    ("BUTY FU", [1747, 1745]),            # the reported search
    ("buty fu", [1747, 1745]),            # any case
    ("FU1479", [1747]),
    ("FU BUTY", [1747, 1745]),            # any word order
    ("  BUTY   FU1569 ", [1745]),         # extra spaces
    ("BUTY vzle", [1741]),                # path and user name together
    ("mizn", [1935, 1933, 1895, 1747, 1745]),
    ("BUTY XYZ", []),                     # every word must be there, no fuzzy
    ("1*2?3", [1500]),                    # * and ? are literal
    ("1?3", []),
])
async def test_every_word_must_appear(search, q, expected):
    assert await search(q) == expected


async def test_filters_still_apply(search):
    assert await search("BUTY FU", status="FAILED") == []


def test_search_terms():
    assert search_terms(" BUTY  FU ") == ["BUTY", "FU"]
    assert search_terms("") == search_terms(None) == []
