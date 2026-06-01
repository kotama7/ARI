// ARI Dashboard – Settings page constants + helpers.
// Extracted verbatim from SettingsPage.tsx (refactor req 15, follow-up to 03):
// the provider/model + Letta embedding tables, the CUSTOM_HANDLE sentinel, the
// LettaModelEntry/LettaProviderTable types, and the pure _splitHandle helper.
// SettingsPage.tsx imports these. Pure data/logic — no React/JSX.

export const DEFAULT_PROVIDER = 'openai';

export const PROVIDER_MODELS: Record<string, string[]> = {
  openai: ['gpt-5.2', 'gpt-4o', 'gpt-4o-mini', 'o3', 'o1-mini'],
  anthropic: ['claude-opus-4-5', 'claude-sonnet-4-5', 'claude-3-5-haiku-latest'],
  gemini: ['gemini/gemini-2.5-pro', 'gemini/gemini-2.0-flash', 'gemini/gemini-1.5-pro'],
  ollama: ['ollama_chat/llama3.3', 'ollama_chat/qwen3:8b', 'ollama_chat/gemma3:9b', 'ollama_chat/mistral'],
  'cli-shim': ['claude-cli', 'claude-cli-agent', 'codex-cli', 'codex-cli-agent'],
};

export const PROVIDER_KEY_PLACEHOLDER: Record<string, string> = {
  openai: 'sk-...',
  anthropic: 'sk-ant-...',
  gemini: 'AIza...',
  ollama: '(not required)',
  'cli-shim': '(not required)',
};

// ── Memory (Letta) — provider × model picker ────────
//
// Letta freezes the agent's embedding_config at agent creation. The
// default ``letta/letta-free`` handle routes through the MemGPT-hosted
// embeddings.memgpt.ai endpoint and intermittently returns 522/empty
// body — Letta then surfaces this as a 400 with the misleading
// "Expecting value: line 1 column 1 (char 0)" message. We expose
// per-provider model lists here so the operator can pick a known-good
// combination and warn when letta-free is selected.
//
// Handles are stored on settings.json as ``provider/model`` strings,
// matching what Letta's SDK (and ari_skill_memory.MemoryConfig)
// expects. Some providers use a different prefix for chat models
// (e.g. ``ollama_chat/`` vs ``ollama/``) — kept on each entry.
export type LettaModelEntry = { handle: string; label?: string };
export type LettaProviderTable = Record<string, LettaModelEntry[]>;

export const LETTA_EMBEDDING_BY_PROVIDER: LettaProviderTable = {
  openai: [
    { handle: 'openai/text-embedding-3-small', label: 'text-embedding-3-small (recommended)' },
    { handle: 'openai/text-embedding-3-large', label: 'text-embedding-3-large' },
    { handle: 'openai/text-embedding-ada-002', label: 'text-embedding-ada-002' },
  ],
  gemini: [
    { handle: 'gemini/text-embedding-004', label: 'text-embedding-004' },
  ],
  ollama: [
    { handle: 'ollama/nomic-embed-text', label: 'nomic-embed-text (local)' },
    { handle: 'ollama/mxbai-embed-large', label: 'mxbai-embed-large (local)' },
    { handle: 'ollama/all-minilm', label: 'all-minilm (local)' },
  ],
  letta: [
    { handle: 'letta/letta-free', label: 'letta-free (external; flaky)' },
    { handle: 'letta-default', label: 'letta-default (resolves to letta-free)' },
  ],
};

// The Letta agent's chat LLM is bound to a fixed mock handle
// (letta/letta-free) inside ari-skill-memory because ARI never invokes
// the agent's chat API — only archival_insert / archival_search, which
// use embeddings. So no LLM picker is rendered; only the embedding
// picker below is operator-facing.
export const LETTA_EMBED_PROVIDERS = ['openai', 'gemini', 'ollama', 'letta'] as const;

export const CUSTOM_HANDLE_VALUE = '__custom__';

export function _splitHandle(
  handle: string,
  table: LettaProviderTable,
): { provider: string; model: string } {
  // Find a provider whose entries contain this handle.
  for (const [prov, entries] of Object.entries(table)) {
    if (entries.some((e) => e.handle === handle)) return { provider: prov, model: handle };
  }
  // Try heuristic split on first slash; fall back to "letta" provider.
  if (handle.includes('/')) {
    const prov = handle.split('/')[0];
    if (prov in table) return { provider: prov, model: handle };
  }
  if (handle === 'letta-default') return { provider: 'letta', model: handle };
  return { provider: CUSTOM_HANDLE_VALUE, model: handle };
}
