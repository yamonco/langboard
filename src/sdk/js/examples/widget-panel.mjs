// Include <main id="app"></main> and configure the approved Langboard origin.
// Run inside an approved native rail panel; no theme, CSS or React setup needed.
import { connectPanel } from '../index.mjs';

export async function mountDraftPanel(expectedHostOrigin) {
    const session = await connectPanel({ expectedHostOrigin });
    const widgets = await session.widgets;
    if (!widgets) throw new Error('This host does not provide native panel widgets');
    const element = document.querySelector('#app');
    if (!element || session.signal.aborted) throw new Error('Panel mount unavailable');
    const unmount = widgets.mountNote(element, {
        label: 'Draft', saveLabel: 'Save draft',
        value: session.state?.draft ?? '',
        status: session.state ? 'Restored' : 'Ready',
        onSave(draft) { session.saveState({ draft }); },
    });
    session.signal.addEventListener('abort', unmount, { once: true });
    return session;
}
