'use client';

import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { FiRefreshCw, FiMaximize2, FiMinimize2, FiInfo } from 'react-icons/fi';
import { LuBrain } from 'react-icons/lu';
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
    const containerRef = useRef<HTMLDivElement>(null);
    const { setSelectedNote, setActiveView } = useStore();

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
        })),
        links: graphData.edges.map((e) => ({
            source: e.source,
            target: e.target,
            linkType: e.link_type,
            aiGenerated: e.ai_generated,
        })),
    } : { nodes: [], links: [] }, [graphData]);

    const hoveredNodeRef = useRef<string | null>(null);

    const handleNodeHover = useCallback((node: { id?: string | number } | null) => {
        hoveredNodeRef.current = node?.id ? String(node.id) : null;
    }, []);

    const nodeCanvasObject = useCallback((node: { x?: number; y?: number; name?: string; id?: string | number;[others: string]: unknown }, ctx: CanvasRenderingContext2D, globalScale: number) => {
        const label = (node as { name?: string }).name || '';
        const fontSize = 12 / globalScale;
        const isHovered = hoveredNodeRef.current === String(node.id);
        const size = isHovered ? 8 : 5;

        // Glow
        ctx.beginPath();
        ctx.arc(node.x || 0, node.y || 0, size + 4, 0, 2 * Math.PI);
        ctx.fillStyle = isHovered ? 'rgba(139, 92, 246, 0.3)' : 'rgba(139, 92, 246, 0.1)';
        ctx.fill();

        // Node
        ctx.beginPath();
        ctx.arc(node.x || 0, node.y || 0, size, 0, 2 * Math.PI);
        ctx.fillStyle = isHovered ? '#a78bfa' : '#8b5cf6';
        ctx.fill();
        ctx.strokeStyle = '#c4b5fd';
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
    }, []);

    const nodePointerAreaPaint = useCallback((node: { x?: number; y?: number;[others: string]: unknown }, color: string, ctx: CanvasRenderingContext2D) => {
        ctx.beginPath();
        ctx.arc(node.x || 0, node.y || 0, 10, 0, 2 * Math.PI);
        ctx.fillStyle = color;
        ctx.fill();
    }, []);

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
            <div className="flex-1 relative">
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
                        graphData={fgData}
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

                {/* Legend */}
                {!loading && graphData && graphData.nodes.length > 0 && (
                    <div className="absolute bottom-4 left-4 bg-dark-900/90 border border-dark-700 rounded-xl p-4 text-xs text-dark-400 backdrop-blur-sm max-w-xs">
                        <div className="flex items-center gap-2 mb-2">
                            <FiInfo className="w-3.5 h-3.5 text-brain-400" />
                            <span className="font-semibold text-dark-200">Legende & Steuerung</span>
                        </div>
                        <div className="space-y-2">
                            <div>
                                <p className="font-medium text-dark-300 mb-1">Was du siehst:</p>
                                <div className="flex items-center gap-2 mb-0.5">
                                    <span className="w-2.5 h-2.5 rounded-full bg-purple-500 flex-shrink-0" />
                                    <span>Jeder Punkt = eine Notiz</span>
                                </div>
                                <div className="flex items-center gap-2 mb-0.5">
                                    <span className="w-4 h-px bg-dark-500 flex-shrink-0" />
                                    <span>Linien = KI-erkannte Verbindungen zwischen Notizen</span>
                                </div>
                                <p className="text-dark-500 mt-1">Nah beieinander liegende Notizen teilen ähnliche Themen. Cluster zeigen zusammengehörige Wissensbereiche.</p>
                            </div>
                            <div className="border-t border-dark-700 pt-2">
                                <p className="font-medium text-dark-300 mb-1">Steuerung:</p>
                                <p>🖱️ Klick auf Notiz → öffnet sie</p>
                                <p>🔍 Scrollen → Zoomen</p>
                                <p>✋ Ziehen auf Hintergrund → Bewegen</p>
                                <p>📌 Ziehen auf Notiz → Fixieren</p>
                            </div>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
