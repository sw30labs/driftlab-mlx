from driftlab.identity import canonical_json, content_hash, deterministic_id, deterministic_uuid, short_hash


def test_canonical_json_is_order_insensitive():
    assert canonical_json({"b": 1, "a": [2, 1]}) == canonical_json({"a": [2, 1], "b": 1})


def test_content_hash_stability():
    payload = {"x": 1, "y": ["a", "b"]}
    assert content_hash(payload) == content_hash(dict(payload))
    assert content_hash(payload) != content_hash({"x": 2, "y": ["a", "b"]})


def test_deterministic_id_prefix_and_stability():
    a = deterministic_id("evt", "key1")
    assert a.startswith("evt_") and len(a) == 4 + 16
    assert a == deterministic_id("evt", "key1")
    assert a != deterministic_id("evt", "key2")


def test_deterministic_uuid_is_uuid5_stable():
    assert deterministic_uuid("anomaly:fp") == deterministic_uuid("anomaly:fp")
    assert deterministic_uuid("anomaly:fp") != deterministic_uuid("anomaly:fp2")


def test_short_hash_length():
    assert len(short_hash("abc", 12)) == 12
