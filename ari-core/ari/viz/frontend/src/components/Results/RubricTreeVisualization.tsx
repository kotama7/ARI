import { useEffect, useMemo, useRef, useState } from 'react';
import * as d3 from 'd3';

export type RubricNode = {
  id?: string;
  requirements?: string;
  weight?: number;
  task_category?: string;
  finegrained_task_category?: string;
  sub_tasks?: RubricNode[];
};

type LeafGrade = Record<string, any>;

interface AggResult {
  score: number | null;
  passed: number;
  total: number;
  valid: boolean;
}

function aggregateScore(
  node: RubricNode,
  gradesById: Map<string, LeafGrade>,
): AggResult {
  const children = node.sub_tasks || [];
  if (children.length === 0) {
    const g = node.id ? gradesById.get(String(node.id)) : undefined;
    if (!g) return { score: null, passed: 0, total: 1, valid: false };
    const mean =
      typeof g.mean_score === 'number'
        ? g.mean_score
        : (g.passed_runs ?? 0) > 0
          ? 1
          : 0;
    return { score: mean, passed: mean >= 0.5 ? 1 : 0, total: 1, valid: true };
  }
  let totalWeight = 0;
  let weightedSum = 0;
  let passedLeaves = 0;
  let totalLeaves = 0;
  let anyValid = false;
  for (const c of children) {
    const cw = typeof c.weight === 'number' ? c.weight : 1;
    const sub = aggregateScore(c, gradesById);
    if (sub.valid && sub.score !== null) {
      totalWeight += cw;
      weightedSum += cw * sub.score;
      anyValid = true;
    }
    passedLeaves += sub.passed;
    totalLeaves += sub.total;
  }
  return {
    score: anyValid && totalWeight > 0 ? weightedSum / totalWeight : null,
    passed: passedLeaves,
    total: totalLeaves,
    valid: anyValid,
  };
}

const NW = 220;
const NH = 58;

function colorFor(score: number | null): string {
  if (score === null) return '#64748b';
  if (score >= 0.7) return '#22c55e';
  if (score >= 0.3) return '#f59e0b';
  return '#ef4444';
}

interface Props {
  node: RubricNode;
  gradesById: Map<string, LeafGrade>;
  noExplanationLabel: string;
}

export function RubricTreeVisualization({
  node,
  gradesById,
  noExplanationLabel,
}: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [selected, setSelected] = useState<RubricNode | null>(null);
  const [renderTick, setRenderTick] = useState(0);

  const aggMap = useMemo(() => {
    const m = new Map<RubricNode, AggResult>();
    const walk = (n: RubricNode) => {
      m.set(n, aggregateScore(n, gradesById));
      (n.sub_tasks || []).forEach(walk);
    };
    walk(node);
    return m;
  }, [node, gradesById]);

  // Sibling-relative weight = w / Σ(siblings' w). Reflects each child's
  // actual contribution to the parent's weighted-average score.
  const relWeightMap = useMemo(() => {
    const m = new Map<RubricNode, number>();
    const walk = (n: RubricNode) => {
      const kids = n.sub_tasks || [];
      const total = kids.reduce(
        (a, k) => a + (typeof k.weight === 'number' ? k.weight : 1),
        0,
      );
      kids.forEach((k) => {
        const w = typeof k.weight === 'number' ? k.weight : 1;
        m.set(k, total > 0 ? w / total : 0);
        walk(k);
      });
    };
    walk(node);
    return m;
  }, [node]);

  useEffect(() => {
    const svgEl = svgRef.current;
    if (!svgEl) return;
    d3.select(svgEl).selectAll('*').remove();

    const rect = svgEl.getBoundingClientRect();
    let W = rect.width > 100 ? rect.width : svgEl.clientWidth || 900;
    let H = rect.height > 100 ? rect.height : svgEl.clientHeight || 460;
    if (W < 100) W = 900;
    if (H < 100) H = 460;

    const root = d3.hierarchy<RubricNode>(node, (d) => d.sub_tasks || []);
    const treeLayout = d3
      .tree<RubricNode>()
      .nodeSize([NW + 24, NH + 60]);
    treeLayout(root);

    const svg = d3.select(svgEl);
    const g = svg.append('g').attr('class', 'rubric-tree-g');
    const zoomBehavior = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.2, 3])
      .on('zoom', (event) => {
        g.attr('transform', event.transform);
      });
    svg.call(zoomBehavior);

    // Edges — color from child aggregated score, thickness from sibling-relative weight.
    const links = root.links() as d3.HierarchyPointLink<RubricNode>[];
    const edgeGroup = g
      .selectAll<SVGGElement, d3.HierarchyPointLink<RubricNode>>('g.rubric-edge-g')
      .data(links)
      .enter()
      .append('g')
      .attr('class', 'rubric-edge-g');

    edgeGroup
      .append('path')
      .attr('class', 'rubric-edge')
      .attr('fill', 'none')
      .attr('stroke', (d) => {
        const sub = aggMap.get(d.target.data);
        return colorFor(sub?.score ?? null);
      })
      .attr('stroke-width', (d) => {
        const rw = relWeightMap.get(d.target.data) ?? 0;
        return 2 + rw * 12; // 0% → 2px, 100% → 14px
      })
      .attr('opacity', (d) => {
        const rw = relWeightMap.get(d.target.data) ?? 0;
        return 0.35 + rw * 0.55; // faint for tiny weights, strong for large
      })
      .attr('d', (d) => {
        const px = d.source.x ?? 0;
        const py = (d.source.y ?? 0) + NH;
        const cx = d.target.x ?? 0;
        const cy = d.target.y ?? 0;
        const midY = (py + cy) / 2;
        return `M${px},${py} C${px},${midY} ${cx},${midY} ${cx},${cy}`;
      });

    // Edge weight labels — sibling-relative percent shown at the midpoint.
    edgeGroup
      .append('rect')
      .attr('x', (d) => ((d.source.x ?? 0) + (d.target.x ?? 0)) / 2 - 22)
      .attr('y', (d) => ((d.source.y ?? 0) + NH + (d.target.y ?? 0)) / 2 - 9)
      .attr('width', 44)
      .attr('height', 16)
      .attr('rx', 8)
      .attr('fill', '#0f172a')
      .attr('stroke', (d) => {
        const sub = aggMap.get(d.target.data);
        return colorFor(sub?.score ?? null);
      })
      .attr('stroke-width', 1)
      .attr('opacity', 0.95);

    edgeGroup
      .append('text')
      .attr('x', (d) => ((d.source.x ?? 0) + (d.target.x ?? 0)) / 2)
      .attr('y', (d) => ((d.source.y ?? 0) + NH + (d.target.y ?? 0)) / 2 + 3)
      .attr('text-anchor', 'middle')
      .attr('font-size', '10px')
      .attr('font-weight', '700')
      .attr('fill', '#e2e8f0')
      .text((d) => {
        const rw = relWeightMap.get(d.target.data);
        return rw !== undefined ? `${(rw * 100).toFixed(0)}%` : '';
      });

    // Nodes
    const descendants = root.descendants() as d3.HierarchyPointNode<RubricNode>[];
    const nodeSel = g
      .selectAll<SVGGElement, d3.HierarchyPointNode<RubricNode>>('g.rubric-node')
      .data(descendants)
      .enter()
      .append('g')
      .attr('class', 'rubric-node')
      .attr('cursor', 'pointer')
      .attr('transform', (d) => `translate(${(d.x ?? 0) - NW / 2},${d.y ?? 0})`)
      .on('click', (event, d) => {
        setSelected(d.data);
        event.stopPropagation();
      });

    // Native SVG tooltip
    nodeSel.append('title').text((d) => {
      const a = aggMap.get(d.data);
      const reqs = d.data.requirements || '(unnamed)';
      const score =
        a?.score === null || a?.score === undefined
          ? '—'
          : `${(a.score * 100).toFixed(1)}%`;
      const rw = relWeightMap.get(d.data);
      const wParts: string[] = [];
      if (d.data.weight !== undefined) wParts.push(`weight: ${d.data.weight}`);
      if (rw !== undefined) wParts.push(`= ${(rw * 100).toFixed(1)}% of parent`);
      const w = wParts.length ? `${wParts.join(' ')}\n` : '';
      const cat = d.data.task_category ? `category: ${d.data.task_category}\n` : '';
      return `${reqs}\n${cat}${w}score: ${score}\n${a?.passed ?? 0}/${a?.total ?? 0} passed`;
    });

    // Background rect
    nodeSel
      .append('rect')
      .attr('width', NW)
      .attr('height', NH)
      .attr('rx', 8)
      .attr('ry', 8)
      .attr('fill', 'rgba(30,41,59,0.92)')
      .attr('stroke', (d) => {
        const a = aggMap.get(d.data);
        return colorFor(a?.score ?? null);
      })
      .attr('stroke-width', 2);

    // Score-fill bar at the bottom of each node
    nodeSel
      .append('rect')
      .attr('x', 0)
      .attr('y', NH - 4)
      .attr('width', (d) => {
        const a = aggMap.get(d.data);
        if (!a || a.score === null) return 0;
        return Math.max(0, Math.min(1, a.score)) * NW;
      })
      .attr('height', 4)
      .attr('rx', 0)
      .attr('fill', (d) => {
        const a = aggMap.get(d.data);
        return colorFor(a?.score ?? null);
      })
      .attr('opacity', 0.85);

    // Title (requirements, truncated)
    nodeSel
      .append('text')
      .attr('x', 10)
      .attr('y', 18)
      .attr('fill', '#e2e8f0')
      .attr('font-size', '11px')
      .attr('font-weight', '600')
      .text((d) => {
        const r = d.data.requirements || '(unnamed)';
        return r.length > 32 ? `${r.slice(0, 30)}…` : r;
      });

    // Score line
    nodeSel
      .append('text')
      .attr('x', 10)
      .attr('y', 38)
      .attr('font-size', '10px')
      .attr('font-weight', '700')
      .attr('fill', (d) => {
        const a = aggMap.get(d.data);
        return colorFor(a?.score ?? null);
      })
      .text((d) => {
        const a = aggMap.get(d.data);
        const isLeaf = !d.data.sub_tasks || d.data.sub_tasks.length === 0;
        if (!a || a.score === null) return isLeaf ? '— pending' : '—';
        const pct = `${(a.score * 100).toFixed(0)}%`;
        if (!isLeaf) return `${pct}  (${a.passed}/${a.total})`;
        return `${a.score >= 0.5 ? '✓' : '✗'} ${pct}`;
      });

    // Weight badge (top-right) — sibling-relative %
    nodeSel
      .filter((d) => relWeightMap.has(d.data))
      .append('text')
      .attr('x', NW - 10)
      .attr('y', 18)
      .attr('text-anchor', 'end')
      .attr('font-size', '10px')
      .attr('font-weight', '700')
      .attr('fill', '#cbd5e1')
      .text((d) => {
        const rw = relWeightMap.get(d.data);
        return rw !== undefined ? `${(rw * 100).toFixed(0)}%` : '';
      });

    // Category badge for leaves (bottom-right)
    nodeSel
      .filter(
        (d) =>
          (!d.data.sub_tasks || d.data.sub_tasks.length === 0) &&
          !!d.data.task_category,
      )
      .append('text')
      .attr('x', NW - 10)
      .attr('y', 38)
      .attr('text-anchor', 'end')
      .attr('font-size', '9px')
      .attr('fill', '#64748b')
      .text((d) => (d.data.task_category || '').slice(0, 16));

    // Fit viewport
    if (descendants.length) {
      const xs = descendants.map((n) => n.x ?? 0);
      const ys = descendants.map((n) => n.y ?? 0);
      const pad = 24;
      const minX = Math.min(...xs) - NW / 2;
      const maxX = Math.max(...xs) + NW / 2;
      const minY = Math.min(...ys);
      const maxY = Math.max(...ys) + NH;
      const treeW = maxX - minX;
      const treeH = maxY - minY;
      const scale = Math.min(
        (W - pad * 2) / treeW,
        (H - pad * 2) / treeH,
        1.0,
      );
      const tx = pad - minX * scale + ((W - pad * 2) - treeW * scale) / 2;
      const ty = pad - minY * scale;
      zoomBehavior.transform(svg, d3.zoomIdentity.translate(tx, ty).scale(scale));
    }

    return () => {
      d3.select(svgEl).selectAll('*').remove();
    };
  }, [node, aggMap, relWeightMap, renderTick]);

  // Re-render when the container resizes so the fit-viewport stays correct.
  useEffect(() => {
    const container = containerRef.current;
    if (!container || typeof ResizeObserver === 'undefined') return;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const observer = new ResizeObserver(() => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => setRenderTick((t) => t + 1), 120);
    });
    observer.observe(container);
    return () => {
      observer.disconnect();
      if (timer) clearTimeout(timer);
    };
  }, []);

  const selectedAgg = selected ? aggMap.get(selected) : null;
  const selectedIsLeaf =
    selected && (!selected.sub_tasks || selected.sub_tasks.length === 0);
  const selectedLeafGrade =
    selectedIsLeaf && selected?.id
      ? gradesById.get(String(selected.id))
      : undefined;
  const selectedExplanation = selectedLeafGrade
    ? String(selectedLeafGrade.explanation || '')
    : '';

  return (
    <div
      ref={containerRef}
      style={{ display: 'flex', flexDirection: 'column', height: 460 }}
    >
      <div style={{ flex: 1, position: 'relative', minHeight: 200 }}>
        <svg
          ref={svgRef}
          style={{ width: '100%', height: '100%', display: 'block' }}
        />
      </div>
      {selected && (
        <div
          style={{
            borderTop: '1px solid var(--border)',
            padding: '8px 12px',
            fontSize: '.72rem',
            maxHeight: 160,
            overflowY: 'auto',
            background: 'rgba(0,0,0,0.03)',
          }}
        >
          <div
            style={{
              fontWeight: 700,
              marginBottom: 4,
              color: 'var(--text)',
              wordBreak: 'break-word',
            }}
          >
            {selected.requirements || '(unnamed)'}
          </div>
          <div
            style={{
              color: 'var(--muted)',
              display: 'flex',
              gap: 12,
              marginBottom: 6,
              flexWrap: 'wrap',
            }}
          >
            {selected.weight !== undefined && (
              <span>
                weight: {selected.weight}
                {relWeightMap.has(selected) &&
                  ` (${(relWeightMap.get(selected)! * 100).toFixed(1)}% of parent)`}
              </span>
            )}
            {selectedAgg && selectedAgg.score !== null && (
              <span>score: {(selectedAgg.score * 100).toFixed(1)}%</span>
            )}
            <span>
              {selectedAgg?.passed ?? 0}/{selectedAgg?.total ?? 0} passed
            </span>
            {selected.task_category && (
              <span>category: {selected.task_category}</span>
            )}
            {selected.id && <span>id: {selected.id}</span>}
          </div>
          {selectedIsLeaf && (
            <div
              style={{
                whiteSpace: 'pre-wrap',
                color: 'var(--text)',
                wordBreak: 'break-word',
              }}
            >
              {selectedExplanation || noExplanationLabel}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
