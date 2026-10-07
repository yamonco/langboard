import { useState } from "react";
import { createRoot } from "react-dom/client";
import CachedImage from "./index";
function Fixture() {
    const [src, setSrc] = useState("/file/encrypted/card_attachment/one.png");
    const [visible, setVisible] = useState(false);
    return (
        <>
            <button onClick={() => setVisible(true)}>Show</button>
            <button onClick={() => setVisible(false)}>Hide</button>
            <button onClick={() => setSrc("/file/encrypted/card_attachment/two.png")}>Next</button>
            <button onClick={() => setSrc("https://external.example.invalid/proof.png")}>External</button>
            {visible && <CachedImage src={src} alt="attachment" srcSet="/file/encrypted/card_attachment/bypass.png 2x" />}
        </>
    );
}
createRoot(document.getElementById("root")!).render(<Fixture />);
