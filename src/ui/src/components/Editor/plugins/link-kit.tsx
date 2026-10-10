"use client";

import { LinkPlugin } from "@platejs/link/react";
import { isUrl } from "platejs";
import { secretReferenceHistoryHref } from "@/core/utils/SecretReferenceLink";
import { LinkElement } from "@/components/plate-ui/link-node";
import { LinkFloatingToolbar } from "@/components/plate-ui/link-toolbar";

export const LinkKit = [
    LinkPlugin.configure({
        options: {
            allowedSchemes: ["http", "https", "mailto", "tel", "secret"],
            isUrl: (url) => !!secretReferenceHistoryHref(url) || (!url.startsWith("secret:") && isUrl(url)),
        },
        render: {
            node: LinkElement,
            afterEditable: () => <LinkFloatingToolbar />,
        },
    }),
];
