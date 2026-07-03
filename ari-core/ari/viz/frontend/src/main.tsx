import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { isDevMode } from "./hooks/useDevMode";

// Error boundary to surface render failures visually. Full stack traces are
// developer-only (071): non-developers see a short friendly message instead of
// a raw stack. This boundary is OUTSIDE the React context/hook tree, so it
// reads the flag directly via isDevMode() (localStorage['ari_dev_mode']).
class ErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { error: Error | null }
> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: 40, color: "#ef4444", fontFamily: "monospace" }}>
          <h2>ARI Dashboard Error</h2>
          {isDevMode() ? (
            <pre style={{ whiteSpace: "pre-wrap", marginTop: 16 }}>
              {this.state.error.message}
              {"\n\n"}
              {this.state.error.stack}
            </pre>
          ) : (
            <p style={{ marginTop: 16 }}>
              Something went wrong rendering the dashboard. Reload the page, or
              enable Developer Mode in Settings to see the full error details.
            </p>
          )}
        </div>
      );
    }
    return this.props.children;
  }
}

try {
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  );
} catch (e: any) {
  document.getElementById("root")!.innerHTML = isDevMode()
    ? `<pre style="color:red;padding:40px">${e?.message}\n${e?.stack}</pre>`
    : `<div style="color:#ef4444;padding:40px;font-family:monospace">ARI Dashboard failed to start. Reload the page, or enable Developer Mode in Settings for details.</div>`;
}
