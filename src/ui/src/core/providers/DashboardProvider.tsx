import { AuthUser } from "@/core/models";
import { ISocketContext, useSocket } from "@/core/providers/SocketProvider";
import { createContext, useContext } from "react";

export interface IDashboardContext {
    currentUser: AuthUser.TModel;
    socket: ISocketContext;
}

interface IDashboardProviderProps {
    currentUser: AuthUser.TModel;
    children: React.ReactNode;
}

const initialContext = {
    currentUser: {} as AuthUser.TModel,
    socket: {} as ISocketContext,
};

const DashboardContext = createContext<IDashboardContext>(initialContext);

export const DashboardProvider = ({ currentUser, children }: IDashboardProviderProps): React.ReactNode => {
    const socket = useSocket();
    return (
        <DashboardContext.Provider
            value={{
                socket,
                currentUser,
            }}
        >
            {children}
        </DashboardContext.Provider>
    );
};

export const useDashboard = () => {
    const context = useContext(DashboardContext);
    if (!context) {
        throw new Error("useDashboard must be used within a DashboardProvider");
    }
    return context;
};
