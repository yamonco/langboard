import Flex from "@/components/base/Flex";
import Toast from "@/components/base/Toast";
import MetadataRow from "@/components/MetadataList/MetadataRow";
import { TMetadataForm } from "@/controllers/api/metadata/types";
import useGetMetadata from "@/controllers/api/metadata/useGetMetadata";
import setupApiErrorHandler, { IApiErrorHandlerMap } from "@/core/helpers/setupApiErrorHandler";
import { MetadataModel } from "@/core/models";
import { Utils } from "@langboard/core/utils";
import { useEffect } from "react";

const SYSTEM_METADATA_KEY_PREFIX = "__system.";

export interface IMetadataListProps {
    form: TMetadataForm;
    errorsMap: () => IApiErrorHandlerMap;
    canEdit: () => bool;
}

function MetadataList({ form, errorsMap, canEdit }: IMetadataListProps) {
    const { data, error, isFetching } = useGetMetadata(form);
    const metadata = MetadataModel.Model.useModel((model) => model.type === form.type && model.uid === form.uid, [data, isFetching]);

    useEffect(() => {
        if (!error) {
            return;
        }

        const messageRef = { message: "" };
        const { handle } = setupApiErrorHandler(errorsMap(), messageRef);

        handle(error);
        Toast.Add.error(messageRef.message);
    }, [error]);

    return (
        <>
            {!data || !metadata || isFetching ? (
                <SkeletonMetadataList />
            ) : (
                <MetadataListInner form={form} metadata={metadata} errorsMap={errorsMap} canEdit={canEdit} />
            )}
        </>
    );
}

function SkeletonMetadataList(): React.JSX.Element {
    return <></>;
}

interface IMetadataListInnerProps {
    form: TMetadataForm;
    metadata: MetadataModel.TModel;
    errorsMap: (messageRef: { message: string }) => IApiErrorHandlerMap;
    canEdit: () => bool;
}

function MetadataListInner({ form, metadata: record, errorsMap, canEdit }: IMetadataListInnerProps): React.JSX.Element | null {
    const metadata = record.useField("metadata");

    return (
        <Flex direction="col" gap="2" mt="2" mb="2">
            {Object.entries(metadata)
                .filter(([key]) => !key.startsWith(SYSTEM_METADATA_KEY_PREFIX))
                .map(([key, value]) => (
                    <MetadataRow
                        key={Utils.String.Token.shortUUID()}
                        form={form}
                        keyName={key}
                        value={value}
                        errorsMap={errorsMap}
                        canEdit={canEdit}
                    />
                ))}
        </Flex>
    );
}

export default MetadataList;
