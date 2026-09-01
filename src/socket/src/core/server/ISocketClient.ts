import User from "@/models/User";
import { ESocketTopic } from "@langboard/core/enums";

export type TSocketSendParams<TData = unknown> = { event: string; topic: ESocketTopic | string; topic_id?: string | string[]; data?: TData };

interface ISocketClient {
    get user(): User;
    subscribe(topic: ESocketTopic | string, topicId: string | string[]): Promise<void>;
    unsubscribe(topic: ESocketTopic | string, topicId: string | string[]): Promise<void>;
    send<TData = unknown>(event: TSocketSendParams<TData>): void;
    registerCloseHandler(handler: () => void): () => void;
    onClose(): void;
}

export default ISocketClient;
