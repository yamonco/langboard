const UNESCAPED_ANGLE_OPENING = /(?<!\\)</g;

/**
 * Escape every unescaped angle-bracket opening so downstream parsers can never
 * interpret the text as HTML or JSX. Used as the fail-safe retry when the
 * markdown deserializer throws on tag-like prose such as `action=<a>`.
 */
export const escapeAngleOpenings = (str: string): string => str.replace(UNESCAPED_ANGLE_OPENING, "&lt;");
