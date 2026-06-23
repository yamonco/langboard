import { MetadataModel } from "@/core/models";

export interface IMetadataUpdatedRawResponse {
    key: string;
    value: string;
    old_key?: string;
}

export interface IMetadataDeletedRawResponse {
    keys: string[];
}

export const applyMetadataUpdated = (type: MetadataModel.TType, uid: string, data: IMetadataUpdatedRawResponse) => {
    let metadata = MetadataModel.Model.getModel(uid);
    if (!metadata) {
        metadata = MetadataModel.Model.fromOne(
            {
                uid,
                type,
                metadata: {},
                created_at: new Date(),
                updated_at: new Date(),
            },
            true
        );
    }
    if (metadata.type !== type) {
        return;
    }

    const newMetadata = { ...metadata.metadata };
    if (data.old_key && data.old_key !== data.key) {
        delete newMetadata[data.old_key];
    }
    newMetadata[data.key] = data.value;
    metadata.metadata = newMetadata;
};

export const applyMetadataDeleted = (type: MetadataModel.TType, uid: string, data: IMetadataDeletedRawResponse) => {
    const metadata = MetadataModel.Model.getModel(uid);
    if (!metadata || metadata.type !== type) {
        return;
    }

    const newMetadata = { ...metadata.metadata };
    for (let i = 0; i < data.keys.length; ++i) {
        const key = data.keys[i];
        if (key in newMetadata) {
            delete newMetadata[key];
        }
    }
    metadata.metadata = newMetadata;
};
