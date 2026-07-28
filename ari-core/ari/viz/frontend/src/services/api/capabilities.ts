// ARI Dashboard API – server capability flags (gui_refresh Wave 1).
//
// GET /api/capabilities reports server-side feature flags, currently the
// ARI_GUI_V2 kill-switch (owner: gui_refresh task 03; removal gate: G6; see
// ari/viz/api_capabilities.py). Callers MUST default gui_v2 to ON when the
// fetch fails — the loopback dashboard must never brick into the fallback
// shell on an API hiccup (App.tsx implements that default).

import { get } from './client';

export interface ServerCapabilities {
  gui_v2: boolean;
  server_version: string;
}

export async function fetchCapabilities(): Promise<ServerCapabilities> {
  return get<ServerCapabilities>('/api/capabilities');
}
