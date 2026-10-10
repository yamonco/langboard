/** Late-loading chunk stand-in; only used to suspend a root-level Suspense boundary. */
export default function CardViewerDeepLinkLateChunkFixture(): React.JSX.Element {
    return <div data-fixture-late-chunk="" />;
}
