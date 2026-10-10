import { createRoot } from "react-dom/client";
import Sidebar from "@/components/Sidebar";
import "@/i18n";
import "@/assets/styles/main.css";
createRoot(document.getElementById("root")!).render(
    <Sidebar
        navs={[
            { icon: "panel-left", name: "Explorer", href: "#explorer" },
            { icon: "list", name: "Cards", href: "#cards" },
            { icon: "circle-check", name: "My Work", href: "#work" },
        ]}
        main={<main>Card workspace</main>}
    />
);
