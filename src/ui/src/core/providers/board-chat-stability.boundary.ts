const socket = { subscribeTopicNotifier: () => {}, unsubscribeTopicNotifier: () => {}, on: () => {}, off: () => {}, send: () => {}, stream: () => {}, streamOff: () => {} };
export const useSocket = () => socket;
export const useSocketOutsideProvider = () => socket;
export const useAuth = () => ({ currentUser: null });
export const useCollaborativeText = () => ({ isSynced: false, updateValue: () => {} });
