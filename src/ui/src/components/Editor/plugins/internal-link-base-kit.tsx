import { BaseInternalLinkInputPlugin, BaseInternalLinkPlugin } from "@/components/Editor/plugins/customs/internal-link/InternalLinkPlugin";
import { InternalLinkElementStatic, InternalLinkInputElementStatic } from "@/components/plate-ui/internal-link-node-static";

export const BaseInternalLinkKit = [
    BaseInternalLinkPlugin.configure({
        options: { triggerPreviousCharPattern: /^$|^[\s"']$/ },
    }).withComponent(InternalLinkElementStatic),
    BaseInternalLinkInputPlugin.withComponent(InternalLinkInputElementStatic),
];
