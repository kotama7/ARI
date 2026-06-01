// ARI Dashboard – Results page shared types.
// Extracted verbatim from resultSections.tsx (refactor req 15 finer split,
// per refactoring/notes/03 DAG). Type-only; no runtime code.

export type OrsRenderInput = {
  repro: any;
  orsRubric?: Record<string, any>;       // full rubric envelope (with .rubric tree)
  orsGrade?: Record<string, any>;
  orsPhase1?: Record<string, any>;
  orsReplicator?: Record<string, any>;
  orsSeed?: Record<string, any>;
  orsRubricMeta?: Record<string, any>;
  ckptId: string;
  reproLog: { open: boolean; loading: boolean; content: string | null; path: string | null };
  onToggleLog: () => void;
  onRefreshLog: () => void;
  t: (key: string) => string;
};

export type RubricNode = {
  id?: string;
  requirements?: string;
  weight?: number;
  task_category?: string;
  finegrained_task_category?: string;
  sub_tasks?: RubricNode[];
};

export type LeafGrade = Record<string, any>;

export type StageState = 'ok' | 'fail' | 'partial' | 'pending' | 'skipped';
