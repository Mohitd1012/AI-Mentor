import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { OverlayApp } from "./overlay/OverlayApp";
import "./index.css";

const isOverlay = window.location.hash === "#overlay";

// Tag the body so CSS can force transparency only for the overlay window.
if (isOverlay) {
  document.documentElement.classList.add("overlay-mode");
  document.body.classList.add("overlay-mode");
}

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    {isOverlay ? <OverlayApp /> : <App />}
  </React.StrictMode>,
);
