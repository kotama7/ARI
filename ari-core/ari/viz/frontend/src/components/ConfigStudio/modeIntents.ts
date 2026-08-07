// ARI Dashboard – the two ADR-09 mode INTENTS (accepted 2026-07-27).
//
// Frontend transcription of `ari.config.field_registry.MODE_INTERLOCK_PAIRS`
// (which is itself the single source the resolver's INTERLOCK_PAIRS aliases
// and the launch path's `_mode_selection` reads). Each intent is a PAIR of
// registry leaves that must always be written together:
//
//   execution: ari.mode   + rqgm.enabled        (active: ari_rqgm)
//   paper:     paper.mode + rqgm.paper.enabled  (active: rqgm_archive)
//
// One user-facing control per pair writes BOTH keys; a document that carries
// one half without its agreeing twin is a 400 `mode_interlock_mismatch` at
// template/draft PATCH and at launch, and the RUNTIME resolver additionally
// warns + falls back to the fallback value. The two intents are strictly
// ORTHOGONAL — all four combinations are valid.
//
// Everything else under `rqgm.` (the ~96 epoch/kernel/governance/adversarial/
// budget tuning leaves) is NOT selectable from the GUI in this slice: it stays
// visible read-only. Widening the GUI write surface means editing this file
// AND `field_registry.MODE_SELECTION_PATHS` — never one alone.

export interface ModeIntentPair {
  /** Stable control id (i18n key prefix, test handle). */
  id: 'execution' | 'paper';
  /** The mode leaf (enum) the user picks. */
  modePath: string;
  /** Its boolean interlock twin. */
  enablePath: string;
  /** The mode value for which the interlock must be `true`. */
  activeMode: string;
  /** The default mode value (interlock `false`) the runtime falls back to. */
  fallbackMode: string;
}

export const MODE_INTENT_PAIRS: readonly ModeIntentPair[] = [
  {
    id: 'execution',
    modePath: 'ari.mode',
    enablePath: 'rqgm.enabled',
    activeMode: 'ari_rqgm',
    fallbackMode: 'simple_bfts',
  },
  {
    id: 'paper',
    modePath: 'paper.mode',
    enablePath: 'rqgm.paper.enabled',
    activeMode: 'rqgm_archive',
    fallbackMode: 'linear',
  },
];

/** i18n key of each intent's user-facing label — shared by the Studio control
 * and the launch review so the two surfaces cannot name the same intent
 * differently. */
export const MODE_INTENT_LABEL_KEY: Record<ModeIntentPair['id'], string> = {
  execution: 'studio_exec_mode_label',
  paper: 'studio_paper_mode_label',
};

/** The four GUI-selectable leaves (mirror of `MODE_SELECTION_PATHS`). */
export const MODE_SELECTION_PATHS: ReadonlySet<string> = new Set(
  MODE_INTENT_PAIRS.flatMap((p) => [p.modePath, p.enablePath]),
);

/** True for a leaf that belongs to the Studio's Execution section (the four
 * selectable mode leaves plus the read-only `rqgm.*` governance tree). */
export function isExecutionSectionPath(path: string, category: string): boolean {
  return category === 'Execution mode' || path.startsWith('rqgm.');
}

/**
 * Read one dotted leaf out of a config value map.
 *
 * The GUI documents are FLAT (`{"dotted.path": value}`) while the resolved
 * manifest from `POST .../resolve-config` is NESTED (`values.ari.mode` — the
 * resolver's `_set_leaf` shape). One reader handles both so the resolved-mode
 * display cannot silently read `undefined` off the wrong shape.
 */
export function readConfigLeaf(values: unknown, path: string): unknown {
  if (values === null || typeof values !== 'object') return undefined;
  const flat = values as Record<string, unknown>;
  if (Object.prototype.hasOwnProperty.call(flat, path)) return flat[path];
  let node: unknown = values;
  for (const part of path.split('.')) {
    if (node === null || typeof node !== 'object') return undefined;
    const rec = node as Record<string, unknown>;
    if (!Object.prototype.hasOwnProperty.call(rec, part)) return undefined;
    node = rec[part];
  }
  return node;
}

/**
 * The mode value implied by an interlock pair, or `null` when the pair is
 * INCONSISTENT (one half says active, the other does not). `null` is the
 * signal the GUI must refuse to launch on: draft validation rejects the pair
 * outright (`mode_interlock_mismatch`) even though the runtime would only
 * warn and fall back.
 */
export function pairSelection(
  pair: ModeIntentPair,
  mode: unknown,
  enabled: unknown,
): string | null {
  const wantsActive = mode === pair.activeMode;
  if (wantsActive !== Boolean(enabled)) return null;
  return wantsActive ? pair.activeMode : pair.fallbackMode;
}
