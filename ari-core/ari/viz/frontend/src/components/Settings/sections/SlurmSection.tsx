import { Card } from '../../common';
import { inputStyle, labelStyle } from '../settingsStyles';
import type { TFn } from '../settingsTypes';

interface Partition {
  name: string;
  nodes: number;
  cpus: number;
}

interface SlurmSectionProps {
  t: TFn;
  partitions: Partition[];
  selectedPartitions: string[];
  setSelectedPartitions: (v: string[]) => void;
  onDetect: () => void;
  cpus: number;
  setCpus: (v: number) => void;
  memGb: number;
  setMemGb: (v: number) => void;
  walltime: string;
  setWalltime: (v: string) => void;
}

export function SlurmSection({
  t,
  partitions,
  selectedPartitions,
  setSelectedPartitions,
  onDetect,
  cpus,
  setCpus,
  memGb,
  setMemGb,
  walltime,
  setWalltime,
}: SlurmSectionProps) {
  return (
    <Card title={t('settings_slurm')}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
        {/* Partition multi-select */}
        <div style={{ gridColumn: '1 / -1' }}>
          <label style={labelStyle}>
            {t('s_partition')}
            <button
              className="btn btn-outline btn-sm"
              style={{ marginLeft: '8px' }}
              onClick={onDetect}
            >
              Detect
            </button>
          </label>
          {partitions.length > 0 ? (
            <select
              multiple
              value={selectedPartitions}
              onChange={(e) => {
                const opts = Array.from(e.target.selectedOptions).map((o) => o.value);
                setSelectedPartitions(opts);
              }}
              style={{ ...inputStyle, height: '100px' }}
            >
              {partitions.map((p) => (
                <option key={p.name} value={p.name}>
                  {p.name} ({p.nodes} nodes, {p.cpus} cpus)
                </option>
              ))}
            </select>
          ) : (
            <div style={{ fontSize: '.78rem', color: 'var(--muted)' }}>
              {selectedPartitions.length > 0
                ? selectedPartitions.join(', ')
                : 'Click Detect to discover partitions'}
            </div>
          )}
        </div>

        {/* CPUs */}
        <div>
          <label style={labelStyle}>{t('s_cpus')}</label>
          <input
            type="number"
            value={cpus}
            onChange={(e) => setCpus(parseInt(e.target.value) || 8)}
            style={inputStyle}
          />
        </div>

        {/* Memory */}
        <div>
          <label style={labelStyle}>Memory (GB)</label>
          <input
            type="number"
            value={memGb}
            onChange={(e) => setMemGb(parseInt(e.target.value) || 32)}
            style={inputStyle}
          />
        </div>

        {/* Walltime */}
        <div>
          <label style={labelStyle}>{t('s_walltime')}</label>
          <input
            type="text"
            value={walltime}
            onChange={(e) => setWalltime(e.target.value)}
            style={inputStyle}
          />
        </div>
      </div>
    </Card>
  );
}
