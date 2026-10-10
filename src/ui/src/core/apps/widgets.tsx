import * as React from "react";
import { createRoot } from "react-dom/client";
import Button from "@/components/base/Button";
import Textarea from "@/components/base/Textarea";
import Input from "@/components/base/Input";
import Badge from "@/components/base/Badge";

// Apps use these exports together so widgets and hooks share one React runtime.
export { React, createRoot, Button, Textarea, Badge, Input };
export type { ButtonProps } from "@/components/base/Button";
export type { TextareaProps } from "@/components/base/Textarea";
export type { BadgeProps } from "@/components/base/Badge";

export function mount(element: Element, content: React.ReactNode) {
    const root = createRoot(element);
    root.render(content);
    return () => root.unmount();
}

export interface NoteOptions {
    label: string;
    saveLabel: string;
    status?: string;
    value?: string;
    onSave: (value: string) => void;
}

function Note({ label, saveLabel, status, value = "", onSave }: NoteOptions) {
    const [draft, setDraft] = React.useState(value);
    const id = React.useId();
    return (
        <form
            className="flex flex-col gap-3 p-3"
            onSubmit={(event) => {
                event.preventDefault();
                onSave(draft);
            }}
        >
            <label htmlFor={id} className="text-sm font-medium">
                {label}
            </label>
            <Textarea id={id} value={draft} onChange={(event) => setDraft(event.target.value)} />
            {status && <Badge variant="secondary">{status}</Badge>}
            <Button type="submit">{saveLabel}</Button>
        </form>
    );
}

/** Draft only: onSave belongs to the app; this widget grants no business writes. */
export function mountNote(element: Element, options: NoteOptions) {
    return mount(element, <Note {...options} />);
}
