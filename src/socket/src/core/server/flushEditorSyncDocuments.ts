import { Hocuspocus } from "@hocuspocus/server";

/** Await native serialized persistence after the transport has stopped accepting edits. */
export default async function flushEditorSyncDocuments(instance: Hocuspocus): Promise<void> {
    await Promise.all(
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
}
