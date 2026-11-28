import React from "react";
import ReactDOM from "react-dom/client";
import "./fonts.css";
import "./styles.css";
import Portal from "./portal/Portal";
import { ThemeProvider } from "./portal/Theme";
import "./portal/night.css";

const Demo = React.lazy(() => import("./demo/Demo"));
const Console = React.lazy(() => import("./App"));
const DroneExplodeBackdrop = React.lazy(() => import("./DroneExplodeBackdrop"));

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ThemeProvider>
      <React.Suspense fallback={null}>
        <DroneExplodeBackdrop />
      </React.Suspense>
      {location.pathname === "/demo" ? (
        <React.Suspense fallback={<div>Loading AERIS…</div>}>
          <Demo />
        </React.Suspense>
      ) : location.pathname === "/console" ? (
        <React.Suspense fallback={<div>Loading AERIS Shenzhen Console…</div>}>
          <Console initialMapKind="shenzhen" />
        </React.Suspense>
      ) : (
        <Portal />
      )}
    </ThemeProvider>
  </React.StrictMode>,
);
