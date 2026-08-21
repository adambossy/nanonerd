import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { registerSW } from "virtual:pwa-register";
import History from "./pages/History";
import Home from "./pages/Home";
import Reader from "./pages/Reader";
import Setup from "./pages/Setup";
import Start from "./pages/Start";
import Stats from "./pages/Stats";
import "./styles.css";

registerSW({ immediate: true });
// Ask the browser not to evict our IndexedDB under storage pressure.
if ("storage" in navigator && navigator.storage?.persist) {
  void navigator.storage.persist().catch(() => undefined);
}

const rootElement = document.getElementById("root");
if (!rootElement) throw new Error("missing #root");

createRoot(rootElement).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Start />} />
        <Route path="/library" element={<Home />} />
        <Route path="/read/:id" element={<Reader />} />
        <Route path="/history" element={<History />} />
        <Route path="/setup" element={<Setup />} />
        <Route path="/stats" element={<Stats />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
);
