import { SlateEditor } from "platejs";
import { deserializeInlineMd, deserializeMd, DeserializeMdOptions } from "@platejs/markdown";
import { escapeAngleOpenings } from "@/components/Editor/plugins/markdown/escape-angles";

const escapeNonHtmlAngles = (str: string): string => {
    const htmlTagRegex = /^<\/?[a-zA-Z][\w:-]*(\s+[a-zA-Z_:][\w:.-]*(\s*=\s*(".*?"|'.*?'|[^'"<>\s]+))?)*\s*\/?>/;
    let result = "";
    let i = 0;

    while (i < str.length) {
        const char = str[i];

        if (char === "<") {
            let slashCount = 0;
            for (let j = i - 1; j >= 0 && str[j] === "\\"; --j) {
                slashCount++;
            }
            const isEscaped = slashCount % 2 === 1;

            const remaining = str.slice(i);
            const match = remaining.match(htmlTagRegex);

            if (!isEscaped && match) {
                const tagMatch = match[0];
                result += tagMatch;
                i += tagMatch.length;
            } else if (!isEscaped) {
                result += "&lt;";
                ++i;
            } else {
                result += char;
                ++i;
            }
        } else if (char === ">") {
            let slashCount = 0;
            for (let j = i - 1; j >= 0 && str[j] === "\\"; --j) {
                slashCount++;
            }
            const isEscaped = slashCount % 2 === 1;

            if (!isEscaped) {
                result += "&gt;";
            } else {
                result += char;
            }
            ++i;
        } else {
            result += char;
            ++i;
        }
    }

    return result;
};

const decodeCodeBlockEntities = (content: string) => {
    return content.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
};

const splitProtectedBlocks = (text: string): { isProtected: bool; content: string }[] => {
    const blocks: { isProtected: bool; content: string }[] = [];
    const protectedBlockRegex = /(```[\s\S]*?(?:```|$)|~~~[\s\S]*?(?:~~~|$)|\$\$[\s\S]*?(?:\$\$|$))/g;
    let lastIndex = 0;
    let match;

    while ((match = protectedBlockRegex.exec(text)) !== null) {
        if (match.index > lastIndex) {
            blocks.push({
                isProtected: false,
                content: text.slice(lastIndex, match.index),
            });
        }

        blocks.push({
            isProtected: true,
            content: decodeCodeBlockEntities(match[0]),
        });

        lastIndex = protectedBlockRegex.lastIndex;
    }

    if (lastIndex < text.length) {
        blocks.push({
            isProtected: false,
            content: text.slice(lastIndex),
        });
    }

    return blocks;
};

export const deserialize = (isInline: bool) => (editor: SlateEditor, text: string, options?: DeserializeMdOptions) => {
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

    const escapeNonMathContent = (text: string): string => {
        const tagLikeRegex = /(?<!\\)<[^>]+>/g;
        let lastIndex = 0;
        let match;
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

            const newTag = tag.replace(/</g, "&lt;").replace(/>/g, "&gt;");
            newText += newTag;
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

    const segments = splitProtectedBlocks(text);
    const processed = segments.map(({ isProtected, content }) => (isProtected ? content : escapeNonMathContent(content))).join("");

    try {
        return isInline ? deserializeInlineMd(editor, processed, options) : deserializeMd(editor, processed, options);
    } catch {
        // Allowed HTML tags still fail MDX parsing when they are never closed, for example a literal
        // `action=<a>` inside prose. Render the angle brackets as text instead of crashing the editor.
        const escaped = escapeAngleOpenings(processed);
        try {
            return isInline ? deserializeInlineMd(editor, escaped, options) : deserializeMd(editor, escaped, options);
        } catch {
            return [{ text }];
        }
    }
};
