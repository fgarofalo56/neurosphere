from neurosphere_workers.runtime import CheckpointStore, InMemoryCheckpointStore


async def test_in_memory_store_satisfies_protocol() -> None:
    store = InMemoryCheckpointStore()
    assert isinstance(store, CheckpointStore)


async def test_get_missing_returns_none_and_commit_roundtrips() -> None:
    store = InMemoryCheckpointStore()
    assert await store.get("p0") is None
    await store.commit("p0", "10")
    await store.commit("p1", "7")
    assert await store.get("p0") == "10"
    assert await store.get("p1") == "7"
    await store.commit("p0", "11")
    assert await store.get("p0") == "11"


async def test_instances_are_isolated() -> None:
    a, b = InMemoryCheckpointStore(), InMemoryCheckpointStore()
    await a.commit("p", "1")
    assert await b.get("p") is None
