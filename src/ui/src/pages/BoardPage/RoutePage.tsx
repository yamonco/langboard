import { BoardController } from "@/core/providers/BoardController";
import BoardProxy from "@/pages/BoardPage";
import { Outlet, useParams } from "react-router";

function BoardRoutePage(): React.JSX.Element {
    const { projectUID } = useParams();

    return (
        <BoardController key={projectUID}>
            <BoardProxy />
            <Outlet />
        </BoardController>
    );
}

export default BoardRoutePage;
