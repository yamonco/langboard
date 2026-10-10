# Native agent policy

Langboard supplies its client-independent instructions through native FastMCP server metadata on compatibility, Agent/Core, Raw and OAuth transports. A client no longer needs the ChatGPT plugin's packaged skill to receive the baseline rules.

The server owns one `AGENT_POLICY` constant. It covers workflow gates, native checklists, requested timer transitions, preserving assignees, local-first label selection, explicit local-label creation, no global-label creation through MCP, revision conflicts, ambiguous mutation failures, directory identity and notification read intent.

Instructions guide agents; domain authorization and validation still enforce access. Metadata does not grant a tool or change legacy ToolGroup permissions. OAuth provisioning remains a separate deployment requirement.

Clients obtain instructions by the legacy initialize handshake or modern discovery negotiation. A client that pins a protocol and skips metadata discovery must fetch server metadata; it cannot receive instructions through a request it does not make.

Verification exercises the actual native server builders and FastMCP clients under legacy and modern discovery, with empty legacy tool grants. The OAuth route fixture additionally verifies that its server receives the same policy. These checks do not establish a live OAuth login, token refresh or business mutation.
