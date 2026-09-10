import { draggable } from "@atlaskit/pragmatic-drag-and-drop/element/adapter";
import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

import { BOARD_MEMBER_DRAG_TYPE } from "@/pages/BoardPage/components/board/BoardGestureData";

export default function BoardMemberDrag({ projectUID, memberUID, children }: { projectUID: string; memberUID: string; children: React.ReactNode }) {
    const ref = useRef<HTMLSpanElement>(null);
    const [t] = useTranslation();
    useEffect(() => {
        if (!ref.current) return;
        return draggable({ element: ref.current, getInitialData: () => ({ type: BOARD_MEMBER_DRAG_TYPE, projectUID, memberUID }) });
    }, [projectUID, memberUID]);

    return (
        <span
            ref={ref}
            className="relative inline-flex shrink-0 cursor-grab rounded-full hover:z-50 active:cursor-grabbing"
            title={t("board.Drag onto a card to assign")}
        >
            {children}
        </span>
    );
}
