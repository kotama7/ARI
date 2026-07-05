// ARI Dashboard API – SSH / HPC probe family.

import { post } from './client';

export async function testSSH(
  data: any,
): Promise<{ ok: boolean; info?: string; error?: string }> {
  return post('/api/ssh/test', data);
}
