import Button from "@/components/base/Button";
import Input from "@/components/base/Input";
import { useState } from "react";
import { useTranslation } from "react-i18next";

type Settings = Record<string, unknown>;

export default function DocumentRetrievalSettings({
    value,
    disabled,
    onSave,
}: {
    value: Settings;
    disabled: boolean;
    onSave: (retrieval: Settings) => void;
}): React.JSX.Element {
    const [t] = useTranslation();
    const [error, setError] = useState("");
    const settings = value.retrieval && typeof value.retrieval === "object" ? (value.retrieval as Settings) : {};
    const splitter = settings.splitter && typeof settings.splitter === "object" ? (settings.splitter as Settings) : {};
    const [splitterType, setSplitterType] = useState(String(splitter.type ?? "recursive"));
    const [lengthUnit, setLengthUnit] = useState(String(splitter.length_unit ?? "characters"));
    const numeric = (name: string, fallback: number, min: number, max: number, step = 1) => (
        <label className="grid gap-1 text-xs" key={name}>
            {t(`internalBot.retrieval.${name}`)}
            <Input
                name={name}
                onInput={(event) => event.currentTarget.setCustomValidity("")}
                type="number"
                required
                min={min}
                max={max}
                step={step}
                defaultValue={Number((name.startsWith("splitter.") ? splitter[name.slice(9)] : settings[name]) ?? fallback)}
            />
        </label>
    );
    const select = (name: string, fallback: string, options: string[]) => (
        <label className="grid gap-1 text-xs" key={name}>
            {t(`internalBot.retrieval.${name}`)}
            <select
                name={name}
                className="h-9 rounded-md border bg-background px-2 text-sm"
                defaultValue={String(splitter[name.slice(9)] ?? fallback)}
                onChange={(event) => {
                    if (name === "splitter.type") setSplitterType(event.target.value);
                    if (name === "splitter.length_unit") setLengthUnit(event.target.value);
                }}
            >
                {options.map((option) => (
                    <option key={option} value={option}>
                        {option}
                    </option>
                ))}
            </select>
        </label>
    );
    return (
        <form
            key={JSON.stringify(settings)}
            className="mb-4 rounded-lg border p-3"
            onInput={(event) => {
                setError("");
                const overlap = event.currentTarget.elements.namedItem("splitter.chunk_overlap") as HTMLInputElement;
                overlap.setCustomValidity("");
            }}
            onSubmit={(event) => {
                event.preventDefault();
                const form = new FormData(event.currentTarget);
                const size = Number(form.get("splitter.chunk_size"));
                const overlap = Number(form.get("splitter.chunk_overlap"));
                const overlapInput = event.currentTarget.elements.namedItem("splitter.chunk_overlap") as HTMLInputElement;
                overlapInput.setCustomValidity(overlap >= size ? t("internalBot.retrieval.overlap_error") : "");
                if (!event.currentTarget.reportValidity()) return;
                const next = { ...settings };
                const nextSplitter = { ...splitter };
                for (const [name, input] of form) {
                    if (
                        [
                            "enabled",
                            "splitter.separators",
                            "splitter.markdown_headers",
                            "splitter.strip_headers",
                            "splitter.strip_whitespace",
                        ].includes(name)
                    )
                        continue;
                    const raw = String(input);
                    const field = name.startsWith("splitter.") ? name.slice(9) : name;
                    const target = name.startsWith("splitter.") ? nextSplitter : next;
                    target[field] = ["type", "length_unit", "encoding", "separator", "keep_separator"].includes(field)
                        ? field === "keep_separator" && raw === "false"
                            ? false
                            : raw
                        : Number(raw);
                }
                nextSplitter.strip_whitespace = form.has("splitter.strip_whitespace");
                if (splitterType === "markdown") {
                    nextSplitter.strip_headers = form.has("splitter.strip_headers");
                    nextSplitter.markdown_headers = form.getAll("splitter.markdown_headers").map(Number);
                    if (!(nextSplitter.markdown_headers as number[]).length) {
                        setError(t("internalBot.retrieval.headers_error"));
                        return;
                    }
                }
                if (splitterType !== "character") {
                    try {
                        const separators: unknown = JSON.parse(String(form.get("splitter.separators")));
                        if (
                            !Array.isArray(separators) ||
                            !separators.length ||
                            separators.length > 16 ||
                            separators.at(-1) !== "" ||
                            separators.some((item) => typeof item !== "string" || item.length > 32)
                        )
                            throw new Error();
                        nextSplitter.separators = separators;
                    } catch {
                        const input = event.currentTarget.elements.namedItem("splitter.separators") as HTMLTextAreaElement;
                        input.setCustomValidity(t("internalBot.retrieval.separators_error"));
                        input.reportValidity();
                        return;
                    }
                }
                next.enabled = form.has("enabled");
                next.splitter = nextSplitter;
                onSave(next);
            }}
        >
            <fieldset disabled={disabled} className="grid gap-3">
                <legend className="mb-2 text-sm font-medium">{t("internalBot.retrieval.title")}</legend>
                <label className="flex items-center gap-2 text-sm">
                    <input name="enabled" type="checkbox" className="size-4 accent-primary" defaultChecked={settings.enabled === true} />
                    {t("internalBot.retrieval.enabled")}
                </label>
                <p className="text-xs text-muted-foreground">{t("internalBot.Existing attachments require explicit processing")}</p>
                <p className="text-xs text-muted-foreground">
                    {t("internalBot.retrieval.store")}: {String(settings.store ?? "sqlite")}
                </p>
                <div className="grid gap-3 sm:grid-cols-2">
                    {numeric("dimensions", 1536, 1, 65536)}
                    {select("splitter.type", "recursive", ["recursive", "character", "markdown"])}
                    {numeric("splitter.chunk_size", 1000, 64, 8192)}
                    {numeric("splitter.chunk_overlap", 150, 0, 2048)}
                    {select("splitter.length_unit", "characters", ["characters", "tokens"])}
                    {lengthUnit === "tokens" && select("splitter.encoding", "cl100k_base", ["cl100k_base", "o200k_base"])}
                    {select("splitter.keep_separator", "start", ["false", "start", "end"])}
                    {numeric("k", 5, 1, 25)}
                    {numeric("max_return_tokens", 4000, 128, 16000)}
                    {numeric("timeout_seconds", 10, 1, 30, 0.1)}
                </div>
                <label className="flex items-center gap-2 text-sm">
                    <input name="splitter.strip_whitespace" type="checkbox" defaultChecked={splitter.strip_whitespace !== false} />
                    {t("internalBot.retrieval.splitter.strip_whitespace")}
                </label>
                <label className="grid gap-1 text-xs">
                    {t(`internalBot.retrieval.splitter.${splitterType === "character" ? "separator" : "separators"}`)}
                    {splitterType === "character" ? (
                        <textarea
                            key="character-separator"
                            name="splitter.separator"
                            maxLength={32}
                            className="min-h-16 rounded-md border bg-background p-2 font-mono text-sm"
                            defaultValue={String(splitter.separator ?? "\n\n")}
                        />
                    ) : (
                        <textarea
                            key="recursive-separators"
                            name="splitter.separators"
                            required
                            className="min-h-16 rounded-md border bg-background p-2 font-mono text-sm"
                            defaultValue={JSON.stringify(splitter.separators ?? ["\n\n", "\n", "。", "．", ".", "，", "、", ",", " ", ""])}
                            onInput={(event) => event.currentTarget.setCustomValidity("")}
                        />
                    )}
                </label>
                {splitterType === "markdown" && (
                    <fieldset className="grid gap-2 rounded-md border p-2">
                        <legend className="text-xs">{t("internalBot.retrieval.splitter.markdown_headers")}</legend>
                        <div className="flex flex-wrap gap-3">
                            {[1, 2, 3, 4, 5, 6].map((level) => (
                                <label key={level} className="flex items-center gap-1 text-sm">
                                    <input
                                        type="checkbox"
                                        name="splitter.markdown_headers"
                                        value={level}
                                        defaultChecked={(Array.isArray(splitter.markdown_headers) ? splitter.markdown_headers : [1, 2, 3]).includes(
                                            level
                                        )}
                                    />
                                    H{level}
                                </label>
                            ))}
                        </div>
                        <label className="flex items-center gap-2 text-sm">
                            <input name="splitter.strip_headers" type="checkbox" defaultChecked={splitter.strip_headers === true} />
                            {t("internalBot.retrieval.splitter.strip_headers")}
                        </label>
                    </fieldset>
                )}
                <p className="text-xs text-muted-foreground">{t("internalBot.retrieval.overlap_help")}</p>
                {error && (
                    <p role="alert" className="text-sm text-destructive">
                        {error}
                    </p>
                )}
                <Button type="submit" size="sm" className="justify-self-start">
                    {t("common.Save")}
                </Button>
            </fieldset>
        </form>
    );
}
