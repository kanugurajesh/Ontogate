import time

from ontogate.runtime.cache import CACHE_MISS, Cache


def test_miss_then_hit():
    cache = Cache()
    key = Cache.make_key("lookup_user", {"user_id": "user:bob"})
    assert cache.get(key) is CACHE_MISS
    cache.set(key, {"id": "user:bob"})
    assert cache.get(key) == {"id": "user:bob"}


def test_key_is_stable_regardless_of_arg_order():
    k1 = Cache.make_key("t", {"a": 1, "b": 2})
    k2 = Cache.make_key("t", {"b": 2, "a": 1})
    assert k1 == k2


def test_different_args_produce_different_keys():
    k1 = Cache.make_key("t", {"a": 1})
    k2 = Cache.make_key("t", {"a": 2})
    assert k1 != k2


def test_ttl_expiry():
    cache = Cache()
    key = Cache.make_key("t", {})
    cache.set(key, "value", ttl_seconds=0.01)
    assert cache.get(key) == "value"
    time.sleep(0.02)
    assert cache.get(key) is CACHE_MISS


def test_cached_none_is_distinguishable_from_miss():
    cache = Cache()
    key = Cache.make_key("t", {})
    cache.set(key, None)
    assert cache.get(key) is None
    assert cache.get(key) is not CACHE_MISS
