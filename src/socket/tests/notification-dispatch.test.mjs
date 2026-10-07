import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { stripTypeScriptTypes } from 'node:module';
import { runInNewContext } from 'node:vm';
import test from 'node:test';

const source = readFileSync(new URL('../src/consumers/NotificationConsumer.ts', import.meta.url), 'utf8');
const helper = source.slice(source.indexOf('const refreshDispatchRecipient'), source.indexOf('Consumer.register'));
const load = (get) => runInNewContext(stripTypeScriptTypes(helper + '\nrefreshDispatchRecipient;', { mode: 'strip' }), {
    api: { get }, API_INTERNAL_URL: 'http://internal.invalid',
    SnowflakeID: class { constructor(value) { this.value = value; } },
    createOneTimeToken: () => 'test-only',
});
const model = () => ({ source_notification_persisted: true, notification: { receiver_id: '123' },
    api_notification: { uid: 'abc' }, target_user: { email: 'old@example.invalid' }, email_formats: {} });

test('current recipient replaces queued email and locale after authorization', async () => {
    let calls = 0;
    const refresh = load(async (url, options) => {
        ++calls;
        assert.equal(url, 'http://internal.invalid/notifications/abc/dispatch-context');
        assert.equal(options.timeout, 5000);
        return { data: { allowed: true, recipient: { email: 'current@example.invalid', preferred_lang: 'ko', firstname: 'Current' } } };
    });
    const queued = model();
    assert.equal(await refresh(queued), true);
    assert.equal(queued.target_user.email, 'current@example.invalid');
    assert.equal(queued.email_formats.recipient, 'Current');
    assert.equal(calls, 1);
});

test('revoked and unavailable authorization fail closed', async () => {
    for (const get of [async () => ({ data: { allowed: false } }), async () => { throw new Error('unavailable'); }]) {
        assert.equal(await load(get)(model()), false);
    }
});

test('legacy unpersisted queue cannot publish without durable source', async () => {
    let calls = 0;
    const queued = model();
    queued.source_notification_persisted = false;
    assert.equal(await load(async () => { ++calls; })(queued), false);
    assert.equal(calls, 0);
});
