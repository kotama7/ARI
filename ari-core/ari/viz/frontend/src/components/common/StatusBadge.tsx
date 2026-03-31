import { Badge } from './Badge';

export function StatusBadge({ status }: { status: string }) {
  const s = status.toLowerCase();

  if (s === 'running') {
    return <Badge variant="yellow">{'⏳'} Running</Badge>;
  }
  if (s === 'completed' || s === 'success') {
    return <Badge variant="green">{'✓'} Done</Badge>;
  }
  if (s === 'failed') {
    return <Badge variant="red">{'✗'} Failed</Badge>;
  }
  return <Badge variant="muted">{status}</Badge>;
}
