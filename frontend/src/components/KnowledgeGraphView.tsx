'use client';

import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { FiRefreshCw, FiMaximize2, FiMinimize2, FiInfo } from 'react-icons/fi';
import { LuBrain } from 'react-icons/lu';
import { HiTag } from 'react-icons/hi2';
import { getGraphData, getNote } from '@/lib/api';
import { useStore } from '@/lib/store';
import type { GraphData } from '@/lib/types';

// Dynamic import for react-force-graph-2d (client only)
import dynamic from 'next/dynamic';
const ForceGraph2D = dynamic(() => import('react-force-graph-2d'), { ssr: false });

export default function KnowledgeGraphView() {
    const [graphData, setGraphData] = useState<GraphData | null>(null);
    const [loading, setLoading] = useState(true);
    const [fullscreen, setFullscreen] = useState(false);
    const [tagCluster, setTagCluster] = useState(false);
    const containerRef = useRef<HTMLDivElement>(null);
    const graphContainerRef = useRef<HTMLDivElement>(null);
    const fgRef = useRef<unknown>(null);
    const [graphDimensions, setGraphDimensions] = useState({ width: 0, height: 0 });
    const { setSelectedNote, setActiveView } = useStore();

    // Measure graph container so ForceGraph2D stays within bounds
    useEffect(() => {
        const el = graphContainerRef.current;
        if (!el) return;
        const ro = new ResizeObserver(([entry]) => {
            const { width, height } = entry.contentRect;
            setGraphDimensions({ width, height });
        });
        ro.observe(el);
        return () => ro.disconnect();
    }, []);

    const loadGraph = useCallback(async () => {
        setLoading(true);
        try {
            const data = await getGraphData();
            setGraphData(data);
        } catch (e) {
            console.error(e);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        loadGraph();
    }, [loadGraph]);

    const handleNodeClick = async (node: { id?: string | number }) => {
        if (!node.id) return;
        try {
            const note = await getNote(String(node.id));
            setSelectedNote(note);
            setActiveView('notes');
        } catch (e) {
            console.error(e);
        }
    };

    const fgData = useMemo(() => graphData ? {
        nodes: graphData.nodes.map((n) => ({
            id: n.id,
            name: n.title,
            folder: n.folder_path,
            val: n.val || 1,
            tags: n.tags || [],
        })),
        links: graphData.edges.map((e) => ({
            source: e.source,
            target: e.target,
            linkType: e.link_type,
            aiGenerated: e.ai_generated,
        })),
    } : { nodes: [], links: [] }, [graphData]);

    // Build tag color map
    const TAG_PALETTE = [
        '#8b5cf6', '#3b82f6', '#10b981', '#f59e0b', '#ef4444',
        '#ec4899', '#06b6d4', '#84cc16', '#f97316', '#6366f1',
        '#14b8a6', '#e879f9', '#22d3ee', '#a3e635', '#fb923c',
    ];

    const { tagColorMap, allTags } = useMemo(() => {
        if (!graphData) return { tagColorMap: new Map<string, string>(), allTags: [] as { id: string; name: string; color: string }[] };
        const tagMap = new Map<string, { name: string; color: string | null; count: number }>();
        for (const node of graphData.nodes) {
            for (const t of (node.tags || [])) {
                const existing = tagMap.get(t.id);
                if (existing) {
                    existing.count++;
                } else {
                    tagMap.set(t.id, { name: t.name, color: t.color, count: 1 });
                }
            }
        }
        // Sort by count descending
        const sorted = Array.from(tagMap.entries()).sort((a, b) => b[1].count - a[1].count);
        const colorMap = new Map<string, string>();
        const tags: { id: string; name: string; color: string }[] = [];
        sorted.forEach(([id, { name, color }], i) => {
            const c = color || TAG_PALETTE[i % TAG_PALETTE.length];
            colorMap.set(id, c);
            tags.push({ id, name, color: c });
        });
        return { tagColorMap: colorMap, allTags: tags };
    }, [graphData]);

    // Get color for a node based on its primary tag
    const getNodeColor = useCallback((node: { tags?: { id: string }[] }) => {
        if (!tagCluster || !node.tags || node.tags.length === 0) return '#8b5cf6';
        // Use the first tag's color
        for (const t of node.tags) {
            const c = tagColorMap.get(t.id);
            if (c) return c;
        }
        return '#6b7280'; // gray for untagged
    }, [tagCluster, tagColorMap]);

    const hoveredNodeRef = useRef<string | null>(null);

    const handleNodeHover = useCallback((node: { id?: string | number } | null) => {
        hoveredNodeRef.current = node?.id ? String(node.id) : null;
    }, []);

    const nodeCanvasObject = useCallback((node: { x?: number; y?: number; name?: string; id?: string | number; tags?: { id: string }[];[others: string]: unknown }, ctx: CanvasRenderingContext2D, globalScale: number) => {
        const label = (node as { name?: string }).name || '';
        const fontSize = 12 / globalScale;
        const isHovered = hoveredNodeRef.current === String(node.id);
        const size = isHovered ? 8 : 5;
        const baseColor = getNodeColor(node);

        // Parse hex to rgba helper
        const hexToRgba = (hex: string, alpha: number) => {
            const r = parseInt(hex.slice(1, 3), 16);
            const g = parseInt(hex.slice(3, 5), 16);
            const b = parseInt(hex.slice(5, 7), 16);
            return `rgba(${r},${g},${b},${alpha})`;
        };

        // Glow
        ctx.beginPath();
        ctx.arc(node.x || 0, node.y || 0, size + 4, 0, 2 * Math.PI);
        ctx.fillStyle = hexToRgba(baseColor, isHovered ? 0.3 : 0.1);
        ctx.fill();

        // Node
        ctx.beginPath();
        ctx.arc(node.x || 0, node.y || 0, size, 0, 2 * Math.PI);
        ctx.fillStyle = isHovered ? hexToRgba(baseColor, 0.85) : baseColor;
        ctx.fill();
        ctx.strokeStyle = hexToRgba(baseColor, 0.6);
        ctx.lineWidth = isHovered ? 2 / globalScale : 0.5 / globalScale;
        ctx.stroke();

        // Label
        if (globalScale > 0.7 || isHovered) {
            ctx.font = `${isHovered ? 'bold ' : ''}${fontSize}px Inter, sans-serif`;
            ctx.textAlign = 'center';
            ctx.textBaseline = 'top';
            ctx.fillStyle = isHovered ? '#ffffff' : '#9ca3af';
            ctx.fillText(label.length > 25 ? label.slice(0, 25) + '...' : label, node.x || 0, (node.y || 0) + size + 3);
        }
    }, [getNodeColor]);

    const nodePointerAreaPaint = useCallback((node: { x?: number; y?: number;[others: string]: unknown }, color: string, ctx: CanvasRenderingContext2D) => {
        ctx.beginPath();
        ctx.arc(node.x || 0, node.y || 0, 10, 0, 2 * Math.PI);
        ctx.fillStyle = color;
        ctx.fill();
    }, []);

    // Apply tag-based clustering force
    useEffect(() => {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const fg = fgRef.current as any;
        if (!fg) return;

        if (tagCluster && graphData && graphData.nodes.length > 0) {
            // Build tag → center position map
            const tagCenters = new Map<string, { x: number; y: number }>();
            const angle = (2 * Math.PI) / Math.max(allTags.length, 1);
            const radius = Math.min(graphDimensions.width, graphDimensions.height) * 0.25 || 200;
            allTags.forEach((t, i) => {
                tagCenters.set(t.id, {
                    x: Math.cos(angle * i) * radius,
                    y: Math.sin(angle * i) * radius,
                });
            });

            // Custom clustering force - pull nodes toward their primary tag center
            const clusterForce = (alpha: number) => {
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                const nodes: any[] = fg.graphData?.()?.nodes || [];
                for (const node of nodes) {
                    if (!node.tags || node.tags.length === 0) continue;
                    const center = tagCenters.get(node.tags[0].id);
                    if (!center) continue;
                    const k = alpha * 0.3;
                    node.vx += (center.x - (node.x || 0)) * k;
                    node.vy += (center.y - (node.y || 0)) * k;
                }
            };

            fg.d3Force('cluster', clusterForce);
            fg.d3Force('charge')?.strength(-120);
        } else if (fg) {
            fg.d3Force('cluster', null);
            fg.d3Force('charge')?.strength(-50);
        }
    }, [tagCluster, graphData, allTags, graphDimensions]);

    return (
        <div
            ref={containerRef}
            className={`h-full flex flex-col bg-dark-950 ${fullscreen ? 'fixed inset-0 z-50' : ''}`}
        >
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-dark-800 bg-dark-900/50">
                <div className="flex items-center gap-3">
                    <div className="p-2 bg-brain-600/20 rounded-xl">
                        <LuBrain className="w-5 h-5 text-brain-400" />
                    </div>
                    <div>
                        <h1 className="text-lg font-semibold text-white">Knowledge Graph</h1>
                        <p className="text-xs text-dark-500">
                            {graphData ? `${graphData.nodes.length} Notizen · ${graphData.edges.length} Verknüpfungen` : 'Lade...'}
                        </p>
                    </div>
                </div>
                <div className="flex items-center gap-2">
                    <button
                        onClick={() => setTagCluster(!tagCluster)}
                        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${tagCluster
                                ? 'bg-brain-600/30 text-brain-300 border border-brain-500/40'
                                : 'bg-dark-800 text-dark-400 hover:text-white border border-transparent'
                            }`}
                        title="Nach Tags clustern"
                    >
                        <HiTag className="w-3.5 h-3.5" />
                        Tag-Cluster
                    </button>
                    <button
                        onClick={loadGraph}
                        disabled={loading}
                        className="p-2 hover:bg-dark-800 rounded-lg transition-colors text-dark-400 hover:text-white"
                        title="Aktualisieren"
                    >
                        <FiRefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
                    </button>
                    <button
                        onClick={() => setFullscreen(!fullscreen)}
                        className="p-2 hover:bg-dark-800 rounded-lg transition-colors text-dark-400 hover:text-white"
                        title={fullscreen ? 'Verkleinern' : 'Vollbild'}
                    >
                        {fullscreen ? <FiMinimize2 className="w-4 h-4" /> : <FiMaximize2 className="w-4 h-4" />}
                    </button>
                </div>
            </div>

            {/* Graph */}
            <div ref={graphContainerRef} className="flex-1 relative overflow-hidden min-h-0">
                {loading && (
                    <div className="absolute inset-0 flex items-center justify-center z-10">
                        <div className="animate-spin w-8 h-8 border-2 border-brain-500 border-t-transparent rounded-full" />
                    </div>
                )}

                {!loading && graphData && graphData.nodes.length === 0 && (
                    <div className="h-full flex items-center justify-center">
                        <div className="text-center">
                            <LuBrain className="w-16 h-16 text-dark-700 mx-auto mb-4" />
                            <h3 className="text-xl font-semibold text-white mb-2">Noch keine Verknüpfungen</h3>
                            <p className="text-sm text-dark-500 max-w-sm">
                                Öffne eine Notiz und nutze &quot;Auto-Verknüpfen&quot;, um KI-basierte Verbindungen zu erstellen.
                            </p>
                        </div>
                    </div>
                )}

                {!loading && graphData && graphData.nodes.length > 0 && (
                    <ForceGraph2D
                        ref={fgRef as React.MutableRefObject<undefined>}
                        graphData={fgData}
                        width={graphDimensions.width || undefined}
                        height={graphDimensions.height || undefined}
                        nodeLabel="name"
                        nodeColor={() => '#8b5cf6'}
                        nodeRelSize={6}
                        linkColor={() => '#374151'}
                        linkWidth={1.5}
                        linkDirectionalParticles={1}
                        linkDirectionalParticleWidth={2}
                        linkDirectionalParticleColor={() => '#8b5cf660'}
                        backgroundColor="#030712"
                        onNodeClick={handleNodeClick}
                        onNodeHover={handleNodeHover}
                        nodeCanvasObject={nodeCanvasObject}
                        nodePointerAreaPaint={nodePointerAreaPaint}
                        warmupTicks={50}
                        cooldownTime={3000}
                    />
                )}

                {/* Tag Legend (when cluster mode active) */}
                {tagCluster && allTags.length > 0 && !loading && (
                    <div className="absolute top-3 right-3 bg-dark-900/95 border border-dark-700 rounded-xl p-3 text-[11px] text-dark-400 backdrop-blur-sm max-w-[220px] max-h-[calc(100%-24px)] overflow-y-auto">
                        <div className="flex items-center gap-2 mb-2">
                            <HiTag className="w-3.5 h-3.5 text-brain-400 flex-shrink-0" />
                            <span className="font-semibold text-dark-200">Tags</span>
                        </div>
                        <div className="space-y-1">
                            {allTags.map((t) => (
                                <div key={t.id} className="flex items-center gap-2">
                                    <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ backgroundColor: t.color }} />
                                    <span className="truncate">{t.name}</span>
                                </div>
                            ))}
                            <div className="flex items-center gap-2 mt-1 pt-1 border-t border-dark-700">
                                <span className="w-2.5 h-2.5 rounded-full flex-shrink-0 bg-gray-500" />
                                <span className="text-dark-500">Ohne Tags</span>
                            </div>
                        </div>
                    </div>
                )}

                {/* Legend */}
                {!loading && graphData && graphData.nodes.length > 0 && (
                    <div className="absolute bottom-3 left-3 bg-dark-900/95 border border-dark-700 rounded-xl p-3 text-[11px] text-dark-400 backdrop-blur-sm max-w-[280px] max-h-[calc(100%-24px)] overflow-y-auto">
                        <div className="flex items-center gap-2 mb-2">
                            <FiInfo className="w-3.5 h-3.5 text-brain-400 flex-shrink-0" />
                            <span className="font-semibold text-dark-200">Legende</span>
                        </div>
                        <div className="space-y-2">
                            <div>
                                <div className="flex items-center gap-2 mb-0.5">
                                    <span className="w-2.5 h-2.5 rounded-full bg-purple-500 flex-shrink-0" />
                                    <span>Punkt = Notiz</span>
                                </div>
                                <div className="flex items-center gap-2 mb-0.5">
                                    <span className="w-4 h-px bg-dark-500 flex-shrink-0" />
                                    <span>Linie = Verbindung zwischen Notizen</span>
                                </div>
                            </div>
                            <div className="border-t border-dark-700 pt-2">
                                <p className="font-medium text-dark-300 mb-1">Wie entstehen Verbindungen?</p>
                                <p className="leading-relaxed">Verbindungen werden <span className="text-brain-400">automatisch</span> erstellt, wenn du eine neue Notiz anlegst. Die KI durchsucht per Vektorsuche alle deine Notizen, findet thematisch verwandte, und erstellt die Verbindungen. Du kannst auch manuell über <span className="text-brain-400">&quot;Auto-Verknüpfen&quot;</span> in einer Notiz neue Verbindungen auslösen.</p>
                            </div>
                            <div className="border-t border-dark-700 pt-2">
                                <p className="font-medium text-dark-300 mb-1">Steuerung:</p>
                                <p>🖱️ Klick → Notiz öffnen</p>
                                <p>🔍 Scrollen → Zoomen</p>
                                <p>✋ Ziehen → Bewegen/Fixieren</p>
                            </div>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
