// lang-bridge.ts — single source of the language⇔locale mapping shared by the
// VitePress docs and the bespoke landing (see docs/README.md). On every docs route the
// active locale (from the /docs/(ja|zh)/ URL) is written to
// localStorage('ari-lang'), so returning to the landing keeps the same
// language. The landing's "Docs" link reads the same key to deep-link the
// matching locale. SSR-guarded by the caller.
export function langBridge(): void {
  try {
    const p = location.pathname
    const m = p.match(/\/docs\/(ja|zh)(\/|$)/)
    const loc = m ? m[1] : 'en'
    localStorage.setItem('ari-lang', loc)
  } catch {
    /* localStorage unavailable — no-op */
  }
}
