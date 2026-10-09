# @langboard/app-panel 0.1.0

Zero runtime dependency ESM protocol for an isolated Langboard app panel. Import
`index.mjs`; ESM declarations live in `index.d.mts` with an `index.d.ts` compatibility export. Run `npm test` and `npm run example`
in this directory with Node 22 or newer. Tests use native Node MessageChannel;
the executable example uses frame/window doubles and is not browser proof.

## Host integration

Revalidate `GET /board/{project_uid}/apps/{app_key}/panel` under current board
permission and consent before creating each frame. Cache snapshots never grant
rendering rights. Create one selected visible iframe, set `sandbox` to exactly
`allow-scripts allow-forms` and `referrerPolicy` to `no-referrer` before assigning
its URL, and call `createPanelHost` once on load. The SDK also enforces these
attributes, but applying them after navigation is insufficient. Do not recreate a
live frame on ordinary UI rerenders. Recreate when URL, revisions or identity
changes. Keep initialization limited to the four context fields; it must contain
no credentials or card body.

```js
import { createPanelHost, PanelStateCache } from './index.mjs';
const cache = new PanelStateCache(); // One session-level cache, shared by all identities.
const key = JSON.stringify([userUid, projectUid, appKey, appVersion]);
const dispose = createPanelHost({
    frame,
    context: { project_uid: projectUid, app_key: appKey, app_version: appVersion, language },
    state: cache.get(key),
    onState: state => cache.set(key, state),
    onReady: () => showLoadedStatus(),
    onClose: () => closeRail(),
    onError: error => { cache.delete(key); showPanelError(error); },
});
```

Call the returned idempotent `dispose()` on rail close, hidden document,
app/context/board/account switch and logout. It sends best-effort `dispose`, closes
the channel and removes the frame independently. Abort pending host requests as
part of the same teardown. Clear the entire cache on account switch/logout;
delete the affected app's keys on revocation or authorization errors. A caller
must track the keys belonging to that app when retaining several app versions.
No inactive frames, global polling, or automatic reload/replay on ready timeout.
The ready timeout is ten seconds. Only `ready`, `state`, and `close`, version 1,
are handled on the private port; snapshots are ignored until ready.

## App integration

```js
import { connectPanel } from './index.mjs';
const panel = await connectPanel({
    expectedHostOrigin: 'https://board.example',
    onShow: session => renderDraft(session.state),
    onDispose: () => releaseResources(),
});
editor.addEventListener('input', () => panel.saveState({ draft: editor.value }), {
    signal: panel.signal,
});
// Use panel.signal for fetch as well. Explicitly clear any timers in onDispose.
// panel.close() asks the host to close; panel.dispose() releases local resources.
```

The origin must be an exact HTTP(S) origin, including a nondefault port when
present, with no path/trailing slash and never `*`. Bootstrap accepts only a
message whose source is the actual parent and whose origin matches that string.
A successful connection removes the window bootstrap listener. The host must
use `*` for the initial transfer because the sandboxed child has an opaque
origin; this does not weaken the client's validation of the host origin.
`connectPanel` rejects after ten seconds without a valid init. Each session
supplies an AbortSignal and an idempotent dispose callback; `pagehide` also
releases an established client session. Unresponsive scripts can miss callbacks,
so essential host cleanup remains independent.

Save draft snapshots incrementally. `saveState` validates and updates the local
`session.state` immediately. The first write can send synchronously; later writes
send at most once every 150 ms and coalesce into one pending latest snapshot.
After rapid editing pauses, the latest snapshot reaches the host on that timer.
Disposal cancels the pending timer and discards the pending snapshot; there is
no hide-time flush guarantee. `saveState` is not an acknowledgement that the host
accepted a snapshot. The host budgets eight state message attempts in any rolling
second before validation, counting invalid messages too; excess attempts are dropped. State is a JSON object capped at
16 KiB measured as UTF-8 serialized JSON. Validation rejects unsupported
prototypes, accessors, functions, nonfinite numbers, cycles and prototype keys;
complexity is bounded at 64 nesting levels and 16,384 visited values. Returned
and cached snapshots are copies. This channel supplies no business-write/outbox
API, credentials or execution authority. State must contain only disposable UI
drafts, never secrets or business execution queues.

## Session cache and lifecycle sources

`PanelStateCache.get(key)` returns a copied snapshot or `null` and refreshes LRU
order; `set(key, state)`, `delete(key)` and `clear()` manage session memory.
Namespace keys with `JSON.stringify([userUid, boardUid, appKey, appVersion])` to
avoid separator collisions. Limits are global across identities: 32 entries and
256 KiB of serialized snapshot bytes; keys are independently capped at 1 KiB.
Oldest entries are evicted until both bounds hold. No browser storage is used.
Draft survival covers close/reopen within the current session only.

Adobe's [UXP lifecycle guidance](https://developer.adobe.com/uxp/guides/how-to/add-lifecycle-hooks/)
describes initialization, persistence and resource release, and warns that hide
or destroy callbacks can be unreliable in some hosts. Adobe XD's
[panel reference](https://developer.adobe.com/xd/uxp/develop/reference/ui/panels/)
describes show/hide/update; its [update callback guidance](https://adobexdplatform.com/plugin-docs/reference/ui/panels/update.html)
(legacy reference) asks callbacks to return quickly because they run for many user actions. These
principles motivate incremental draft storage, focused callbacks, and explicit
host teardown here. This browser SDK does not implement Adobe APIs or claim
Adobe host lifecycle guarantees.

## Browser example and service headers

Run `node examples/serve.mjs`, then open
`http://127.0.0.1:8769/examples/host.html`. This example runs the actual SDK in an
opaque sandboxed iframe and lets you save a draft, close, reopen and clear the
session. It exercises the protocol; it does not grant a real board permission.
Panel module assets must supply appropriate CORS headers because an iframe
without `allow-same-origin` has an opaque origin. The local example server permits
public assets with `Access-Control-Allow-Origin: *`; do not use it as a production
API or send credentials through it. Production apps must configure their approved
Langboard host origin for `connectPanel`. Panel services must permit approved
hosts in their CSP `frame-ancestors` and avoid incompatible `X-Frame-Options`.

## Automatic Langboard design and widgets

The native rail host supplies its current semantic theme and approved shared
resources during connection. `connectPanel` applies tokens, light/dark class and
`color-scheme`, loads the existing host stylesheet and exposes actual wrapped
Langboard widgets through `session.widgets`. Plugin authors do not install another
theme, copy widget CSS or provide a theme picker. Use exports from one supplied
widget module together; it owns a single React runtime for those widgets.

```js
const session = await connectPanel({ expectedHostOrigin: configuredHostOrigin });
const widgets = await session.widgets;
if (!widgets) throw new Error('This host does not supply panel widgets');
const unmount = widgets.mountNote(document.querySelector('#app'), {
    label: 'Draft', saveLabel: 'Save draft', value: session.state?.draft ?? '',
    onSave(draft) { session.saveState({ draft }); },
});
session.signal.addEventListener('abort', unmount, { once: true });
```

See [`examples/widget-panel.mjs`](examples/widget-panel.mjs) for an app-side
mount using the host resources without CSS or React setup.

The module also exports the host's `Button`, `Textarea`, `Badge`, `React`,
`createRoot` and `mount`. These are wrappers/exports of existing components, not
separate styling implementations. Advanced apps can compose their own content
using the supplied React and widgets. Additional shared widgets should be added
at this common entry after assessing their dependencies and bundle cost.

Theme changes travel over the private MessagePort without remounting the panel.
Only allowlisted existing HSL semantic colors and radius are accepted; arbitrary
CSS text, URLs in tokens, scripts and permissions are excluded. Bootstrap module
and CSS URLs must share the exact configured host origin, use HTTPS (HTTP only
for localhost development), and contain no embedded credentials or fragment.
Live design updates cannot change resource URLs. Resource load failures reject
`session.widgets`; apps should display an unavailable state and respect the abort
signal. The SDK removes the stylesheet and restores prior appearance on disposal.

Host resources use content-hashed URLs from `/panel-sdk-resources.json` and public
immutable caching. The manifest is refreshed when opening a panel. The shared
stylesheet is the existing generated UI CSS, not a plugin-specific copied theme.
A separate iframe still owns its own DOM/React instance; this is resource and
visual reuse, not shared execution across security boundaries. Neither the design
channel nor the widget module receives credentials or business write authority.

For native UI development, build the UI once before opening an app panel. Vite's
resource endpoint serves compiled widgets from its configured output directory;
source transforms with React Refresh are not executed in opaque panel frames.
If no prior compiled manifest exists, the endpoint returns 503 with the build
requirement. Rebuild after widget changes. Production uses hashed resources from
its current build and retains previous release assets for already-open sessions.
