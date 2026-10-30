import React from "react";
import ReactDOM from "react-dom/client";
import { Theme } from "@carbon/react";
import App from "./App";
import "./styles.scss";
import "./sre/sre.scss";
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Theme theme="white">
      <App />
    </Theme>
  </React.StrictMode>,
);
