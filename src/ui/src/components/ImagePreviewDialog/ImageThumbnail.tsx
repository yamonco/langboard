import CachedImage from "@/components/CachedImage";
import ImagePreviewDialog from "@/components/ImagePreviewDialog";
import { cn } from "@/core/utils/ComponentUtils";
import { useState, type ImgHTMLAttributes } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";

export default function ImageThumbnail({ className, alt, src, ...props }: ImgHTMLAttributes<HTMLImageElement>) {
    const [t] = useTranslation();
    const [isOpened, setIsOpened] = useState(false);
    if (!src) return null;
    const label = alt || t("editor.Image");
    return (
        <>
            <button type="button" className="block max-w-full cursor-zoom-in" aria-label={label} onClick={() => setIsOpened(true)}>
                <CachedImage
                    {...props}
                    src={src}
                    alt={alt ?? ""}
                    className={cn(className, "h-auto max-h-[min(60vh,24rem)] w-auto max-w-full object-contain")}
                />
            </button>
            {isOpened &&
                createPortal(
                    <ImagePreviewDialog files={[{ name: label, url: src, type: "image/*" }]} initialIndex={0} onClose={() => setIsOpened(false)} />,
                    document.body
                )}
        </>
    );
}
