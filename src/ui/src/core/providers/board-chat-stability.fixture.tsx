import "@/core/injection";
import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BoardController, useBoardController } from "./BoardController";
import { useBoardChat } from "./BoardChatProvider";
import { api } from "@/core/helpers/Api";
import { InternalBotModel } from "@/core/models";
import "@/i18n";
let mounts = 0, requests = 0;
api.defaults.adapter = async (config) => {
 requests++;
 return { status: 200, statusText: "OK", headers: {}, config, data: { sessions: [] } };
};
function Page() {
 const { setBoardChat } = useBoardController();
 const { bot } = useBoardChat();
 const [mount, setMount] = useState(0), [value, setValue] = useState("");
 useEffect(() => setMount(++mounts), []);
 return <><output data-testid="mounts">{mount}</output><output data-testid="chat">{bot.uid ?? "disabled"}</output>
 <input aria-label="Draft" value={value} onChange={(e) => setValue(e.target.value)} />
 <button onClick={() => setBoardChat({ projectUID: "fixture", bot: { uid: "bot" } as InternalBotModel.TModel })}>Enable chat</button>
 <button onClick={() => setBoardChat(undefined)}>Disable chat</button>
 <button onClick={() => setValue(String(requests))}>Read requests</button></>;
}
createRoot(document.getElementById("root")!).render(<QueryClientProvider client={new QueryClient()}><BoardController projectUID="fixture"><Page /></BoardController></QueryClientProvider>);
