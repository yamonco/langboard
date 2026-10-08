import { Hocuspocus } from "@hocuspocus/server";

/** Await native serialized persistence after the transport has stopped accepting edits. */
export default async function flushEditorSyncDocuments(instance: Hocuspocus): Promise<void> {
    const results = await Promise.allSettled(
        [...instance.documents.values()]
            .filter((document) => !document.isLoading)
            .map((document) =>
                instance.storeDocumentHooks(
                    document,
                    {
                        document,
                        documentName: document.name,
                        instance,
                        clientsCount: document.getConnectionsCount(),
                        context: {},
                        requestHeaders: {},
                        requestParameters: new URLSearchParams(),
                        socketId: "",
                    },
                    true
                )
            )
    );
    const failures = results.filter((result): result is PromiseRejectedResult => result.status === "rejected");
    if (failures.length) {
        throw new AggregateError(
            failures.map((result) => result.reason),
            "Editor persistence failed during shutdown"
        );
    }
}
