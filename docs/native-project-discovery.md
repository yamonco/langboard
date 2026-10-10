# Native project discovery

Modern `get_projects` supports an optional title `query` (trimmed, 1–100
characters, Unicode case-insensitive substring match). Search operates only on
the existing authenticated user's authorized project list.

Agent/Core, Raw and native OAuth results use a compact typed summary: UID,
title, project type, star state, current role actions, `project_url` and
`project_link_markdown`. Board bodies and unrelated internal fields are omitted.
Clients need neither the ChatGPT plugin's search/projection code nor a custom
ToolGroup on the native OAuth transport. Compatibility retains its input and
output contract; query is a modern-only parameter.

The existing authorization query still materializes the user's full authorized
project list before filtering. This slice reduces client payload and duplicate
application policy; it does not claim database query latency improvements or
external OAuth deployment acceptance.
