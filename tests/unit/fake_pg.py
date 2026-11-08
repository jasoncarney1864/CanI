"""A recording stand-in for a psycopg connection, for unit-testing the vector stores'
SQL without Postgres. Each ``execute`` records the whitespace-normalised statement and
its params, and answers from a queue of row sets. Shared by the two store test modules."""

from __future__ import annotations


class FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class FakeConn:
    def __init__(self, results=None):
        self.calls: list[tuple[str, object]] = []
        self._results = list(results or [])
        self.commits = 0

    def execute(self, sql, params=None):
        self.calls.append((" ".join(sql.split()), params))
        rows = self._results.pop(0) if self._results else []
        return FakeCursor(rows)

    def commit(self):
        self.commits += 1
