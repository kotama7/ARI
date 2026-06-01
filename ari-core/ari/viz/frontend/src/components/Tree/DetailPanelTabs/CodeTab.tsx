// ARI Dashboard – DetailPanel "Code" tab.
// Extracted verbatim from DetailPanel.tsx (refactor req 15): the code-tab JSX
// block. The `activeTab === 'code' && codeSnippets.length > 0` guard stays in
// the container; this renders the snippet list.

import React from 'react';

interface CodeTabProps {
  codeSnippets: string[];
}

export function CodeTab({ codeSnippets }: CodeTabProps) {
  return (
    <div>
      {codeSnippets.map((c, i) => (
        <React.Fragment key={i}>
          <div
            style={{
              fontSize: '.72rem',
              color: 'var(--muted)',
              margin: '6px 0 2px',
            }}
          >
            --- Snippet {i + 1} / {codeSnippets.length} ---
          </div>
          <pre
            className="code"
            style={{
              maxHeight: 400,
              overflow: 'auto',
              fontSize: '.72rem',
              lineHeight: 1.5,
              marginBottom: 8,
            }}
          >
            {c}
          </pre>
        </React.Fragment>
      ))}
    </div>
  );
}
