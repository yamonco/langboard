"""Elapsed budget rejects drip responses despite individual reads succeeding."""

import httpx
import pytest
from langboard.apps import MetadataTransport as transport


@pytest.mark.parametrize("slow", [False, True])
def test_stream_elapsed_budget_closes_response(monkeypatch, slow):
    clock = [0.0]
    closed = []

    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            for chunk in (b'{"safe":', b"true}"):
                clock[0] += 8 if slow else 1
                yield chunk

        def close(self):
            closed.append(True)

    client = httpx.Client
    monkeypatch.setattr(transport, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        transport.httpx,
        "Client",
        lambda **kwargs: client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=Stream())), **kwargs
        ),
    )
    if slow:
        with pytest.raises(transport.MetadataUnavailable):
            transport.read_json("https://deploy.example.invalid", "/api/project.all", {})
    else:
        assert transport.read_json("https://deploy.example.invalid", "/api/project.all", {})[0] == {"safe": True}
    assert closed == [True]
