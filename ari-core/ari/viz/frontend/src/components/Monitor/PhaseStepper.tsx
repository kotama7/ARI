// ARI Dashboard – Phase Stepper bar (React port of updatePhaseStepper from dashboard.js)

import React from 'react';
import { useAppContext } from '../../context/AppContext';

// ── Phase definitions ─────────────────────────────

interface PhaseInfo {
  id: string;
  icon: string;
  label: string;
}

const PHASES: PhaseInfo[] = [
  { id: 'starting', icon: '⏳', label: 'Starting' },
  { id: 'idea', icon: '💡', label: 'Idea' },
  { id: 'bfts', icon: '🔬', label: 'BFTS' },
  { id: 'paper', icon: '📄', label: 'Paper' },
  { id: 'review', icon: '🔍', label: 'Review' },
];

/** Maps raw current_phase values to canonical phase IDs. */
const PHASE_MAP: Record<string, string> = {
  starting: 'starting',
  idea: 'idea',
  bfts: 'bfts',
  idle: 'bfts',
  coding: 'bfts',
  evaluation: 'bfts',
  eval: 'bfts',
  paper: 'paper',
  review: 'review',
  done: 'review',
};

const ORDER = PHASES.map((p) => p.id);

// ── Component ─────────────────────────────────────

export function PhaseStepper() {
  const { state } = useAppContext();

  const rawPhase = state?.current_phase ?? '';
  const flags = (state as any)?.phase_flags as Record<string, boolean> | undefined;

  let activeId: string | null = null;
  if (rawPhase === 'idle') {
    // 'idle' is ambiguous: could be pre-idea or mid-BFTS.
    // Use phase_flags to disambiguate.
    if (flags?.bfts || flags?.coding || flags?.evaluation) {
      activeId = 'bfts';
    } else if (flags?.idea) {
      activeId = 'idea';
    } else if (state?.running_pid) {
      activeId = 'starting';
    } else {
      activeId = null;
    }
  } else {
    activeId = PHASE_MAP[rawPhase] ?? (state?.running_pid ? 'starting' : null);
  }
  const activeIdx = activeId ? ORDER.indexOf(activeId) : -1;

  // Detect error state from exit code (mirroring _lastExitCode logic)
  const hasError = state?.status_label?.toLowerCase().includes('error') ?? false;

  // All 5 stepper phases are complete once review_report.json exists
  // (activeId === 'review').  Later pipeline stages (e.g. reproducibility_check)
  // are not represented in the stepper, so the process may still be running.
  const allDone = activeId === 'review';

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 0,
        marginBottom: 16,
        overflowX: 'auto',
        padding: '4px 0',
      }}
    >
      {PHASES.map((phase, i) => {
        let cls = 'phase-step';
        if (allDone) {
          cls += ' done';
        } else if (hasError && i === activeIdx) {
          cls += ' error';
        } else if (i < activeIdx) {
          cls += ' done';
        } else if (i === activeIdx) {
          cls += ' active';
        }

        return (
          <React.Fragment key={phase.id}>
            {i > 0 && <div className="pstep-arrow">{'→'}</div>}
            <div className={cls} id={`pstep-${phase.id}`} data-phase={phase.id}>
              <div className="pstep-icon">{phase.icon}</div>
              <div className="pstep-label">{phase.label}</div>
            </div>
          </React.Fragment>
        );
      })}
    </div>
  );
}

export default PhaseStepper;
