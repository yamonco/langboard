"use client";

import { ListPlugin } from "@platejs/list/react";
import { BulletedListRules, TaskListRules } from "@platejs/list";
import { orderedListInputRules } from "./markdown/list-number";
import { KEYS } from "platejs";
import { IndentKit } from "@/components/Editor/plugins/indent-kit";
import { BlockList } from "@/components/plate-ui/block-list";

export const ListKit = [
    ...IndentKit,
    ListPlugin.configure({
        inputRules: [
            BulletedListRules.markdown({ variant: "-" }),
            BulletedListRules.markdown({ variant: "*" }),
            ...orderedListInputRules,
            TaskListRules.markdown({ checked: false }),
            TaskListRules.markdown({ checked: true }),
        ],
        inject: {
            targetPlugins: [...KEYS.heading, KEYS.p, KEYS.blockquote, KEYS.codeBlock, KEYS.img],
        },
        render: {
            belowNodes: BlockList,
        },
    }),
];
