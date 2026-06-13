// Custom VitePress theme: default theme + shared ARI brand tokens.
import DefaultTheme from 'vitepress/theme'
import type { Theme } from 'vitepress'
import './brand-bridge.css'
import { langBridge } from './lang-bridge'

export default {
  extends: DefaultTheme,
  enhanceApp({ router }) {
    // Cross-surface language continuity: keep localStorage('ari-lang') in sync
    // with the active /docs/(ja|zh)/ locale so the bespoke landing and the
    // VitePress docs stay on the same language (see docs/README.md). SSR-guarded.
    if (typeof window !== 'undefined') {
      langBridge()
      router.onAfterRouteChange = () => langBridge()
    }
  },
} satisfies Theme
