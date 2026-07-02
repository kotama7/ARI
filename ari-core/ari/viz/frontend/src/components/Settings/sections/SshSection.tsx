import { Card } from '../../common';
import { inputStyle, labelStyle } from '../settingsStyles';
import type { TFn } from '../settingsTypes';

interface SshSectionProps {
  t: TFn;
  sshHost: string;
  setSshHost: (v: string) => void;
  sshPort: number;
  setSshPort: (v: number) => void;
  sshUser: string;
  setSshUser: (v: string) => void;
  sshPath: string;
  setSshPath: (v: string) => void;
  sshKeyPath: string;
  setSshKeyPath: (v: string) => void;
  sshStatus: string;
  onTestSSH: () => void;
}

export function SshSection({
  t,
  sshHost,
  setSshHost,
  sshPort,
  setSshPort,
  sshUser,
  setSshUser,
  sshPath,
  setSshPath,
  sshKeyPath,
  setSshKeyPath,
  sshStatus,
  onTestSSH,
}: SshSectionProps) {
  return (
    <Card title={t('settings_ssh')}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
        <div>
          <label style={labelStyle}>Host</label>
          <input
            type="text"
            value={sshHost}
            onChange={(e) => setSshHost(e.target.value)}
            style={inputStyle}
          />
        </div>
        <div>
          <label style={labelStyle}>Port</label>
          <input
            type="number"
            value={sshPort}
            onChange={(e) => setSshPort(parseInt(e.target.value) || 22)}
            style={inputStyle}
          />
        </div>
        <div>
          <label style={labelStyle}>{t('ssh_username')}</label>
          <input
            type="text"
            value={sshUser}
            onChange={(e) => setSshUser(e.target.value)}
            style={inputStyle}
          />
        </div>
        <div>
          <label style={labelStyle}>Remote ARI Path</label>
          <input
            type="text"
            value={sshPath}
            onChange={(e) => setSshPath(e.target.value)}
            style={inputStyle}
          />
        </div>
        <div>
          <label style={labelStyle}>SSH Key Path</label>
          <input
            type="text"
            value={sshKeyPath}
            onChange={(e) => setSshKeyPath(e.target.value)}
            style={inputStyle}
          />
        </div>
        <div style={{ display: 'flex', alignItems: 'flex-end' }}>
          <button className="btn btn-outline btn-sm" onClick={onTestSSH}>
            Test SSH
          </button>
        </div>
      </div>
      {sshStatus && (
        <div style={{ marginTop: '8px', fontSize: '.82rem' }}>
          <span
            className={sshStatus.startsWith('✓') ? 'badge badge-green' : ''}
            style={sshStatus.startsWith('✗') ? { color: 'var(--red)' } : undefined}
          >
            {sshStatus}
          </span>
        </div>
      )}
    </Card>
  );
}
