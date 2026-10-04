import assert from "node:assert/strict";
import { test } from "node:test";
import { ESocketTopic } from "@langboard/core/enums";
import { removeStreamErrorCallback, runStreamErrorCallbacks, setStreamErrorCallback } from "./streamErrorCallbacks";

test("stream error callbacks survive repeated errors and independent unsubscription", async () => {
    const calls: string[] = [];
    const first = () => {
        calls.push("first");
    };
    const second = () => {
        calls.push("second");
    };

    setStreamErrorCallback(ESocketTopic.Board, "board:chat:stream", "first", first);
    setStreamErrorCallback(ESocketTopic.Board, "board:chat:stream", "second", second);
    try {
        await runStreamErrorCallbacks(new Event("error"));
        await runStreamErrorCallbacks(new Event("error"));
        assert.deepEqual(calls, ["first", "second", "first", "second"]);

        removeStreamErrorCallback(ESocketTopic.Board, "board:chat:stream", "first");
        await runStreamErrorCallbacks(new Event("error"));
        assert.deepEqual(calls, ["first", "second", "first", "second", "second"]);
    } finally {
        removeStreamErrorCallback(ESocketTopic.Board, "board:chat:stream", "first");
        removeStreamErrorCallback(ESocketTopic.Board, "board:chat:stream", "second");
    }
});
