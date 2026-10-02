import assert from "node:assert/strict";
import test from "node:test";

import { buildDescriptionChunks } from "./descriptionChunks.ts";
import { buildRailMarkers, getMarkerOpacity, getMarkerWidth, getNearestMarkerIndex, MAX_RAIL_MARKERS } from "./descriptionOverviewRailData.ts";

function createChunks(count: number) {
    return buildDescriptionChunks(Array.from({ length: count }, (_, index) => `# Heading ${index}\n\ncontent ${index}`).join("\n\n"));
}

test("rail preserves chunk indexes up to the marker limit", () => {
    const chunks = createChunks(12);
    const markers = buildRailMarkers(chunks);

    assert.equal(markers.length, chunks.length);
    assert.deepEqual(
        markers.map((marker) => marker.index),
        chunks.map((_, index) => index)
    );
});

test("oversized documents are bucketed while preferring headings", () => {
    const chunks = createChunks(MAX_RAIL_MARKERS * 2);
    const markers = buildRailMarkers(chunks);

    assert.equal(markers.length, MAX_RAIL_MARKERS);
    markers.forEach((marker, bucketIndex) => {
        assert.equal(chunks[marker.index].metadata.type, "heading");
        const bucketSize = Math.ceil(chunks.length / MAX_RAIL_MARKERS);
        assert.deepEqual(marker.range, {
            start: bucketIndex * bucketSize + 1,
            end: Math.min(chunks.length, (bucketIndex + 1) * bucketSize),
        });
    });
});

test("active marker metrics form a compact distance wave", () => {
    assert.equal(getMarkerWidth(0), "w-5");
    assert.equal(getMarkerWidth(4), "w-1.5");
    assert.equal(getMarkerOpacity(0), "opacity-100");
    assert.equal(getMarkerOpacity(8), "opacity-30");
    assert.equal(getNearestMarkerIndex(buildRailMarkers(createChunks(20)), 9), 9);
});
