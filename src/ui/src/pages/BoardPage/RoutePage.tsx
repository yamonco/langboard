import { BoardController } from "@/core/providers/BoardController";
import BoardProxy from "@/pages/BoardPage";
import { Outlet } from "react-router";

function BoardRoutePage(): React.JSX.Element {
    return (
        <BoardController>
            <BoardProxy />
            <Outlet />
        </BoardController>
    );
}

export default BoardRoutePage;
