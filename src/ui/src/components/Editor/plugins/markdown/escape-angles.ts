const PROTECTED_BLOCK = /(```[\s\S]*?(?:```|$)|~~~[\s\S]*?(?:~~~|$)|\$\$[\s\S]*?(?:\$\$|$))/g;

const escapeTextAngleOpenings = (str: string): string => {
    let result = "";

    for (let index = 0; index < str.length; ++index) {
        if (str[index] !== "<") {
            result += str[index];
            continue;
        }

        let slashCount = 0;
        for (let slashIndex = index - 1; slashIndex >= 0 && str[slashIndex] === "\\"; --slashIndex) {
            ++slashCount;
        }
        result += slashCount % 2 === 0 ? "&lt;" : "<";
    }

    return result;
};

/**
 * Escape every unescaped angle-bracket opening so downstream parsers can never
 * interpret the text as HTML or JSX. Used as the fail-safe retry when the
 * markdown deserializer throws on tag-like prose such as `action=<a>`.
 */
export const escapeAngleOpenings = (str: string): string => {
    let lastIndex = 0;
    let result = "";

    for (const match of str.matchAll(PROTECTED_BLOCK)) {
        const index = match.index;
        result += escapeTextAngleOpenings(str.slice(lastIndex, index));
        result += match[0];
        lastIndex = index + match[0].length;
    }

    return result + escapeTextAngleOpenings(str.slice(lastIndex));
};
