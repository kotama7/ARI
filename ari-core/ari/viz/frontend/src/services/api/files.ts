// ARI Dashboard API – checkpoint file management (Overleaf-like) family.

import { get, post } from './client';

export interface CheckpointFile {
  name: string;
  size: number;
  editable: boolean;
  ext: string;
  abs_path: string;
}

export async function fetchCheckpointFiles(
  id: string,
): Promise<{ id: string; path: string; files: CheckpointFile[]; error?: string }> {
  return get(`/api/checkpoint/${encodeURIComponent(id)}/files`);
}

export async function fetchCheckpointFileContent(
  id: string,
  filename: string,
): Promise<{ name: string; content: string; error?: string }> {
  return get(`/api/checkpoint/${encodeURIComponent(id)}/file?name=${encodeURIComponent(filename)}`);
}

export async function fetchCheckpointFilecontent(
  id: string,
  path: string,
  nodeId?: string,
): Promise<{ name?: string; content?: string; error?: string }> {
  const nq = nodeId ? `&node_id=${encodeURIComponent(nodeId)}` : '';
  return get(
    `/api/checkpoint/${encodeURIComponent(id)}/filecontent?path=${encodeURIComponent(path)}${nq}`,
  );
}

// File tree for a checkpoint (or a node's work_dir when nodeId is set). Returns
// 200 + {error} for application errors; callers read data.error/data.tree.
export async function fetchCheckpointFiletree(
  id: string,
  nodeId?: string,
): Promise<{ tree?: any[]; error?: string }> {
  const qs = nodeId ? `?node_id=${encodeURIComponent(nodeId)}` : '';
  return get(`/api/checkpoint/${encodeURIComponent(id)}/filetree${qs}`);
}

export async function saveCheckpointFile(
  checkpointId: string,
  filename: string,
  content: string,
): Promise<{ ok: boolean; error?: string }> {
  return post('/api/checkpoint/file/save', {
    checkpoint_id: checkpointId,
    filename,
    content,
  });
}

// Bespoke octet-stream POST (X-Filename header). Throws on non-2xx, preserving
// the original error message verbatim.
export async function uploadCheckpointFile(
  checkpointId: string,
  file: File,
): Promise<{ ok: boolean; name?: string; error?: string }> {
  const res = await fetch(`/api/checkpoint/${encodeURIComponent(checkpointId)}/file/upload`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/octet-stream',
      'X-Filename': file.name,
    },
    body: file,
  });
  if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
  return res.json();
}

export async function deleteCheckpointFile(
  checkpointId: string,
  filename: string,
): Promise<{ ok: boolean; error?: string }> {
  return post('/api/checkpoint/file/delete', {
    checkpoint_id: checkpointId,
    filename,
  });
}

export async function compileCheckpointPaper(
  checkpointId: string,
  mainFile?: string,
): Promise<{ ok: boolean; log: string }> {
  return post('/api/checkpoint/compile', {
    checkpoint_id: checkpointId,
    main_file: mainFile || 'full_paper.tex',
  });
}
