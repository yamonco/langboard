export interface ILinkedResourceProjection<TContent = unknown> {
    uid: string;
    status: "available" | "forbidden" | "missing";
    title?: string;
    preview?: string;
    content?: TContent;
}

export function mergeLinkedResourceProjection<TContent>(
    incoming: ILinkedResourceProjection<TContent>,
    existing?: ILinkedResourceProjection<TContent>
): ILinkedResourceProjection<TContent> {
    const canRetainDetail =
        incoming.status === "available" &&
        existing?.status === "available" &&
        incoming.uid === existing.uid &&
        incoming.content === undefined &&
        existing.content !== undefined;

    if (!canRetainDetail) {
        return incoming;
    }

    return {
        ...incoming,
        preview: incoming.preview ?? existing.preview,
        content: existing.content,
    };
}
