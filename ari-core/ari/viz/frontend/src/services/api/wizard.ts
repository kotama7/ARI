// ARI Dashboard API – wizard / chat / file-upload family.

import { API_BASE, post } from './client';

export async function chatGoal(
  messages: any[],
): Promise<{ reply?: string; ready?: boolean; md?: string; error?: string }> {
  return post('/api/chat-goal', { messages });
}

export async function generateConfig(goal: string): Promise<any> {
  return post('/api/config/generate', { goal });
}

// ── file upload ────────────────────────────────
// Bespoke octet-stream POST (X-Filename / X-File-Type headers). Throws on
// non-2xx, preserving the original error message verbatim.
export async function uploadFile(
  file: File,
  fileType: string,
): Promise<{ ok: boolean; path?: string; filename?: string; error?: string }> {
  const res = await fetch(`${API_BASE}/api/upload`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/octet-stream',
      'X-Filename': file.name,
      'X-File-Type': fileType,
    },
    body: file,
  });
  if (!res.ok) throw new Error(`POST /api/upload failed: ${res.status}`);
  return res.json();
}

export async function deleteUploadedFile(
  filename: string,
): Promise<{ ok: boolean; error?: string }> {
  return post('/api/upload/delete', { filename });
}
