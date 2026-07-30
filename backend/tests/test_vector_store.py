import unittest
from unittest.mock import patch

from app.services import vector_store


class _FakePointIdsList:
    def __init__(self, points):
        self.points = points


class _FakeVectorParams:
    def __init__(self, *, size, distance):
        self.size = size
        self.distance = distance


class _FakeDistance:
    COSINE = "Cosine"


class _FakeModels:
    PointIdsList = _FakePointIdsList
    VectorParams = _FakeVectorParams
    Distance = _FakeDistance


class _FakeScrollRecord:
    def __init__(self, point_id):
        self.id = point_id


class VectorStoreTest(unittest.TestCase):
    def test_recreate_missing_collection_does_not_purge_local_storage(self):
        class Client:
            def __init__(self):
                self.created = False

            def collection_exists(self, collection_name):
                return self.created

            def create_collection(self, *, collection_name, vectors_config):
                self.created = True

        client = Client()
        with (
            patch.object(vector_store, "get_qdrant_client", return_value=client),
            patch.object(vector_store, "_qdrant_imports", return_value=(None, _FakeModels)),
            patch.object(vector_store, "_purge_local_collection_storage", side_effect=AssertionError("unexpected purge")),
        ):
            vector_store.ensure_vector_collection("missing_collection", recreate=True)

        self.assertTrue(client.created)

    def test_prune_collection_points_deletes_stale_ids(self):
        class Client:
            def __init__(self):
                self.deleted = []

            def collection_exists(self, collection_name):
                return True

            def scroll(self, **kwargs):
                return [_FakeScrollRecord("keep"), _FakeScrollRecord("stale-1"), _FakeScrollRecord("stale-2")], None

            def delete(self, *, collection_name, points_selector, wait):
                self.deleted.extend(points_selector.points)

        client = Client()
        with (
            patch.object(vector_store, "get_qdrant_client", return_value=client),
            patch.object(vector_store, "_qdrant_imports", return_value=(None, _FakeModels)),
        ):
            pruned = vector_store._prune_collection_points("knowledge", {"keep"})

        self.assertEqual(pruned, 2)
        self.assertEqual(client.deleted, ["stale-1", "stale-2"])
