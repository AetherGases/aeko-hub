"""Query-aware doubles for the small slice of pymongo the repositories use.

The concrete repositories only need `find`, `find_one`, `insert_one` and
`update_one`. These doubles record every call so tests can assert on the
filters and update documents the query helpers build, without running Mongo.
"""


class StubCollection:
    def __init__(self, find_one_result=None, find_one_results=None, find_result=None, error=None, inserted_id="inserted-id"):
        self.find_one_result = find_one_result
        self.find_one_results = list(find_one_results) if find_one_results is not None else None
        self.find_result = list(find_result or [])
        self.error = error
        self.inserted_id = inserted_id
        self.calls = []
        self.find_options = []

    def _record(self, name, *args):
        self.calls.append((name, *args))
        if self.error is not None:
            raise self.error

    def find(self, query=None, projection=None, **options):
        # `sort` and `limit` travel beside the recorded call rather than in it:
        # the callers that read `call_args("find")` unpack exactly two values.
        self.find_options.append(options)
        self._record("find", query, projection)
        return iter(self.find_result)

    def find_one(self, query=None, projection=None):
        self._record("find_one", query, projection)
        if self.find_one_results:
            return self.find_one_results.pop(0)
        return self.find_one_result

    def insert_one(self, document):
        self._record("insert_one", document)
        return type("InsertOneResult", (), {"inserted_id": self.inserted_id})()

    def update_one(self, query, update):
        self._record("update_one", query, update)
        return type("UpdateResult", (), {"modified_count": 1})()

    def call_args(self, name):
        return [call[1:] for call in self.calls if call[0] == name]


class StubDatabase:
    """Supports both `db["collection"]` and `db.collection` access."""

    def __init__(self, **collections):
        self.collections = dict(collections)

    def __getitem__(self, name):
        return self.collections.setdefault(name, StubCollection())

    def __getattr__(self, name):
        if name == "collections":
            raise AttributeError(name)
        return self[name]
