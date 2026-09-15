import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import Input from "@/components/base/Input";
import Label from "@/components/base/Label";
import CachedImage from "@/components/CachedImage";
import { useEffect, useMemo, useState } from "react";
import mimeTypes from "react-native-mime-types";
import { DismissableLayer } from "@radix-ui/react-dismissable-layer";
import { useTranslation } from "react-i18next";

export type FileItem = {
    url: string;
    type: string;
};

interface ImagePreviewDialogProps {
    files: { name: string; url: string; type?: string }[];
    initialIndex: number;
    onClose: () => void;
}

const ImagePreviewDialog = ({ files, initialIndex, onClose }: ImagePreviewDialogProps) => {
    const [t] = useTranslation();
    const [currentIndex, setCurrentIndex] = useState(initialIndex);
    const [zoom, setZoom] = useState(1);
    const currentFile = useMemo(() => files[currentIndex], [files, currentIndex]);
    const currentFileUrl = useMemo(() => currentFile?.url, [currentFile]);
    const currentFileName = useMemo(() => currentFile?.name, [currentFile]);
    const mimeType = useMemo(() => currentFile?.type || (!!currentFile && mimeTypes.lookup(currentFile.url)), [currentFile]);
    const updateZoom = (type: "in" | "out") => {
        setZoom((prev) => {
            if (type === "in") {
                return Math.min(prev + 0.1, 1.5);
            } else {
                return Math.max(prev - 0.1, 0.5);
            }
        });
    };

    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent) => {
            if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Escape"].includes(e.key)) return;
            e.preventDefault();
            e.stopPropagation();

            if (e.key === "ArrowLeft") {
                goPrev();
            } else if (e.key === "ArrowRight") {
                goNext();
            } else if (e.key === "ArrowUp") {
                updateZoom("in");
            } else if (e.key === "ArrowDown") {
                updateZoom("out");
            } else if (e.key === "Escape") {
                onClose();
            }
        };

        window.addEventListener("keydown", handleKeyDown);

        return () => {
            window.removeEventListener("keydown", handleKeyDown);
        };
    }, [currentIndex, files]);

    const handleWheel = (e: React.WheelEvent<HTMLDivElement>) => {
        if (e.deltaY < 0) {
            updateZoom("in");
        } else {
            updateZoom("out");
        }
    };

    const handleDrag = (e: React.DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
    };

    const goPrev = () => {
        if (currentIndex - 1 >= 0) {
            setCurrentIndex(currentIndex - 1);
            setZoom(1);
        } else {
            setCurrentIndex(files.length - 1);
            setZoom(1);
        }
    };

    const goNext = () => {
        if (currentIndex + 1 <= files.length - 1) {
            setCurrentIndex(currentIndex + 1);
            setZoom(1);
        } else {
            setCurrentIndex(0);
            setZoom(1);
        }
    };

    return (
        <DismissableLayer disableOutsidePointerEvents>
            <Flex
                role="dialog"
                aria-label={t("editor.Image")}
                items="center"
                justify="center"
                position="fixed"
                z="50"
                className="inset-0 overflow-hidden bg-opacity-50 backdrop-blur-sm"
                onWheel={handleWheel}
                onClick={onClose}
            >
                <Box
                    onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                    }}
                >
                    <Flex items="center" justify="center" p="4" style={{ transform: `scale(${zoom})`, transition: "transform 0.2s ease-in-out" }}>
                        {!!mimeType && mimeType.startsWith("image/") ? (
                            <CachedImage
                                src={currentFileUrl}
                                alt={currentFileName ?? t("editor.Image")}
                                className="h-auto max-h-[calc(100dvh-4rem)] w-auto max-w-[calc(100vw-2rem)] object-contain"
                                onDragStart={handleDrag}
                                onDragOver={handleDrag}
                                onDragEnd={handleDrag}
                                onDrag={handleDrag}
                            />
                        ) : (
                            <Flex items="center" direction="col">
                                <Box textSize="2xl" weight="semibold" mb="2" className="text-gray-500">
                                    {t("common.No preview")}
                                </Box>
                                <Box>{currentFileName}</Box>
                            </Flex>
                        )}
                    </Flex>
                    <Flex
                        items="center"
                        gap="2"
                        rounded="full"
                        border
                        position="fixed"
                        bottom="1"
                        z="50"
                        className="left-1/2 -translate-x-1/2 bg-secondary/70 [&>:first-child]:rounded-l-full [&>:last-child]:rounded-r-full"
                    >
                        <Label display="flex" items="center" ml="2" gap="0.5">
                            <Input
                                type="number"
                                value={currentIndex + 1}
                                min={1}
                                max={files.length}
                                onChange={(e) => setCurrentIndex(Number(e.target.value) - 1)}
                                variant="ghost"
                                className="h-auto w-10 p-0 text-center"
                            />
                            <span className="text-nowrap text-xs text-gray-500">/ {files.length}</span>
                        </Label>
                        <Flex items="center">
                            <Button variant="ghost" size="icon-sm" onClick={goPrev}>
                                <IconComponent icon="chevron-left" size="4" />
                            </Button>
                            <Button variant="ghost" size="icon-sm" onClick={goNext}>
                                <IconComponent icon="chevron-right" size="4" />
                            </Button>
                        </Flex>
                        <Label display="flex" items="center" mr="2" gap="0.5">
                            <Input
                                type="number"
                                value={Math.round(zoom * 100)}
                                min={50}
                                max={150}
                                onChange={(e) => setZoom(Number(e.target.value) / 100)}
                                variant="ghost"
                                className="h-auto w-10 p-0 text-center"
                            />
                            <span className="text-xs text-gray-500">%</span>
                        </Label>
                        <Button variant="ghost" size="icon-sm" onClick={onClose}>
                            <IconComponent icon="x" size="4" />
                        </Button>
                    </Flex>
                </Box>
            </Flex>
        </DismissableLayer>
    );
};

export default ImagePreviewDialog;
