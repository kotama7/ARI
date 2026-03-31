import type { ChangeEvent, KeyboardEvent } from 'react';
import { useState, useRef, useEffect, useCallback } from 'react';
import { useI18n } from '../../i18n';
import * as api from '../../services/api';

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

interface UploadedFile {
  name: string;
  path: string;
  type: string;
}

interface StepGoalProps {
  wizMode: 'chat' | 'md';
  setWizMode: (mode: 'chat' | 'md') => void;
  chatHistory: ChatMessage[];
  setChatHistory: (h: ChatMessage[]) => void;
  chatGeneratedMd: string;
  setChatGeneratedMd: (md: string) => void;
  goalText: string;
  setGoalText: (text: string) => void;
  generatedMd: string;
  setGeneratedMd: (md: string) => void;
  uploadedFiles: UploadedFile[];
  setUploadedFiles: (files: UploadedFile[]) => void;
  savePath: string;
  setSavePath: (p: string) => void;
  onNext: () => void;
}

export function StepGoal({
  wizMode,
  setWizMode,
  chatHistory,
  setChatHistory,
  chatGeneratedMd,
  setChatGeneratedMd,
  goalText,
  setGoalText,
  generatedMd,
  setGeneratedMd,
  uploadedFiles,
  setUploadedFiles,
  savePath: _savePath,
  setSavePath,
  onNext,
}: StepGoalProps) {
  const { t } = useI18n();
  const [chatInput, setChatInput] = useState('');
  const [chatSending, setChatSending] = useState(false);
  const [genStatus, setGenStatus] = useState('');
  const [uploadStatus, setUploadStatus] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const chatContainerRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = useCallback(() => {
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight;
    }
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [chatHistory, chatSending, scrollToBottom]);

  const handleChatSend = async () => {
    const text = chatInput.trim();
    if (!text || chatSending) return;
    setChatInput('');
    setChatSending(true);

    const newHistory = [...chatHistory, { role: 'user' as const, content: text }];
    setChatHistory(newHistory);

    try {
      const d = await api.chatGoal(newHistory);
      if (d.error) {
        setChatHistory([
          ...newHistory,
          { role: 'assistant', content: '⚠️ Error: ' + d.error },
        ]);
      } else {
        const updated = [...newHistory];
        if (d.reply) {
          updated.push({ role: 'assistant', content: d.reply });
        }
        if (d.ready && d.md) {
          setChatGeneratedMd(d.md);
          updated.push({
            role: 'assistant',
            content:
              '✅ Research goal is ready! You can review and edit the generated experiment.md below, then click Next →',
          });
        }
        setChatHistory(updated);
      }
    } catch (e: any) {
      setChatHistory([
        ...newHistory,
        { role: 'assistant', content: '⚠️ Network error: ' + (e.message || e) },
      ]);
    }
    setChatSending(false);
  };

  const handleChatKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleChatSend();
    }
  };

  const handleGenerate = async () => {
    const goal = goalText.trim();
    if (!goal) return;
    setGenStatus('Generating...');
    try {
      const d = await api.generateConfig(goal);
      if (d.md || d.config) {
        setGeneratedMd(d.md || d.config || '');
        setGenStatus('');
      } else if (d.error) {
        setGenStatus('Error: ' + d.error);
      } else {
        setGenStatus('');
      }
    } catch (e: any) {
      setGenStatus('Error: ' + (e.message || e));
    }
  };

  const handleUpload = async (
    e: ChangeEvent<HTMLInputElement>,
    fileType: string,
  ) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    setUploadStatus('Uploading ' + files.length + ' file(s)...');
    const newUploaded = [...uploadedFiles];
    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      try {
        const r = await api.uploadFile(file, fileType);
        if (r.ok) {
          newUploaded.push({ name: file.name, path: r.path || '', type: fileType });
          if (fileType === 'experiment' && /\.md$/i.test(file.name)) {
            const text = await file.text();
            setGeneratedMd(text);
            if (r.filename) setSavePath(r.filename);
          }
        }
      } catch {
        newUploaded.push({ name: file.name, path: 'error', type: fileType });
      }
    }
    setUploadedFiles(newUploaded);
    setUploadStatus('Done (' + files.length + ' files)');
  };

  return (
    <div>
      {/* Mode selector tabs */}
      <div
        style={{
          display: 'flex',
          gap: 0,
          marginBottom: 16,
          border: '1px solid var(--border)',
          borderRadius: 8,
          overflow: 'hidden',
        }}
      >
        <button
          onClick={() => setWizMode('chat')}
          style={{
            flex: 1,
            padding: '10px 0',
            background: wizMode === 'chat' ? 'rgba(59,130,246,.18)' : 'none',
            border: 'none',
            color: wizMode === 'chat' ? 'var(--blue-light)' : 'var(--muted)',
            fontWeight: wizMode === 'chat' ? 700 : 400,
            fontSize: '.88rem',
            cursor: 'pointer',
            borderRight: '1px solid var(--border)',
          }}
        >
          {'💬'} Chat Mode
          <br />
          <span style={{ fontSize: '.7rem', fontWeight: 400, color: 'var(--muted)' }}>
            Answer questions interactively
          </span>
        </button>
        <button
          onClick={() => setWizMode('md')}
          style={{
            flex: 1,
            padding: '10px 0',
            background: wizMode === 'md' ? 'rgba(59,130,246,.18)' : 'none',
            border: 'none',
            color: wizMode === 'md' ? 'var(--blue-light)' : 'var(--muted)',
            fontWeight: wizMode === 'md' ? 700 : 400,
            fontSize: '.88rem',
            cursor: 'pointer',
          }}
        >
          {'📝'} Write MD
          <br />
          <span style={{ fontSize: '.7rem', fontWeight: 400 }}>
            Write experiment.md directly
          </span>
        </button>
      </div>

      {/* CHAT MODE */}
      {wizMode === 'chat' && (
        <div>
          <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
            <div
              ref={chatContainerRef}
              style={{
                height: 320,
                overflowY: 'auto',
                padding: 16,
                display: 'flex',
                flexDirection: 'column',
                gap: 10,
              }}
            >
              {/* Initial greeting */}
              <div style={{ alignSelf: 'flex-start', maxWidth: '85%' }}>
                <div
                  style={{
                    background: 'rgba(59,130,246,.12)',
                    border: '1px solid rgba(59,130,246,.3)',
                    borderRadius: '12px 12px 12px 2px',
                    padding: '10px 14px',
                    fontSize: '.84rem',
                    lineHeight: 1.6,
                  }}
                >
                  {'👋'} Let's define your research goal together!
                  <br />
                  <strong>What would you like to optimize or investigate?</strong>
                  <br />
                  <span style={{ color: 'var(--muted)', fontSize: '.78rem' }}>
                    (e.g. "inference latency for a neural network", "training speed for a
                    transformer", "memory usage")
                  </span>
                </div>
              </div>

              {/* Chat messages */}
              {chatHistory.map((msg, i) => {
                const isUser = msg.role === 'user';
                return (
                  <div
                    key={i}
                    style={{
                      alignSelf: isUser ? 'flex-end' : 'flex-start',
                      maxWidth: '85%',
                    }}
                  >
                    <div
                      style={{
                        background: isUser
                          ? 'rgba(139,92,246,.15)'
                          : 'rgba(59,130,246,.12)',
                        border: `1px solid ${isUser ? 'rgba(139,92,246,.3)' : 'rgba(59,130,246,.3)'}`,
                        borderRadius: isUser
                          ? '12px 12px 2px 12px'
                          : '12px 12px 12px 2px',
                        padding: '10px 14px',
                        fontSize: '.84rem',
                        lineHeight: 1.6,
                        whiteSpace: 'pre-wrap',
                      }}
                    >
                      {msg.content}
                    </div>
                  </div>
                );
              })}

              {/* Typing indicator */}
              {chatSending && (
                <div
                  style={{
                    alignSelf: 'flex-start',
                    color: 'var(--muted)',
                    fontSize: '.78rem',
                    padding: '4px 8px',
                  }}
                >
                  ...
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>

            {/* Input area */}
            <div
              style={{
                borderTop: '1px solid var(--border)',
                padding: 10,
                display: 'flex',
                gap: 8,
                alignItems: 'flex-end',
              }}
            >
              <textarea
                rows={2}
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                onKeyDown={handleChatKeyDown}
                disabled={chatSending}
                style={{
                  flex: 1,
                  resize: 'none',
                  background: 'rgba(255,255,255,.05)',
                  border: '1px solid var(--border)',
                  borderRadius: 8,
                  padding: 8,
                  color: 'var(--text)',
                  fontSize: '.85rem',
                }}
                placeholder="Type your answer..."
              />
              <button
                className="btn btn-primary"
                onClick={handleChatSend}
                disabled={chatSending}
                style={{ padding: '8px 16px', whiteSpace: 'nowrap' }}
              >
                Send {'↵'}
              </button>
            </div>
          </div>

          {/* Generated MD preview */}
          {chatGeneratedMd && (
            <div style={{ marginTop: 12 }}>
              <div
                className="card"
                style={{ border: '1.5px solid var(--green)' }}
              >
                <div className="card-title" style={{ color: 'var(--green)' }}>
                  {'✅'} experiment.md generated
                </div>
                <textarea
                  rows={12}
                  value={chatGeneratedMd}
                  onChange={(e) => setChatGeneratedMd(e.target.value)}
                  style={{ width: '100%', fontFamily: 'monospace', fontSize: '.82rem' }}
                />
                <div
                  style={{
                    marginTop: 8,
                    fontSize: '.78rem',
                    color: 'var(--muted)',
                  }}
                >
                  You can edit this before proceeding.
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* MD MODE */}
      {wizMode === 'md' && (
        <div>
          <div className="card">
            <div className="card-title">{'📝'} Write experiment.md</div>
            <div
              style={{ fontSize: '.78rem', color: 'var(--muted)', marginBottom: 8 }}
            >
              Write your experiment configuration in Markdown. Required sections:{' '}
              <code>## Research Goal</code>, <code>## Evaluation Metric</code>,{' '}
              <code>## Constraints</code>
            </div>
            <textarea
              rows={14}
              value={goalText}
              onChange={(e) => setGoalText(e.target.value)}
              style={{ fontFamily: 'monospace', fontSize: '.82rem', width: '100%' }}
              placeholder={`## Research Goal\n\n\n## Evaluation Metric\nMaximize the primary score metric.\n\n## Constraints\n- Describe your platform and toolchain\n- Baseline: your current implementation`}
            />
            <div
              style={{
                display: 'flex',
                gap: 10,
                alignItems: 'center',
                marginTop: 8,
              }}
            >
              <button className="btn btn-outline" onClick={handleGenerate}>
                {'⚡'} Generate from summary
              </button>
              <span style={{ fontSize: '.8rem', color: 'var(--muted)' }}>
                {genStatus}
              </span>
            </div>
          </div>

          {/* Generated card */}
          {generatedMd && (
            <div className="card" style={{ marginTop: 12 }}>
              <div className="card-title">Generated experiment.md</div>
              <textarea
                rows={10}
                value={generatedMd}
                onChange={(e) => setGeneratedMd(e.target.value)}
                style={{ width: '100%', fontFamily: 'monospace', fontSize: '.82rem' }}
              />
            </div>
          )}
        </div>
      )}

      {/* Upload Files */}
      <div
        className="card"
        style={{
          marginTop: 12,
          border: '1.5px dashed var(--border)',
          background: 'rgba(255,255,255,.02)',
        }}
      >
        <div className="card-title">{t('upload_title')}</div>
        <div style={{ display: 'flex', gap: 10, marginBottom: 8 }}>
          <label style={{ flex: 1 }}>
            <div style={{ fontSize: '.75rem', color: 'var(--muted)', marginBottom: 4 }}>
              experiment.md
            </div>
            <input
              type="file"
              accept=".md,.txt,.yaml,.yml"
              style={{ width: '100%' }}
              onChange={(e) => handleUpload(e, 'experiment')}
            />
          </label>
          <label style={{ flex: 1 }}>
            <div style={{ fontSize: '.75rem', color: 'var(--muted)', marginBottom: 4 }}>
              {t('upload_extra_files')}
            </div>
            <input
              type="file"
              multiple
              style={{ width: '100%' }}
              onChange={(e) => handleUpload(e, 'extra')}
            />
          </label>
        </div>
        <div style={{ fontSize: '.78rem', maxHeight: 100, overflow: 'auto' }}>
          {uploadedFiles.map((f, i) => (
            <div
              key={i}
              style={{ color: f.path === 'error' ? 'var(--red)' : 'var(--green)' }}
            >
              {f.path === 'error'
                ? `✗ ${f.name}: error`
                : `✓ ${f.name} → ${f.path}`}
            </div>
          ))}
        </div>
        <span
          style={{
            fontSize: '.8rem',
            color: uploadStatus.startsWith('Done') ? 'var(--green)' : 'var(--muted)',
          }}
        >
          {uploadStatus}
        </span>
      </div>

      {/* Next button */}
      <div style={{ marginTop: 16, display: 'flex', justifyContent: 'flex-end' }}>
        <button className="btn btn-primary" onClick={onNext}>
          Next {'→'}
        </button>
      </div>
    </div>
  );
}
