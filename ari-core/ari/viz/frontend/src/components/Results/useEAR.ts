// ARI Dashboard – EAR (Experiment Artifact Repository) action-state hook.
// Extracted from ResultsPage.tsx (refactor req 15, optional §3 high-risk seam).
// Owns the curate/publish/publish.yaml-editor state that lived in the container
// and was used only by the EAR section. Initial values are verbatim; `ear` /
// `earLoading` stay in the container (they are part of the data spine that
// loadResults() sets) and are passed into <EarSection> as props.

import { useState } from 'react';
import type { PublishRecord, PublishYamlData } from '../../services/api';

export function useEAR() {
  const [curating, setCurating] = useState(false);
  const [curateMsg, setCurateMsg] = useState<string>('');
  const [publishing, setPublishing] = useState(false);
  const [publishMsg, setPublishMsg] = useState<string>('');
  const [publishRecord, setPublishRecord] = useState<PublishRecord | null>(null);
  const [publishBackend, setPublishBackend] = useState<string>('local-tarball');
  const [publishConsent, setPublishConsent] = useState<boolean>(false);

  // publish.yaml editor state
  const [pyEditorOpen, setPyEditorOpen] = useState(false);
  const [pyData, setPyData] = useState<PublishYamlData | null>(null);
  const [pyText, setPyText] = useState<string>('');
  const [pyExists, setPyExists] = useState<boolean>(false);
  const [pyMode, setPyMode] = useState<'form' | 'raw'>('form');
  const [pySaving, setPySaving] = useState(false);
  const [pyMsg, setPyMsg] = useState<string>('');

  return {
    curating, setCurating, curateMsg, setCurateMsg,
    publishing, setPublishing, publishMsg, setPublishMsg,
    publishRecord, setPublishRecord, publishBackend, setPublishBackend,
    publishConsent, setPublishConsent,
    pyEditorOpen, setPyEditorOpen, pyData, setPyData,
    pyText, setPyText, pyExists, setPyExists,
    pyMode, setPyMode, pySaving, setPySaving, pyMsg, setPyMsg,
  };
}
