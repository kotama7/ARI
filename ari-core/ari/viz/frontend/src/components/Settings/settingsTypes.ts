// Shared prop/data types for the decomposed Settings sections.
// Extracted from SettingsPage.tsx (SkillInfo was :31-36) so section
// components can import them without re-declaring. No runtime code.

// The single translator function threaded from the orchestrator's useI18n().
// Passing the one `t` down (rather than each section calling useI18n itself)
// keeps the whole panel bound to a single language state, preserving the
// pre-split behaviour where a language switch re-renders every label at once.
export type TFn = (key: string) => string;

// A read-only skill row served by GET /api/skills (SkillsSection table).
export interface SkillInfo {
  name: string;
  display_name: string;
  description: string;
  requires_env?: string[];
}

// Letta restart deployment path — matches _api_memory_start_local's `path`
// contract (auto/docker/singularity/pip).
export type LettaDeployment = 'auto' | 'docker' | 'singularity' | 'pip';
