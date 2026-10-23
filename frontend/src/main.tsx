import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { configureClient } from "./api/client";
import { useAuthStore } from "./store/auth";
import "./styles.css";

configureClient({
  getToken: () => useAuthStore.getState().token,
  onUnauthorized: () => useAuthStore.getState().logout(),
});

// Permissions can change server-side; re-sync them whenever the app loads with a stored session.
void useAuthStore.getState().refreshProfile();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
