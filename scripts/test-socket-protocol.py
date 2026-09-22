import argparse
import asyncio
import json
import os
from pathlib import Path
from time import monotonic
from urllib.parse import quote
from uuid import uuid4
import websockets
from websockets.exceptions import ConnectionClosed


RECEIVE_TIMEOUT_SECONDS = 5.0
SILENCE_TIMEOUT_SECONDS = 0.25


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the shared raw WebSocket protocol suite")
    parser.add_argument(
        "--target",
        action="append",
        required=True,
        metavar="NAME=URL",
        help="Runtime name and base WebSocket URL; repeat for every runtime",
    )
    parser.add_argument(
        "--max-payload-mb",
        type=int,
        default=int(os.environ.get("SOCKET_MAX_PAYLOAD_MB", "8")),
    )
    return parser.parse_args()


def _parse_targets(values: list[str]) -> list[tuple[str, str]]:
    targets: list[tuple[str, str]] = []
    names: set[str] = set()
    for value in values:
        name, separator, url = value.partition("=")
        if not separator or not name or not url:
            raise ValueError(f"Invalid target {value!r}; expected NAME=URL")
        if name in names:
            raise ValueError(f"Duplicate target name: {name}")
        names.add(name)
        targets.append((name, url.rstrip("/")))
    return targets


def _load_contract() -> dict:
    contract_path = Path(__file__).resolve().parents[1] / "src" / "shared" / "realtime" / "contract.json"
    return json.loads(contract_path.read_text(encoding="utf-8"))


def _read_credentials() -> tuple[str, str]:
    access_token = os.environ.get("SOCKET_PROTOCOL_ACCESS_TOKEN", "")
    user_uid = os.environ.get("SOCKET_PROTOCOL_USER_UID", "")
    if not access_token or not user_uid:
        raise RuntimeError("SOCKET_PROTOCOL_ACCESS_TOKEN and SOCKET_PROTOCOL_USER_UID are required")
    return access_token, user_uid


def _connection_url(base_url: str, token: str | None) -> str:
    if token is None:
        return f"{base_url}/"
    return f"{base_url}/?authorization={quote(token, safe='')}"


async def _connect(base_url: str, token: str | None, max_payload_bytes: int):
    return await websockets.connect(
        _connection_url(base_url, token),
        open_timeout=RECEIVE_TIMEOUT_SECONDS,
        close_timeout=RECEIVE_TIMEOUT_SECONDS,
        max_size=max_payload_bytes * 2,
        ping_interval=None,
    )


async def _receive_json(websocket) -> dict:
    payload = await asyncio.wait_for(websocket.recv(), timeout=RECEIVE_TIMEOUT_SECONDS)
    if not isinstance(payload, str):
        raise AssertionError(f"Expected a text frame, received {type(payload).__name__}")
    frame = json.loads(payload)
    if not isinstance(frame, dict):
        raise AssertionError(f"Expected an object frame, received {frame!r}")
    return frame


async def _assert_silent(websocket, label: str) -> None:
    try:
        payload = await asyncio.wait_for(websocket.recv(), timeout=SILENCE_TIMEOUT_SECONDS)
    except TimeoutError:
        return
    raise AssertionError(f"{label} unexpectedly produced {payload!r}")


async def _assert_close_code(websocket, expected_code: int, label: str) -> None:
    deadline = monotonic() + RECEIVE_TIMEOUT_SECONDS
    try:
        while monotonic() < deadline:
            await asyncio.wait_for(websocket.recv(), timeout=deadline - monotonic())
    except ConnectionClosed as error:
        if error.code != expected_code:
            raise AssertionError(f"{label} closed with {error.code}, expected {expected_code}") from error
        return
    except TimeoutError as error:
        raise AssertionError(f"{label} did not close") from error
    raise AssertionError(f"{label} did not close")


async def _assert_bootstrap(websocket, contract: dict, user_uid: str) -> None:
    expected = [
        {
            "event": contract["events"]["subscribed"],
            "topic": contract["topics"]["global"],
            "topic_id": [contract["topic_ids"]["global"]],
        },
        {
            "event": contract["events"]["subscribed"],
            "topic": contract["topics"]["user_private"],
            "topic_id": [user_uid],
        },
    ]
    actual = [await _receive_json(websocket), await _receive_json(websocket)]
    if actual != expected:
        raise AssertionError(f"Bootstrap frames differ: {actual!r}")


async def _run_valid_frame_suite(
    base_url: str,
    access_token: str,
    user_uid: str,
    contract: dict,
    max_payload_bytes: int,
) -> None:
    events = contract["events"]
    topics = contract["topics"]
    global_topic_id = contract["topic_ids"]["global"]
    foreign_uid = uuid4().hex[: contract["identifiers"]["short_uid_length"]]

    websocket = await _connect(base_url, access_token, max_payload_bytes)
    try:
        await _assert_bootstrap(websocket, contract, user_uid)

        await websocket.send("")
        echoed = await asyncio.wait_for(websocket.recv(), timeout=RECEIVE_TIMEOUT_SECONDS)
        if echoed != "":
            raise AssertionError(f"Empty-frame echo differs: {echoed!r}")

        await websocket.send("{")
        await _assert_silent(websocket, "Malformed JSON")

        await websocket.send(json.dumps({}))
        await _assert_silent(websocket, "Missing event")

        await websocket.send(
            json.dumps(
                {
                    "event": f"protocol:unknown:{uuid4().hex}",
                    "topic": topics["global"],
                    "topic_id": global_topic_id,
                    "data": {},
                }
            )
        )
        await _assert_silent(websocket, "Unknown event")

        await websocket.send(
            json.dumps(
                {
                    "event": events["subscribe"],
                    "topic": topics["user_private"],
                    "topic_id": [foreign_uid],
                }
            )
        )
        denied = await _receive_json(websocket)
        expected_denied = {
            "event": events["subscribed"],
            "topic": topics["user_private"],
            "topic_id": [],
        }
        if denied != expected_denied:
            raise AssertionError(f"Unauthorized subscription response differs: {denied!r}")

        unknown_topic = f"unknown-{uuid4().hex}"
        await websocket.send(
            json.dumps(
                {
                    "event": events["subscribe"],
                    "topic": unknown_topic,
                    "topic_id": [global_topic_id],
                }
            )
        )
        unknown_topic_response = await _receive_json(websocket)
        expected_unknown_topic = {
            "event": events["subscribed"],
            "topic": unknown_topic,
            "topic_id": [],
        }
        if unknown_topic_response != expected_unknown_topic:
            raise AssertionError(f"Unknown-topic response differs: {unknown_topic_response!r}")

        rapid_frames = []
        for _index in range(4):
            rapid_frames.extend(
                [
                    {
                        "event": events["unsubscribe"],
                        "topic": topics["global"],
                        "topic_id": [global_topic_id],
                    },
                    {
                        "event": events["subscribe"],
                        "topic": topics["global"],
                        "topic_id": [global_topic_id],
                    },
                ]
            )
        for frame in rapid_frames:
            await websocket.send(json.dumps(frame))

        expected_events = [events["unsubscribed"], events["subscribed"]] * 4
        actual_events = []
        for expected_event in expected_events:
            frame = await _receive_json(websocket)
            expected_frame = {
                "event": expected_event,
                "topic": topics["global"],
                "topic_id": [global_topic_id],
            }
            if frame != expected_frame:
                raise AssertionError(f"Rapid subscription response differs: {frame!r}")
            actual_events.append(frame["event"])
        if actual_events != expected_events:
            raise AssertionError(f"Rapid subscription order differs: {actual_events!r}")

        await websocket.send(
            json.dumps(
                {
                    "event": events["subscribe"],
                    "topic": topics["global"],
                    "topic_id": [global_topic_id],
                }
            ).encode()
        )
        binary_response = await _receive_json(websocket)
        expected_binary_response = {
            "event": events["subscribed"],
            "topic": topics["global"],
            "topic_id": [global_topic_id],
        }
        if binary_response != expected_binary_response:
            raise AssertionError(f"Binary JSON response differs: {binary_response!r}")
    finally:
        await websocket.close()


async def _run_invalid_subscription_suite(
    base_url: str,
    access_token: str,
    user_uid: str,
    contract: dict,
    max_payload_bytes: int,
) -> None:
    invalid_frames = [
        {"event": contract["events"]["subscribe"], "topic": contract["topics"]["global"]},
        {
            "event": contract["events"]["subscribe"],
            "topic": contract["topics"]["global"],
            "topic_id": 1,
        },
        {
            "event": contract["events"]["unsubscribe"],
            "topic": contract["topics"]["global"],
            "topic_id": [""],
        },
        {
            "event": contract["events"]["subscribe"],
            "topic": contract["topics"]["global"],
            "topic_id": ["x"] * (contract["protocol_limits"]["max_topic_ids"] + 1),
        },
        {
            "event": contract["events"]["subscribe"],
            "topic": contract["topics"]["global"],
            "topic_id": ["x" * (contract["protocol_limits"]["max_topic_id_bytes"] + 1)],
        },
    ]
    expected_code = contract["close_codes"]["invalid_data"]
    for index, frame in enumerate(invalid_frames):
        websocket = await _connect(base_url, access_token, max_payload_bytes)
        try:
            await _assert_bootstrap(websocket, contract, user_uid)
            await websocket.send(json.dumps(frame))
            await _assert_close_code(websocket, expected_code, f"Invalid subscription frame {index}")
        finally:
            await websocket.close()


async def _run_connection_failure_suite(base_url: str, contract: dict, max_payload_bytes: int) -> None:
    for token, expected_code, label in [
        (None, contract["close_codes"]["unauthorized"], "Missing authorization"),
        ("invalid-token", contract["close_codes"]["unauthorized"], "Invalid authorization"),
    ]:
        websocket = await _connect(base_url, token, max_payload_bytes)
        try:
            await _assert_close_code(websocket, expected_code, label)
        finally:
            await websocket.close()


async def _run_oversized_frame_suite(
    base_url: str,
    access_token: str,
    user_uid: str,
    contract: dict,
    max_payload_bytes: int,
) -> None:
    websocket = await _connect(base_url, access_token, max_payload_bytes)
    try:
        await _assert_bootstrap(websocket, contract, user_uid)
        await websocket.send("x" * (max_payload_bytes + 1))
        await _assert_close_code(
            websocket,
            contract["close_codes"]["message_too_big"],
            "Oversized frame",
        )
    finally:
        await websocket.close()


async def _run_target(
    name: str,
    base_url: str,
    access_token: str,
    user_uid: str,
    contract: dict,
    max_payload_bytes: int,
) -> None:
    await _run_valid_frame_suite(base_url, access_token, user_uid, contract, max_payload_bytes)
    await _run_invalid_subscription_suite(base_url, access_token, user_uid, contract, max_payload_bytes)
    await _run_connection_failure_suite(base_url, contract, max_payload_bytes)
    await _run_oversized_frame_suite(base_url, access_token, user_uid, contract, max_payload_bytes)
    print(f"{name} raw WebSocket protocol suite passed", flush=True)


async def _run() -> None:
    args = _parse_args()
    targets = _parse_targets(args.target)
    contract = _load_contract()
    access_token, user_uid = _read_credentials()
    max_payload_bytes = args.max_payload_mb * 1024 * 1024

    for name, base_url in targets:
        await _run_target(name, base_url, access_token, user_uid, contract, max_payload_bytes)


if __name__ == "__main__":
    asyncio.run(_run())
