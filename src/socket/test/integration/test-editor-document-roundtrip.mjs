import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createRequire } from "node:module";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const require = createRequire(
  new URL("../../../ui/package.json", import.meta.url),
);
const Y = require("yjs");

const directory = process.argv[2];
assert.ok(directory, "An editor document directory is required");

const files = readdirSync(directory)
  .filter((name) => name.endsWith(".ydoc"))
  .sort();
assert.ok(files.length > 0, "No editor documents were found");

const documents = files.map((name) => {
  const document = new Y.Doc();
  Y.applyUpdate(document, readFileSync(join(directory, name)));
  return document;
});

try {
  const updates = documents.map((document) =>
    Buffer.from(Y.encodeStateAsUpdate(document)).toString("base64"),
  );
  const elixir = process.platform === "win32" ? "elixir.bat" : "elixir";
  const output = execFileSync(
    elixir,
    [
      "-S",
      "mix",
      "run",
      "--no-start",
      "test/integration/editor_document_roundtrip.exs",
    ],
    {
      cwd: new URL("../../", import.meta.url),
      input: JSON.stringify(updates),
      encoding: "utf8",
      maxBuffer: 16 * 1024 * 1024,
      shell: process.platform === "win32",
    },
  );
  const roundtripped = JSON.parse(output.trim());
  assert.equal(roundtripped.length, files.length);

  for (let index = 0; index < files.length; index++) {
    const restored = new Y.Doc();
    try {
      Y.applyUpdate(restored, Buffer.from(roundtripped[index], "base64"));
      assert.deepEqual(
        Y.encodeStateVector(restored),
        Y.encodeStateVector(documents[index]),
        files[index],
      );
      assert.deepEqual(
        Y.encodeStateAsUpdate(restored),
        Y.encodeStateAsUpdate(documents[index]),
        files[index],
      );
    } finally {
      restored.destroy();
    }
  }
  console.log(`Editor Yjs/Yex roundtrip: ${files.length} documents matched`);
} finally {
  for (const document of documents) document.destroy();
}
