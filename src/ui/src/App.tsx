import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import Router from "@/Router";
import Toast from "@/components/base/Toast";
import { AuthProvider } from "@/core/providers/AuthProvider";
import { SocketProvider } from "@/core/providers/SocketProvider";
import "@/i18n";
import { Outlet } from "react-router";
import { PageHeaderProvider } from "@/core/providers/PageHeaderProvider";
import { GlobalSocketHandlersSubscriber } from "@/core/providers/GlobalSocketHandlersSubscriber";
import ProjectQuickSwitcher from "@/pages/DashboardPage/components/ProjectQuickSwitcher";
import { useAuth } from "@/core/providers/AuthProvider";

const queryClient = new QueryClient();

function App() {
    return (
        <QueryClientProvider client={queryClient}>
            <PageHeaderProvider>
                <Router>
                    <AuthProvider>
                        <SocketProvider>
                            <GlobalSocketHandlersSubscriber>
                                <Outlet />
                                <AuthenticatedProjectQuickSwitcher />
                                <Toast.Area richColors />
                            </GlobalSocketHandlersSubscriber>
                        </SocketProvider>
                    </AuthProvider>
                </Router>
            </PageHeaderProvider>
        </QueryClientProvider>
    );
}

function AuthenticatedProjectQuickSwitcher(): React.JSX.Element | null {
    const { currentUser } = useAuth();
    return currentUser ? <ProjectQuickSwitcher /> : null;
}

export default App;
