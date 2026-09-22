from pathlib import Path
import orjson
from langboard.routes.auth.SocketAuthApi import SOCKET_INTERNAL_API_CONTRACT_VERSION
from langboard_shared.core.routing import GLOBAL_TOPIC_ID, NONE_TOPIC_ID, SettingSocketTopicID, SocketTopic


CONTRACT_PATH = Path(__file__).parents[3] / "shared" / "realtime" / "contract.json"


def test_realtime_contract_matches_python_transport_enums() -> None:
    contract = orjson.loads(CONTRACT_PATH.read_bytes())

    assert set(contract["topics"].values()) == {topic.value for topic in SocketTopic}
    assert set(contract["setting_topic_ids"].values()) == {topic_id.value for topic_id in SettingSocketTopicID}
    assert contract["topic_ids"] == {"global": GLOBAL_TOPIC_ID, "none": NONE_TOPIC_ID}
    assert contract["internal_api"] == {
        "capabilities_path": "/auth/socket/capabilities",
        "contract_version": SOCKET_INTERNAL_API_CONTRACT_VERSION,
    }


def test_runtime_inventory_is_scoped_and_unique() -> None:
    contract = orjson.loads(CONTRACT_PATH.read_bytes())
    runtime = contract["runtime"]
    topics = set(contract["topics"].values())

    assert set(runtime["validated_topics"]) == topics - {SocketTopic.Global.value, SocketTopic.NoneTopic.value}
    assert len(runtime["validated_topics"]) == len(set(runtime["validated_topics"]))

    commands = [(command["topic"], command["event"]) for command in runtime["client_commands"]]
    assert all(topic in topics and event for topic, event in commands)
    assert len(commands) == len(set(commands))

    routes = [(route["method"], route["path"]) for route in runtime["http_routes"]]
    assert all(method in {"GET", "POST"} and path.startswith("/") for method, path in routes)
    assert len(routes) == len(set(routes))
    broker_consumers = [(consumer["event"], consumer["purpose"]) for consumer in runtime["broker_consumers"]]
    assert {purpose for _, purpose in broker_consumers} == {"fanout", "side_effect"}
    assert len(broker_consumers) == len(set(broker_consumers))
    assert runtime["editor_sync"]["websocket_path"].startswith("/")
    assert len(runtime["editor_sync"]["lifecycle_hooks"]) == len(set(runtime["editor_sync"]["lifecycle_hooks"]))


def test_broker_envelope_contract_declares_v2_with_legacy_fallback() -> None:
    contract = orjson.loads(CONTRACT_PATH.read_bytes())

    assert contract["broker_envelope"] == {
        "current_schema_version": "2",
        "legacy_cache_key_field": "cache_key",
        "legacy_cache_key_prefix": "broadcast-",
        "legacy_cache_key_max_length": 160,
        "required_fields": ["schema_version", "event_id", "event", "occurred_at", "data"],
    }
    assert contract["dead_letter"] == {
        "schema_version": "1",
        "fanout_topic": "socket_publish_dead_letter",
    }
