import type { TCaptionProps, TImageElement, TResizableProps } from "platejs";
import type { SlateElementProps } from "platejs/static";
import { NodeApi } from "platejs";
import { SlateElement } from "platejs/static";
import { cn } from "@/core/utils/ComponentUtils";
import CachedImage from "@/components/CachedImage";

export function ImageElementStatic(props: SlateElementProps<TImageElement & TCaptionProps & TResizableProps>) {
    const { align = "center", caption, url, width } = props.element;
    const hasExplicitWidth = width !== undefined;

    return (
        <SlateElement {...props} className="py-2.5">
            <figure className="group relative m-0 inline-block max-w-full" style={{ width }}>
                <div className="relative min-w-[92px] max-w-full" style={{ textAlign: align }}>
                    <CachedImage
                        className={cn(
                            "h-auto max-w-full cursor-default object-cover px-0",
                            hasExplicitWidth ? "w-full" : "w-auto max-w-2xl",
                            "rounded-sm"
                        )}
                        alt=""
                        src={url}
                    />
                    {caption && <figcaption className="mx-auto mt-2 h-[24px] max-w-full">{NodeApi.string(caption[0])}</figcaption>}
                </div>
            </figure>
            {props.children}
        </SlateElement>
    );
}
