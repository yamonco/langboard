/* eslint-disable @typescript-eslint/no-explicit-any */
import { default as BaseMarkdown, Components, Options as MarkdownOptions } from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeMathjax from "rehype-mathjax";
import MarkdownCodeBlock from "@/components/Markdown/CodeBlock";
import MarkdownCodeDrawingBlock, { isCodeDrawingLanguage } from "@/components/Markdown/CodeDrawingBlock";
import { IChatContent } from "@/core/models/Base";
import Box from "@/components/base/Box";
import MarkdownDateBlock from "@/components/Markdown/DateBlock";
import rehypeRaw from "rehype-raw";
import { cn } from "@/core/utils/ComponentUtils";
import MarkdownThinkBlock from "@/components/Markdown/ThinkBlock";
import { memo } from "react";
import MarkdownInternalLink from "@/components/Markdown/InternalLink";
import MarkdownMentionLink from "@/components/Markdown/MentionLink";
import { CODE_DRAWING_TYPE } from "@platejs/code-drawing";
import { visit } from "unist-util-visit";
import type { Plugin } from "unified";

export interface IMarkdownProps extends Omit<MarkdownOptions, "remarkPlugins" | "rehypePlugins" | "className" | "components" | "children"> {
    message: IChatContent | { content: string };
}

const INTERNAL_LINK_PATTERN = /\[\[(card|project_wiki):([a-zA-Z0-9_-]+)\]\]/g;
const FENCED_CODE_PATTERN = /^(```|~~~)/;
const CODE_DRAWING_INLINE_PATTERN = /^\$\$(PlantUml|Graphviz|Flowchart|Mermaid)\s+(.+?)(?:\s*\$\$)?$/;
const HTML_TAG_REGEX = /^<\/?[a-zA-Z][\w:-]*(\s+[a-zA-Z_:][\w:.-]*(\s*=\s*(".*?"|'.*?'|[^'"<>\s]+))?)*\s*\/?>/;
const PROTECTED_BLOCK_REGEX = /(```[\s\S]*?(?:```|$)|~~~[\s\S]*?(?:~~~|$)|\$\$[\s\S]*?(?:\$\$|$))/g;
const HTML_TAGS = new Set([
    "a",
    "abbr",
    "address",
    "audio",
    "b",
    "bdi",
    "bdo",
    "big",
    "blockquote",
    "br",
    "callout",
    "caption",
    "cite",
    "code",
    "col",
    "colgroup",
    "date",
    "dd",
    "del",
    "details",
    "dfn",
    "div",
    "dl",
    "dt",
    "em",
    "figcaption",
    "figure",
    "file",
    "font",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "i",
    "img",
    "ins",
    "kbd",
    "li",
    "mark",
    "math",
    "ol",
    "p",
    "picture",
    "pre",
    "q",
    "rp",
    "rt",
    "ruby",
    "samp",
    "small",
    "source",
    "span",
    "strong",
    "sub",
    "summary",
    "sup",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "time",
    "toc",
    "tr",
    "track",
    "u",
    "ul",
    "video",
    "wbr",
]);

const isExternalLink = (href: string) => /^(https?:|mailto:|tel:|\/|#)/.test(href);

const getCodeDrawingTypeFromCode = (code: string) => {
    const trimmedCode = code.trim();
    if (/@startuml\b/i.test(trimmedCode) || /@enduml\b/i.test(trimmedCode)) {
        return "PlantUml";
    }

    if (/^digraph\b/i.test(trimmedCode) || /^graph\b/i.test(trimmedCode)) {
        return "Graphviz";
    }

    if (/^flowchart\b/i.test(trimmedCode)) {
        return "Flowchart";
    }

    if (/^(sequenceDiagram|classDiagram|stateDiagram|erDiagram|journey|gantt|pie|mindmap|timeline)\b/i.test(trimmedCode)) {
        return "Mermaid";
    }

    return "";
};

const isLikelyNonMathBlock = (code: string) => /[\u3131-\uD79D]/.test(code) || /[-=]+>|--+/.test(code);

const getTextFromChildren = (children: unknown): string => {
    if (typeof children === "string" || typeof children === "number") {
        return `${children}`;
    }

    if (Array.isArray(children)) {
        return children.map(getTextFromChildren).join("");
    }

    if (children && typeof children === "object" && "props" in children) {
        return getTextFromChildren((children as { props?: { children?: unknown } }).props?.children);
    }

    return "";
};

const replaceInternalLinks = (content: string) => {
    const lines = content.split("\n");
    let inCodeBlock = false;

    return lines
        .map((line) => {
            if (FENCED_CODE_PATTERN.test(line.trim())) {
                inCodeBlock = !inCodeBlock;
                return line;
            }

            if (inCodeBlock) {
                return line;
            }

            return line.replace(
                INTERNAL_LINK_PATTERN,
                (_, internalType: string, uid: string) => `<span data-internal-link-type="${internalType}" data-internal-link-uid="${uid}"></span>`
            );
        })
        .join("\n");
};

const normalizeCodeDrawingSyntax = (content: string) => {
    return content
        .split("\n")
        .map((line) => {
            const trimmedLine = line.trim();
            const inlineMatch = trimmedLine.match(CODE_DRAWING_INLINE_PATTERN);
            if (!inlineMatch) {
                if (!trimmedLine.startsWith("$$")) {
                    return line.replace(/\$\$(PlantUml|Graphviz|Flowchart|Mermaid)(?=\s)/g, "\\$\\$$1");
                }

                return line;
            }

            const [, drawingType, code] = inlineMatch;
            return `$$${drawingType}\n${code.trim()}\n$$`;
        })
        .join("\n");
};

const decodeCodeBlockEntities = (content: string) => {
    return content.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
};

const splitProtectedBlocks = (text: string): { content: string; isProtected: bool }[] => {
    const blocks: { content: string; isProtected: bool }[] = [];
    let lastIndex = 0;
    let match: RegExpExecArray | null;

    while ((match = PROTECTED_BLOCK_REGEX.exec(text)) !== null) {
        if (match.index > lastIndex) {
            blocks.push({
                content: text.slice(lastIndex, match.index),
                isProtected: false,
            });
        }

        blocks.push({
            content: decodeCodeBlockEntities(match[0]),
            isProtected: true,
        });

        lastIndex = PROTECTED_BLOCK_REGEX.lastIndex;
    }

    if (lastIndex < text.length) {
        blocks.push({
            content: text.slice(lastIndex),
            isProtected: false,
        });
    }

    return blocks;
};

const escapeNonHtmlAngles = (content: string) => {
    let result = "";
    let i = 0;

    while (i < content.length) {
        const char = content[i];

        if (char === "<") {
            let slashCount = 0;
            for (let j = i - 1; j >= 0 && content[j] === "\\"; --j) {
                ++slashCount;
            }

            const isEscaped = slashCount % 2 === 1;
            const remaining = content.slice(i);
            const match = remaining.match(HTML_TAG_REGEX);
            if (!isEscaped && match) {
                result += match[0];
                i += match[0].length;
                continue;
            }

            result += isEscaped ? char : "&lt;";
            ++i;
            continue;
        }

        if (char === ">") {
            let slashCount = 0;
            for (let j = i - 1; j >= 0 && content[j] === "\\"; --j) {
                ++slashCount;
            }

            result += slashCount % 2 === 1 ? char : "&gt;";
            ++i;
            continue;
        }

        result += char;
        ++i;
    }

    return result;
};

const escapeMarkdownAngles = (content: string) => {
    const escapeNonProtectedContent = (text: string): string => {
        const tagLikeRegex = /(?<!\\)<[^>]+>/g;
        let lastIndex = 0;
        let match: RegExpExecArray | null;
        let newText = "";

        while ((match = tagLikeRegex.exec(text)) !== null) {
            if (match.index > lastIndex) {
                newText += text.slice(lastIndex, match.index);
            }

            const tag = match[0];
            const tagName = tag.replace(/<|\/|>/g, "").split(" ")[0];

            if (HTML_TAGS.has(tagName)) {
                newText += tag;
                lastIndex = match.index + tag.length;
                continue;
            }

            newText += tag.replace(/</g, "&lt;").replace(/>/g, "&gt;");
            lastIndex = match.index + tag.length;
        }

        newText += text.slice(lastIndex);
        const escapedContent = escapeNonHtmlAngles(newText);

        const lines = escapedContent.split("\n");
        for (let i = 0; i < lines.length; ++i) {
            const line = lines[i].trimStart();
            if (line.startsWith("&gt;")) {
                lines[i] = lines[i].replace(/^(\s*)&gt;(\s*)/, "$1>$2");
            }
        }

        return lines.join("\n");
    };

    return splitProtectedBlocks(content)
        .map(({ content, isProtected }) => (isProtected ? content : escapeNonProtectedContent(content)))
        .join("");
};

const remarkCodeDrawing: Plugin = () => {
    return (tree) => {
        visit(
            tree,
            (node: any) => node.type === "math" || node.type === "inlineMath",
            (node: any) => {
                const meta = `${node.meta ?? ""}`.trim();
                let drawingType = meta.split(/\s+/)[0];
                let code = node.value || meta.slice(drawingType.length).trim();

                if (!CODE_DRAWING_TYPE[drawingType as keyof typeof CODE_DRAWING_TYPE]) {
                    const valueMatch = `${node.value ?? ""}`.trim().match(/^(PlantUml|Graphviz|Flowchart|Mermaid)\s+([\s\S]*)$/);
                    drawingType = valueMatch?.[1] ?? getCodeDrawingTypeFromCode(`${node.value ?? ""}`);
                    code = valueMatch?.[2]?.trim() ?? `${node.value ?? ""}`;
                }

                if (!drawingType || !CODE_DRAWING_TYPE[drawingType as keyof typeof CODE_DRAWING_TYPE]) {
                    if (isLikelyNonMathBlock(`${node.value ?? ""}`)) {
                        node.type = "html";
                        delete node.data;
                        node.value = `<div data-markdown-literal-code="${encodeURIComponent(`${node.value ?? ""}`)}"></div>`;
                    }

                    return;
                }

                node.type = "html";
                delete node.data;
                node.value = `<div data-code-drawing-language="${drawingType}" data-code-drawing-code="${encodeURIComponent(code)}"></div>`;
            }
        );
    };
};

const Markdown = memo(({ message, ...mdProps }: IMarkdownProps): React.JSX.Element => {
    const components: Components = {
        p({ node, ...props }) {
            return <div>{props.children}</div>;
        },
        div({ node, ...props }) {
            const htmlProps = props as Record<string, unknown>;
            const language = htmlProps["data-code-drawing-language"];
            const code = htmlProps["data-code-drawing-code"];
            if (typeof language === "string" && typeof code === "string") {
                return <MarkdownCodeDrawingBlock language={language} code={decodeURIComponent(code)} />;
            }

            const literalCode = htmlProps["data-markdown-literal-code"];
            if (typeof literalCode === "string") {
                return (
                    <pre
                        className={cn(
                            "my-2 overflow-auto whitespace-pre-wrap rounded-md border",
                            "bg-muted/30 p-3 text-xs leading-relaxed [overflow-wrap:anywhere]"
                        )}
                    >
                        <code>{decodeURIComponent(literalCode)}</code>
                    </pre>
                );
            }

            return <div {...props} />;
        },
        span({ node, ...props }) {
            const htmlProps = props as Record<string, unknown>;
            const internalType = htmlProps["data-internal-link-type"];
            const uid = htmlProps["data-internal-link-uid"];
            if (typeof internalType === "string" && typeof uid === "string") {
                return <MarkdownInternalLink internalType={internalType} uid={uid} />;
            }

            return <span {...props} />;
        },
        pre({ node, ...props }) {
            return <>{props.children}</>;
        },
        ol({ node, ...props }) {
            return <ol className="max-w-full">{props.children}</ol>;
        },
        ul({ node, ...props }) {
            return <ul className="max-w-full">{props.children}</ul>;
        },
        a({ node, ...props }) {
            const href = props.href ?? "";
            const label = getTextFromChildren(props.children);
            if (href && !isExternalLink(href) && label.trim().startsWith("@")) {
                return <MarkdownMentionLink uid={href} fallbackLabel={label} />;
            }

            return <a className="underline underline-offset-4 [overflow-wrap:anywhere]" target="_blank" {...props} />;
        },
        audio({ node, ...props }) {
            return <audio controls className="mt-2 max-w-full" {...props} />;
        },
        img({ node, ...props }) {
            return <img className="h-auto max-w-full" {...props} />;
        },
        video({ node, ...props }) {
            return <video controls className="mt-2 max-w-full rounded-md" {...props} />;
        },
        table({ node, ...props }) {
            return (
                <div className="prose prose-invert max-w-full overflow-x-auto">
                    <table>{props.children}</table>
                </div>
            );
        },
        code({ node, className, children, ...props }) {
            const match = /language-(\w+)/.exec(className || "");
            const language = match?.[1] ?? "";
            const code = String(children).replace(/\n$/, "");
            if (language && isCodeDrawingLanguage(language)) {
                return <MarkdownCodeDrawingBlock language={language} code={code} />;
            }

            return match ? (
                <MarkdownCodeBlock language={language} code={code} />
            ) : (
                <code
                    className={cn(
                        "whitespace-pre-wrap rounded-md bg-foreground/10 px-[0.3em] py-[0.2em] font-mono text-sm",
                        "text-inherit [overflow-wrap:anywhere]",
                        className
                    )}
                    {...props}
                >
                    {children}
                </code>
            );
        },
    };

    (components as any).date = MarkdownDateBlock;
    (components as any).file = ({ node, ...props }: Record<string, any>) => {
        const src = props.src ?? props.href ?? "";
        const name = props.name ?? props.children ?? src;
        if (!src) {
            return <span>{name}</span>;
        }

        return (
            <a href={src} target="_blank" className="underline underline-offset-4 [overflow-wrap:anywhere]">
                {name}
            </a>
        );
    };
    (components as any).think = MarkdownThinkBlock;

    const replaceNewlinesInTags = (content: string): string => {
        return content.replace(/(<[^>]+>)([\s\S]*?)(<\/[^>]+>)/g, (_, openTag, innerContent, closeTag) => {
            const trimmedContent = innerContent.replace(/^\n+|\n+$/g, "");
            const updatedContent = trimmedContent.replace(/\n/g, "<br>");
            return `${openTag}${updatedContent}${closeTag}`;
        });
    };

    const sanitizedContent = replaceNewlinesInTags(replaceInternalLinks(escapeMarkdownAngles(normalizeCodeDrawingSyntax(message.content))));

    return (
        <Box
            className={cn(
                "markdown min-w-0 max-w-full overflow-visible [overflow-wrap:anywhere]",
                "[&_mjx-container]:max-w-full [&_mjx-container]:overflow-x-auto"
            )}
        >
            <BaseMarkdown
                remarkPlugins={[remarkGfm, remarkMath, remarkCodeDrawing]}
                rehypePlugins={[rehypeRaw, rehypeMathjax]}
                components={components}
                {...mdProps}
            >
                {sanitizedContent}
            </BaseMarkdown>
        </Box>
    );
});

export default Markdown;
