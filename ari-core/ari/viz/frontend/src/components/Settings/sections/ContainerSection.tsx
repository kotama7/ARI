import { Card } from '../../common';
import { inputStyle, labelStyle } from '../settingsStyles';

interface ContainerSectionProps {
  containerMode: string;
  setContainerMode: (v: string) => void;
  containerPull: string;
  setContainerPull: (v: string) => void;
  containerImage: string;
  setContainerImage: (v: string) => void;
  containerRuntime: string;
  containerVersion: string;
  onDetectRuntime: () => void;
}

export function ContainerSection({
  containerMode,
  setContainerMode,
  containerPull,
  setContainerPull,
  containerImage,
  setContainerImage,
  containerRuntime,
  containerVersion,
  onDetectRuntime,
}: ContainerSectionProps) {
  return (
    <Card title="Container">
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
        <div>
          <label style={labelStyle}>Mode</label>
          <select
            value={containerMode}
            onChange={(e) => setContainerMode(e.target.value)}
            style={inputStyle}
          >
            <option value="auto">Auto</option>
            <option value="docker">Docker</option>
            <option value="singularity">Singularity</option>
            <option value="apptainer">Apptainer</option>
            <option value="none">None</option>
          </select>
        </div>
        <div>
          <label style={labelStyle}>Pull Policy</label>
          <select
            value={containerPull}
            onChange={(e) => setContainerPull(e.target.value)}
            style={inputStyle}
          >
            <option value="always">Always</option>
            <option value="on_start">On Start</option>
            <option value="never">Never</option>
          </select>
        </div>
        <div style={{ gridColumn: '1 / -1' }}>
          <label style={labelStyle}>Image</label>
          <input
            type="text"
            value={containerImage}
            onChange={(e) => setContainerImage(e.target.value)}
            placeholder="ghcr.io/kotama7/ari:latest"
            style={inputStyle}
          />
        </div>
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: '8px' }}>
          <button className="btn btn-outline btn-sm" onClick={onDetectRuntime}>
            Detect Runtime
          </button>
          {containerRuntime && (
            <span
              className={containerRuntime !== 'none' ? 'badge badge-green' : 'badge'}
              style={{ fontSize: '.75rem' }}
            >
              {containerRuntime}
              {containerRuntime !== 'none' ? ' ✓' : ''}
              {containerVersion ? ` (${containerVersion})` : ''}
            </span>
          )}
        </div>
      </div>
    </Card>
  );
}
