import { forwardRef, memo, useEffect, useRef, useState } from "react";
import { VariantProps, tv } from "tailwind-variants";
import useProtectedImage from "@/core/hooks/useProtectedImage";
import Skeleton from "@/components/base/Skeleton";
import SuspenseComponent from "@/components/base/SuspenseComponent";
import { cn } from "@/core/utils/ComponentUtils";
import { DimensionMap } from "@/core/utils/VariantUtils";

const CachedImageVariants = tv(
    {
        variants: {
            size: DimensionMap.all,
            w: DimensionMap.width,
            h: DimensionMap.height,
        },
        defaultVariants: {
            size: undefined,
            width: undefined,
            height: undefined,
        },
    },
    {
        responsiveVariants: true,
    }
);

interface ICachedImageProps extends React.ImgHTMLAttributes<HTMLImageElement>, VariantProps<typeof CachedImageVariants> {
    fallback?: React.ReactNode;
}

const imageCache = new Map<string, HTMLImageElement>();

const lazyImage = (src: string, cache = true) => {
    return new Promise((resolve, reject) => {
        if (cache && imageCache.has(src)) {
            resolve(imageCache.get(src));
            return;
        }

        const image = new Image();
        image.onload = () => {
            if (cache) imageCache.set(src, image);
            resolve(image);
        };
        image.onerror = reject;
        image.src = src;
    });
};

const CachedImage = memo(
    forwardRef<HTMLImageElement, ICachedImageProps>(({ size, w, h, src, fallback, className, ...props }, ref) => {
        const resolved = useProtectedImage(src);
        const imageSrc = resolved.src;
        const [image, setImage] = useState<React.ReactNode | null>(null);
        const imageKeyRef = useRef(src);
        const renderedSource = useRef<string | undefined>(undefined);

        const classNames = cn(CachedImageVariants({ size, w, h }), className);

        useEffect(() => {
            let disposed = false;
            renderedSource.current = imageSrc;
            setImage(null);
            if (!imageSrc) {
                setImage(fallback ?? null);
                return;
            }

            lazyImage(imageSrc, !resolved.protected)
                .then(() => {
                    if (disposed) return;
                    setImage(
                        <img
                            key={imageKeyRef.current}
                            ref={ref}
                            className={classNames}
                            {...props}
                            src={imageSrc}
                            srcSet={resolved.protected ? undefined : props.srcSet}
                        />
                    );
                })
                .catch(() => {
                    if (!disposed) setImage(fallback ?? <Skeleton className={classNames} />);
                });
            return () => {
                disposed = true;
            };
        }, [imageSrc, resolved.protected]);

        return <SuspenseComponent className={classNames}>{renderedSource.current === imageSrc ? image : null}</SuspenseComponent>;
    }),
    (prev, next) => {
        const checkableProps = ["src", "className", "size", "w", "h"] as const;
        for (let i = 0; i < checkableProps.length; ++i) {
            const key = checkableProps[i];
            if (prev[key] !== next[key]) {
                return false;
            }
        }
        return true;
    }
);

export default CachedImage;
