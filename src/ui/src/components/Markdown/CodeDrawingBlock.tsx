import Button from "@/components/base/Button";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import Loading from "@/components/base/Loading";
import { canRenderDiagram, renderDiagram } from "@/core/helpers/CodeDrawingRenderer";
import MarkdownCodeBlock from "@/components/Markdown/CodeBlock";
import { cn, copyToClipboard } from "@/core/utils/ComponentUtils";
import type { CodeDrawingType } from "@platejs/code-drawing";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

export interface IMarkdownCodeDrawingBlockProps {
    code: string;
    language: string;
}

const CODE_DRAWING_LANGUAGE_MAP: Record<string, CodeDrawingType> = {
    plantuml: "PlantUml",
    puml: "PlantUml",
    graphviz: "Graphviz",
    dot: "Graphviz",
    flowchart: "Flowchart",
    mermaid: "Mermaid",
};

export const isCodeDrawingLanguage = (language: string) => {
    return !!CODE_DRAWING_LANGUAGE_MAP[language.toLowerCase()];
};

const decodeCodeDrawingEntities = (content: string) => {
    return content
        .replace(/&amp;lt;/g, "<")
        .replace(/&amp;gt;/g, ">")
        .replace(/&amp;amp;/g, "&")
        .replace(/&lt;/g, "<")
        .replace(/&gt;/g, ">")
        .replace(/&amp;/g, "&");
};

function MarkdownCodeDrawingBlock({ code, language }: IMarkdownCodeDrawingBlockProps) {
    const [t] = useTranslation();
    const [image, setImage] = useState("");
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState("");
    const [isCopied, setIsCopied] = useState(false);
    const requestIDRef = useRef(0);
    const drawingType = useMemo(() => CODE_DRAWING_LANGUAGE_MAP[language.toLowerCase()], [language]);
    const normalizedCode = useMemo(() => decodeCodeDrawingEntities(code), [code]);
    const canRender = drawingType ? canRenderDiagram(drawingType, normalizedCode) : false;

    useEffect(() => {
        if (!drawingType || !canRender) {
            setImage("");
            setError("");
            setIsLoading(false);
            return;
        }

        requestIDRef.current += 1;
        const requestID = requestIDRef.current;
        setIsLoading(true);
        setError("");

        renderDiagram(drawingType, normalizedCode)
            .then((imageData) => {
                if (requestIDRef.current !== requestID) {
                    return;
                }

                setImage(imageData);
            })
            .catch((e) => {
                if (requestIDRef.current !== requestID) {
                    return;
                }

                setImage("");
                setError(e instanceof Error ? e.message : "Rendering failed");
            })
            .finally(() => {
                if (requestIDRef.current === requestID) {
                    setIsLoading(false);
                }
            });
    }, [canRender, drawingType, normalizedCode]);

    const copy = async () => {
        await copyToClipboard(normalizedCode);
        setIsCopied(true);
        setTimeout(() => setIsCopied(false), 2000);
    };

    if (!drawingType) {
        return <MarkdownCodeBlock language={language} code={normalizedCode} />;
    }

    if (!canRender) {
        return <MarkdownCodeBlock language={language} code={normalizedCode} />;
    }

    return (
        <Flex direction="col" mt="2" w="full" rounded="md" className="min-w-0 overflow-hidden border bg-card text-left">
            <Flex items="center" justify="between" w="full" pl="3" pr="1.5" py="1.5" className="border-b bg-muted/60">
                <span className="text-sm font-semibold">{drawingType}</span>
                <Button variant="ghost" size="icon-sm" onClick={copy} aria-label={t("common.Copy")}>
                    <IconComponent icon={isCopied ? "check" : "copy"} size="4" />
                </Button>
            </Flex>
            <Flex items="center" justify="center" className={cn("min-h-40 overflow-x-auto bg-background p-3", error && "items-stretch")}>
                {isLoading ? (
                    <Loading size="4" variant="secondary" spacing="2" animate="pulse" />
                ) : image ? (
                    <img src={image} alt={t("editor.Code drawing")} className="h-auto max-h-[50vh] max-w-none object-contain" />
                ) : error ? (
                    <MarkdownCodeBlock language={language} code={code} />
                ) : null}
            </Flex>
        </Flex>
    );
}

export default MarkdownCodeDrawingBlock;
