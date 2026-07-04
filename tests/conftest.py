"""Test fixtures: an in-memory fake Supabase client.

Supports the subset of the postgrest query-builder chain the backend uses
(select/eq/in_/is_/order/limit/insert/update/upsert/execute + rpc). Enough to
exercise the picks/record and settle logic without a real project.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import pytest

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key-test-key-test-key")


@dataclass
class _Result:
    data: list
    count: int | None = None


class _Query:
    def __init__(self, rows: list[dict]):
        self._rows = list(rows)
        self._filters: list = []
        self._order: list = []
        self._limit: int | None = None

    # filters
    def select(self, *_a, **_k): return self
    def eq(self, col, val): self._filters.append(("eq", col, val)); return self
    def neq(self, col, val): self._filters.append(("neq", col, val)); return self
    def in_(self, col, vals): self._filters.append(("in", col, list(vals))); return self
    def is_(self, col, _val): self._filters.append(("is_null", col, None)); return self
    def gte(self, col, val): self._filters.append(("gte", col, val)); return self
    def lt(self, col, val): self._filters.append(("lt", col, val)); return self
    def like(self, col, val): self._filters.append(("like", col, val)); return self

    def order(self, col, desc=False): self._order.append((col, desc)); return self
    def limit(self, n): self._limit = n; return self

    def _apply(self) -> list[dict]:
        rows = self._rows
        for kind, col, val in self._filters:
            if kind == "eq":
                rows = [r for r in rows if r.get(col) == val]
            elif kind == "neq":
                rows = [r for r in rows if r.get(col) != val]
            elif kind == "in":
                rows = [r for r in rows if r.get(col) in val]
            elif kind == "is_null":
                rows = [r for r in rows if r.get(col) is None]
            elif kind == "gte":
                rows = [r for r in rows if r.get(col) is not None and r.get(col) >= val]
            elif kind == "lt":
                rows = [r for r in rows if r.get(col) is not None and r.get(col) < val]
            elif kind == "like":
                needle = val.replace("%", "")
                rows = [r for r in rows if needle in str(r.get(col) or "")]
        for col, desc in reversed(self._order):
            rows = sorted(rows, key=lambda r: (r.get(col) is None, r.get(col)), reverse=desc)
        if self._limit is not None:
            rows = rows[: self._limit]
        return rows

    def execute(self) -> _Result:
        rows = self._apply()
        return _Result(data=[dict(r) for r in rows], count=len(rows))


class _Table:
    def __init__(self, store: dict, name: str):
        self._store = store
        self._name = name

    def _rows(self) -> list[dict]:
        return self._store.setdefault(self._name, [])

    def select(self, *a, **k): return _Query(self._rows()).select(*a, **k)

    def insert(self, rows):
        rows = rows if isinstance(rows, list) else [rows]
        for r in rows:
            r = dict(r)
            r.setdefault("id", len(self._rows()) + 1)
            self._rows().append(r)
        return _Query(rows)

    def upsert(self, rows, on_conflict=None):
        rows = rows if isinstance(rows, list) else [rows]
        keys = (on_conflict or "").split(",") if on_conflict else []
        for r in rows:
            r = dict(r)
            if keys:
                existing = next(
                    (x for x in self._rows() if all(x.get(k) == r.get(k) for k in keys)), None)
                if existing:
                    existing.update(r)
                    continue
            r.setdefault("id", len(self._rows()) + 1)
            self._rows().append(r)
        return _Query(rows)

    class _Update:
        def __init__(self, table, patch): self.table, self.patch, self.f = table, patch, []
        def eq(self, col, val): self.f.append((col, val)); return self
        def execute(self):
            n = 0
            for r in self.table._rows():
                if all(r.get(c) == v for c, v in self.f):
                    r.update(self.patch); n += 1
            return _Result(data=[], count=n)

    def update(self, patch): return _Table._Update(self, patch)


class FakeSupabaseClient:
    def __init__(self): self._store: dict = {}
    def table(self, name): return _Table(self._store, name)

    def seed(self, name, rows):
        bucket = self._store.setdefault(name, [])
        for r in rows:
            r = dict(r)
            r.setdefault("id", len(bucket) + 1)
            bucket.append(r)

    def rpc(self, name, _params):
        # only refresh_* RPCs are ever called from code under test here
        return _Query([{"refresh": 0}])


@pytest.fixture
def fake_client(monkeypatch):
    client = FakeSupabaseClient()

    def _get_client():
        return client

    # Patch every module that imports get_client at call time.
    import backend.db.client as dbc
    monkeypatch.setattr(dbc, "get_client", _get_client)
    for mod in ("backend.jobs.settle_predictions", "backend.api.routes.picks"):
        import importlib
        m = importlib.import_module(mod)
        if hasattr(m, "get_client"):
            monkeypatch.setattr(m, "get_client", _get_client)
    return client
