# Native notification read scope

`mark_notifications_read` absorbs the plugin's explicit notification scope into
Langboard. `change.scope=one` requires a nonblank `notification_uid`;
`change.scope=all` forbids it. Extra fields and missing scopes are rejected before
any command runs. Querying unread notifications does not mark them read.

The facade is user-only and dispatches through canonical authorized commands.
One-notification ownership and all-notifications receiver filtering remain in
the existing domain service. It returns the native typed `{ "read": true }`
contract. Output validation follows execution and must not imply rollback.

Only invoke this mutation for the scope explicitly requested by the user.
Existing primitive names remain available. This slice does not switch the plugin
routing or prove external OAuth login, consent, refresh or persistence.
