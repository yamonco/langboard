/* eslint-disable @typescript-eslint/no-explicit-any */
import type { TCaptionProps, TImageElement, TResizableProps } from "platejs";
import type { SlateElementProps } from "platejs/static";
import { NodeApi } from "platejs";
import { SlateElement } from "platejs/static";
import { cn } from "@/core/utils/ComponentUtils";
import CachedImage from "@/components/CachedImage";

export function ImageElementStatic(props: SlateElementProps<TImageElement & TCaptionProps & TResizableProps>) {
    const { align = "center", caption, url, width } = props.element;

    return (
        <SlateElement {...props} className="py-2.5">
            <figure className="group relative m-0 inline-block" style={{ width }}>
                <div className="relative min-w-[92px] max-w-full" style={{ textAlign: align }}>
                    <CachedImage
                        className={cn("w-full max-w-full cursor-default object-cover px-0", "rounded-sm")}
                        alt={(props.attributes as any).alt}
                        src={url}
                    />
                    {caption && <figcaption className="mx-auto mt-2 h-[24px] max-w-full">{NodeApi.string(caption[0])}</figcaption>}
                </div>
            </figure>
            {props.children}
        </SlateElement>
    );
}
