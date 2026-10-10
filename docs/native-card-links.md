# Native card links

Modern Agent/Core, Raw and OAuth providers return `card_url` and
`card_link_markdown` from `get_card_bundle`, including continuation reads.
Independent MCP clients can display the same browser shortcut without a plugin
or a user-created ToolGroup on the native OAuth transport.

Links use the deployment's public UI URL and encoded project/card path segments.
They are generated only after the existing authorized read succeeds. A URL does
not grant access. Compatibility providers retain their previous output schema.

This removes the plugin dependency for card-read shortcuts. Project and creation
shortcuts, embedded Apps and authenticated native OAuth deployment parity remain
separate acceptance work.
