export let session = "a";
export const rows = [{ uid: "cached", chat_session_uid: "a", updated_at: new Date() }];
export function selectSession(value: string) {
    session = value;
}
