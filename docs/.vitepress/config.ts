import { defineConfig } from 'vitepress'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// docs/ is the VitePress srcDir; this file lives in docs/.vitepress/.
const DOCS = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

const ORIGIN = 'https://kotama7.github.io'
const BASE = '/ARI/docs/' // GitHub Pages project sub-path (see docs/README.md)

// ── fs-driven sidebar ──────────────────────────────────────────────────────
// Auto-localises: each locale dir (root=en, ja/, zh/) is scanned, and the
// item label is the file's own H1 (so ja/zh files show their translated title).
function h1Of(abs: string): string {
  try {
    for (const ln of fs.readFileSync(abs, 'utf-8').split('\n')) {
      const m = ln.match(/^#\s+(.+?)\s*$/)
      if (m) return m[1].replace(/`/g, '').replace(/\s*\(.*?\)\s*$/, '').trim()
    }
  } catch {}
  return path.basename(abs, '.md')
}
function listGroup(localeDir: string, sub: string, text: string) {
  const dir = path.join(DOCS, localeDir, sub)
  if (!fs.existsSync(dir)) return null
  const items = fs.readdirSync(dir)
    .filter((f) => f.endsWith('.md') && f !== 'README.md')
    .sort()
    .map((f) => {
      const rel = path.posix.join('/', localeDir, sub, f.replace(/\.md$/, ''))
      return { text: h1Of(path.join(dir, f)), link: rel }
    })
  return items.length ? { text, collapsed: false, items } : null
}
function sidebar(localeDir: string, labels: Record<string, string>) {
  const groups = [
    listGroup(localeDir, 'getting-started', labels.gs),
    listGroup(localeDir, 'concepts', labels.concepts),
    listGroup(localeDir, 'guides', labels.guides),
    listGroup(localeDir, 'guides/paperbench', labels.paperbench),
    listGroup(localeDir, 'reference', labels.reference),
    listGroup(localeDir, 'about', labels.about),
  ].filter(Boolean)
  return groups as any
}

const SIDE_LABELS = {
  en: { gs: 'Getting Started', concepts: 'Concepts', guides: 'Guides', paperbench: 'PaperBench', reference: 'Reference', about: 'About' },
  ja: { gs: 'はじめに', concepts: 'コンセプト', guides: 'ガイド', paperbench: 'PaperBench', reference: 'リファレンス', about: 'About' },
  zh: { gs: '入门', concepts: '概念', guides: '指南', paperbench: 'PaperBench', reference: '参考', about: '关于' },
}

const NAV = {
  en: [{ text: 'Home', link: '/' }, { text: '↩ ARI site', link: '/../' }],
  ja: [{ text: 'ホーム', link: '/ja/' }, { text: '↩ ARI サイト', link: '/../' }],
  zh: [{ text: '首页', link: '/zh/' }, { text: '↩ ARI 站点', link: '/../' }],
}

export default defineConfig({
  base: BASE,
  title: 'ARI Docs',
  description: 'Technical reference for ARI — Autonomous Research Infrastructure.',
  lang: 'en-US',
  cleanUrls: true,
  // The markdown tree carries pre-existing cross-tree links owned by the
  // docs-expansion effort; do not fail the build on them (the markdown link
  // integrity gate lives in scripts/docs/check_doc_links.py).
  ignoreDeadLinks: true,
  // The markdown tree was authored for plain rendering, not for VitePress's
  // Vue-flavoured markdown. Two neutralisations let the source be consumed
  // UNMODIFIED:
  //   1. html:false — bare angle-bracket placeholders (<node_id>, <hash>) in
  //      prose are escaped instead of parsed as (unclosed) HTML tags. The tree
  //      has no intentional inline HTML (verified), so nothing is lost.
  //   2. text-renderer override — `{{ }}` in prose (e.g. workflow.yaml template
  //      vars) is escaped to entities so Vue does not treat it as interpolation.
  //      Only prose text tokens are touched; code spans/blocks (which VitePress
  //      renders v-pre) keep their `{{ }}` verbatim.
  markdown: {
    html: false,
    config(md) {
      const escMustache = (s: string) =>
        s.replace(/\{\{/g, '&#123;&#123;').replace(/\}\}/g, '&#125;&#125;')
      // Escape mustaches in prose text AND inline code (`{{ari_root}}` etc.),
      // which VitePress does not v-pre. Fenced code blocks are already v-pre.
      for (const rule of ['text', 'code_inline'] as const) {
        const orig =
          md.renderer.rules[rule] ||
          ((tokens: any, idx: number, opts: any, _env: any, self: any) =>
            self.renderToken(tokens, idx, opts))
        md.renderer.rules[rule] = (tokens: any, idx: number, opts: any, env: any, self: any) =>
          escMustache(orig(tokens, idx, opts, env, self))
      }
    },
  },
  srcExclude: ['**/README.md', 'PLAN_homepage_redesign.md', '**/_archive/**'],
  sitemap: { hostname: ORIGIN + BASE },
  head: [
    ['link', { rel: 'icon', type: 'image/png', sizes: '32x32', href: BASE + 'assets/favicon.png' }],
    ['link', { rel: 'apple-touch-icon', href: BASE + 'assets/apple-touch-icon.png' }],
    ['meta', { name: 'theme-color', content: '#030712' }],
  ],
  themeConfig: {
    logo: '/assets/favicon.png',
    search: { provider: 'local' }, // minisearch — CJK capable
    socialLinks: [{ icon: 'github', link: 'https://github.com/kotama7/ARI' }],
  },
  locales: {
    root: { label: 'English', lang: 'en', themeConfig: { nav: NAV.en, sidebar: sidebar('', SIDE_LABELS.en) } },
    ja: { label: '日本語', lang: 'ja', link: '/ja/', themeConfig: { nav: NAV.ja, sidebar: sidebar('ja', SIDE_LABELS.ja) } },
    zh: { label: '中文', lang: 'zh', link: '/zh/', themeConfig: { nav: NAV.zh, sidebar: sidebar('zh', SIDE_LABELS.zh) } },
  },
  // Per-page canonical + hreflang alternates (true multilingual SEO — the L3 win).
  transformPageData(pageData) {
    const rel = pageData.relativePath.replace(/(^|\/)index\.md$/, '$1').replace(/\.md$/, '')
    const url = (p: string) => ORIGIN + BASE + p
    // map this page to its locale siblings (mirror layout: root=en, ja/, zh/)
    const stripLoc = (p: string) => p.replace(/^(ja|zh)\//, '')
    const bare = stripLoc(rel)
    const alts: Array<[string, string]> = [
      ['en', url(bare)],
      ['ja', url('ja/' + bare).replace(/\/$/, '/')],
      ['zh', url('zh/' + bare).replace(/\/$/, '/')],
    ]
    pageData.frontmatter.head ??= []
    pageData.frontmatter.head.push(['link', { rel: 'canonical', href: url(rel) }])
    for (const [lang, href] of alts) {
      pageData.frontmatter.head.push(['link', { rel: 'alternate', hreflang: lang, href }])
    }
    pageData.frontmatter.head.push(['link', { rel: 'alternate', hreflang: 'x-default', href: url(bare) }])
    pageData.frontmatter.head.push(['meta', { property: 'og:url', content: url(rel) }])
    pageData.frontmatter.head.push(['meta', { property: 'og:image', content: ORIGIN + BASE + 'assets/og-image.png' }])
  },
})
