import { useEffect, useRef } from 'react';
import * as d3 from 'd3';
import type { TreeNode } from '../../types';

// ── Colour constants (exact match with original dashboard.js) ──

const LABEL_COLORS: Record<string, string> = {
  draft: '#3b82f6',
  improve: '#8b5cf6',
  ablation: '#f59e0b',
  debug: '#ef4444',
  validation: '#10b981',
};

const NW = 160;
const NH = 62;

// ── Edge path helper (cubic bezier, same as _edgePath in dashboard.js) ──

interface Pos {
  x: number;
  y: number;
}

function edgePath(p: Pos | undefined, c: Pos | undefined): string {
  if (!p || !c) return '';
  const px = p.x;
  const py = p.y + NH;
  const cx = c.x;
  const cy = c.y;
  const midY = (py + cy) / 2;
  return `M${px},${py} C${px},${midY} ${cx},${midY} ${cx},${cy}`;
}

// ── Props ──

interface TreeVisualizationProps {
  nodes: TreeNode[];
  selectedNodeId: string | null;
  onSelectNode: (id: string) => void;
  /** When true, suppress the outer border/background (for embedding inside a card). */
  borderless?: boolean;
}

// ── Component ──

export function TreeVisualization({
  nodes,
  selectedNodeId,
  onSelectNode,
  borderless = false,
}: TreeVisualizationProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const nodeDraggedRef = useRef(false);

  useEffect(() => {
    const svgEl = svgRef.current;
    if (!svgEl) return;

    // 1. Clear previous SVG content
    d3.select(svgEl).selectAll('*').remove();

    if (!nodes || nodes.length === 0) return;

    // Measure container
    const rect = svgEl.getBoundingClientRect();
    let W = rect.width > 100 ? rect.width : svgEl.clientWidth || 900;
    let H = rect.height > 100 ? rect.height : svgEl.clientHeight || 500;
    if (W < 100) W = 900;
    if (H < 100) H = 500;

    // Build id map and find root
    const idMap: Record<string, TreeNode> = {};
    nodes.forEach((n) => {
      idMap[n.id] = n;
    });
    let root = nodes.find((n) => !n.parent_id || !idMap[n.parent_id]);
    if (!root) root = nodes[0];

    // 3. Build hierarchy with d3.stratify
    let treeData: d3.HierarchyNode<TreeNode> | null = null;
    try {
      const strat = d3
        .stratify<TreeNode>()
        .id((d) => d.id)
        .parentId((d) => (idMap[d.parent_id ?? ''] ? d.parent_id : null));
      treeData = strat(nodes);
    } catch {
      treeData = null;
    }

    const svg = d3.select(svgEl);

    // 2. Create a zoomable g container
    const g = svg.append('g').attr('class', 'tree-g');
    const zoomBehavior = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.2, 3])
      .on('zoom', (event) => {
        g.attr('transform', event.transform);
      });
    svg.call(zoomBehavior);

    // 4. Compute positions with d3.tree().nodeSize([190, 122])
    const posMap: Record<string, Pos> = {};
    if (treeData) {
      const treeLayout = d3.tree<TreeNode>().nodeSize([NW + 30, NH + 60]);
      treeLayout(treeData);
      treeData.descendants().forEach((d) => {
        posMap[d.id!] = { x: d.x! + W / 2, y: d.y! + 40 };
      });
    } else {
      // Grid fallback
      nodes.forEach((n) => {
        const depth = n.depth || 0;
        const col = nodes.filter((x) => (x.depth || 0) === depth);
        const idx = col.indexOf(n);
        posMap[n.id] = { x: 40 + depth * (NW + 60), y: 40 + idx * (NH + 50) };
      });
    }

    // 5. Draw edges as cubic bezier paths
    const links = nodes.filter((n) => n.parent_id && posMap[n.parent_id]);
    g.selectAll('.tree-edge')
      .data(links)
      .enter()
      .append('path')
      .attr('class', 'tree-edge')
      .attr('id', (d) => `edge-d3-${d.id}`)
      .attr('fill', 'none')
      .attr('stroke', (d) => LABEL_COLORS[d.label] || 'rgba(59,130,246,.5)')
      .attr('stroke-width', 1.8)
      .attr('opacity', 0.7)
      .attr('d', (d) => edgePath(posMap[d.parent_id!], posMap[d.id]));

    // 6. Draw nodes as groups with rect, text elements
    const nodeSel = g
      .selectAll<SVGGElement, TreeNode>('.tree-node-g')
      .data(nodes)
      .enter()
      .append('g')
      .attr('class', 'tree-node-g')
      .attr('cursor', 'pointer')
      .attr('transform', (d) => {
        const p = posMap[d.id];
        return `translate(${p.x - NW / 2},${p.y})`;
      });

    // 7. Enable d3.drag on nodes
    nodeSel.call(
      d3
        .drag<SVGGElement, TreeNode>()
        .on('start', function () {
          d3.select(this).raise();
        })
        .on('drag', function (event, d) {
          posMap[d.id].x += event.dx;
          posMap[d.id].y += event.dy;
          d3.select(this).attr(
            'transform',
            `translate(${posMap[d.id].x - NW / 2},${posMap[d.id].y})`,
          );
          // Update connected edges immediately
          g.selectAll<SVGPathElement, TreeNode>('.tree-edge')
            .filter((e) => e.id === d.id || e.parent_id === d.id)
            .attr('d', (e) =>
              edgePath(posMap[e.parent_id!] || posMap[e.id], posMap[e.id]),
            );
          nodeDraggedRef.current = true;
        })
        .on('end', () => {
          setTimeout(() => {
            nodeDraggedRef.current = false;
          }, 100);
        }),
    );

    // Click to select node
    nodeSel.on('click', (event, d) => {
      if (!nodeDraggedRef.current) {
        onSelectNode(d.id);
      }
      event.stopPropagation();
    });

    // Node rect
    nodeSel
      .append('rect')
      .attr('width', NW)
      .attr('height', NH)
      .attr('rx', 8)
      .attr('ry', 8)
      .attr('fill', 'rgba(30,41,59,0.9)')
      .attr('stroke', (d) => LABEL_COLORS[d.label || ''] || 'rgba(71,85,105,0.8)')
      .attr('stroke-width', 1.5);

    // Label text (top-left)
    nodeSel
      .append('text')
      .attr('x', 8)
      .attr('y', 18)
      .attr('fill', (d) => LABEL_COLORS[d.label || ''] || '#94a3b8')
      .attr('font-size', '11px')
      .attr('font-weight', '700')
      .text((d) => (d.label || d.node_type || 'node').slice(0, 12));

    // Label badge (top-right)
    nodeSel
      .append('rect')
      .attr('x', NW - 60)
      .attr('y', 6)
      .attr('width', 54)
      .attr('height', 16)
      .attr('rx', 8)
      .attr('ry', 8)
      .attr('fill', (d) => {
        const c = LABEL_COLORS[d.label || ''];
        return c ? c + '33' : 'rgba(100,116,139,.2)';
      });
    nodeSel
      .append('text')
      .attr('x', NW - 33)
      .attr('y', 18)
      .attr('fill', (d) => LABEL_COLORS[d.label || ''] || '#94a3b8')
      .attr('font-size', '9px')
      .attr('text-anchor', 'middle')
      .text((d) => (d.label || '').slice(0, 8));

    // Node ID (short, monospace)
    nodeSel
      .append('text')
      .attr('x', 8)
      .attr('y', 34)
      .attr('fill', '#64748b')
      .attr('font-size', '10px')
      .attr('font-family', 'monospace')
      .text((d) => d.id.slice(-8));

    // Status badge rect
    nodeSel
      .append('rect')
      .attr('x', 8)
      .attr('y', 40)
      .attr('width', 50)
      .attr('height', 15)
      .attr('rx', 6)
      .attr('fill', (d) =>
        d.status === 'success'
          ? 'rgba(16,185,129,.2)'
          : d.status === 'failed'
            ? 'rgba(239,68,68,.2)'
            : 'rgba(59,130,246,.2)',
      );
    nodeSel
      .append('text')
      .attr('x', 33)
      .attr('y', 51)
      .attr('text-anchor', 'middle')
      .attr('fill', (d) =>
        d.status === 'success'
          ? '#10b981'
          : d.status === 'failed'
            ? '#ef4444'
            : '#3b82f6',
      )
      .attr('font-size', '9px')
      .text((d) => (d.status || '').slice(0, 8));

    // Score (bottom-right, only when present)
    nodeSel
      .filter((d) => {
        const s =
          d.scientific_score ??
          (d.metrics as Record<string, unknown> | null)?._scientific_score;
        return s != null;
      })
      .append('text')
      .attr('x', NW - 8)
      .attr('y', 54)
      .attr('text-anchor', 'end')
      .attr('fill', '#60a5fa')
      .attr('font-size', '10px')
      .attr('font-weight', '700')
      .text((d) => {
        const s =
          d.scientific_score ??
          ((d.metrics as Record<string, unknown> | null)?._scientific_score as number) ??
          0;
        return (s as number).toFixed(2);
      });

    // 8. Fit viewport with initial transform
    const allX = Object.values(posMap).map((p) => p.x);
    const allY = Object.values(posMap).map((p) => p.y);
    if (allX.length) {
      const pad = 24;
      const minX = Math.min(...allX) - NW / 2;
      const maxX = Math.max(...allX) + NW / 2;
      const minY = Math.min(...allY);
      const maxY = Math.max(...allY) + NH;
      const treeW = maxX - minX;
      const treeH = maxY - minY;
      const scaleX = (W - pad * 2) / treeW;
      const scaleY = (H - pad * 2) / treeH;
      const scale = Math.min(scaleX, scaleY, 1.0);
      const tx = pad - minX * scale + ((W - pad * 2) - treeW * scale) / 2;
      const ty = pad - minY * scale;
      zoomBehavior.transform(svg, d3.zoomIdentity.translate(tx, ty).scale(scale));
    }

    // 9. Clean up on unmount
    return () => {
      d3.select(svgEl).selectAll('*').remove();
    };
  }, [nodes, selectedNodeId, onSelectNode]);

  // ResizeObserver to re-render on container resize
  useEffect(() => {
    const container = containerRef.current;
    if (!container || typeof ResizeObserver === 'undefined') return;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const observer = new ResizeObserver(() => {
      if (timer) clearTimeout(timer);
      // Re-render is triggered by the dependency on nodes (force update via key or similar)
      // For simplicity, we trigger a re-render by dispatching a custom event
      timer = setTimeout(() => {
        // Force re-render by updating the svg viewBox or similar
        const svgEl = svgRef.current;
        if (svgEl) {
          // Trigger the effect by touching the SVG attribute
          svgEl.dispatchEvent(new Event('resize'));
        }
      }, 100);
    });
    observer.observe(container);
    return () => {
      observer.disconnect();
      if (timer) clearTimeout(timer);
    };
  }, []);

  return (
    <div
      ref={containerRef}
      style={{
        flex: 1,
        ...(borderless
          ? {}
          : {
              border: '1px solid var(--border)',
              borderRadius: 8,
              background: 'var(--card-bg, rgba(30,41,59,.5))',
            }),
        overflow: 'hidden',
        position: 'relative',
      }}
    >
      <svg
        ref={svgRef}
        id="tree-d3-svg"
        style={{ width: '100%', height: '100%', display: 'block' }}
      />
    </div>
  );
}
