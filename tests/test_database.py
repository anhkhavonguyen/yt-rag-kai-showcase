"""Database.delete_chunks_except: paged reads, deletes by row id in batches.

A stub stands in for the Supabase client and records every query.
"""

import asyncio

import pytest

from app.core import database
from app.core.database import Database


class StubResult:
    def __init__(self, data):
        self.data = data


class StubQuery:
    """Chainable query builder over an in-memory table that records each request."""

    def __init__(self, client):
        self.client = client
        self.op = None
        self.range_ = None
        self.ids = None

    def select(self, columns):
        self.op = "select"
        return self

    def order(self, column):
        return self

    def range(self, start, end):
        self.range_ = (start, end)
        return self

    def delete(self):
        self.op = "delete"
        return self

    def in_(self, column, values):
        assert column == "id"
        self.ids = list(values)
        return self

    def execute(self):
        if self.op == "select":
            start, end = self.range_
            self.client.reads.append(self.range_)
            return StubResult([dict(row) for row in self.client.rows[start:end + 1]])
        if self.op == "delete":
            if self.client.fail_delete:
                raise RuntimeError("delete failed")
            self.client.deletes.append(self.ids)
            wanted = set(self.ids)
            self.client.rows = [row for row in self.client.rows if row["id"] not in wanted]
            return StubResult([])
        raise AssertionError(f"unexpected query {self.op}")


class StubClient:
    def __init__(self, chunk_ids):
        self.rows = [{"id": i + 1, "chunk_id": chunk_id} for i, chunk_id in enumerate(chunk_ids)]
        self.reads: list[tuple[int, int]] = []
        self.deletes: list[list[int]] = []
        self.fail_delete = False

    def table(self, name):
        assert name == "rag_chunks"
        return StubQuery(self)


def database_with(stub: StubClient) -> Database:
    db = Database()
    db.get_client = lambda admin=True: stub
    return db


def test_reads_every_page_and_deletes_in_batches_of_100():
    chunk_ids = [f"old{i}#1" for i in range(1050)]
    keep = {"old3#1", "old1049#1"}
    stub = StubClient(chunk_ids)

    removed = asyncio.run(database_with(stub).delete_chunks_except(keep))

    assert stub.reads == [(0, 999), (1000, 1999)]
    assert removed == 1048
    assert all(len(batch) <= 100 for batch in stub.deletes)
    assert sum(len(batch) for batch in stub.deletes) == 1048
    assert [row["chunk_id"] for row in stub.rows] == ["old3#1", "old1049#1"]


def test_chunk_ids_with_special_characters_are_kept_or_deleted_correctly():
    stub = StubClient(["a,b#1", "c(d)#1", "kai_overview_v1#1", "e#f#1"])

    removed = asyncio.run(database_with(stub).delete_chunks_except(["c(d)#1", "kai_overview_v1#1"]))

    assert removed == 2
    assert [row["chunk_id"] for row in stub.rows] == ["c(d)#1", "kai_overview_v1#1"]
    assert stub.deletes == [[1, 4]]  # integer row ids, never chunk IDs


def test_no_delete_request_when_everything_is_kept():
    stub = StubClient(["a#1", "b#1"])

    removed = asyncio.run(database_with(stub).delete_chunks_except({"a#1", "b#1", "c#1"}))

    assert removed == 0
    assert stub.deletes == []
    assert stub.reads == [(0, 999)]


def test_empty_table():
    stub = StubClient([])

    assert asyncio.run(database_with(stub).delete_chunks_except({"a#1"})) == 0
    assert stub.deletes == []


def test_a_failed_delete_is_raised():
    stub = StubClient(["a#1", "b#1"])
    stub.fail_delete = True

    with pytest.raises(RuntimeError):
        asyncio.run(database_with(stub).delete_chunks_except({"a#1"}))


def test_page_and_batch_sizes():
    assert database.READ_PAGE_SIZE == 1000
    assert database.DELETE_BATCH_SIZE == 100
