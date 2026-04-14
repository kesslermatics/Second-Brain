'use client';

import { useState, useCallback, useRef, useEffect } from 'react';
import { FiSave, FiX, FiArrowLeft } from 'react-icons/fi';
import type { Note } from '@/lib/types';

// Dynamic import for Excalidraw since it needs browser APIs
let ExcalidrawComponent: any = null;

interface Props {
    note: Note;
    onClose: () => void;
    onSave: (title: string, content: string) => Promise<void>;
}

export default function ExcalidrawEditor({ note, onClose, onSave }: Props) {
    const [title, setTitle] = useState(note.title);
    const [saving, setSaving] = useState(false);
    const [loaded, setLoaded] = useState(false);
    const [excalidrawAPI, setExcalidrawAPI] = useState<any>(null);
    const excalidrawRef = useRef<any>(null);

    // Parse initial data from JSON content
    const getInitialData = useCallback(() => {
        try {
            const data = JSON.parse(note.content);
            return {
                elements: data.elements || [],
                appState: data.appState || { theme: 'dark' },
                files: data.files || {},
            };
        } catch {
            return {
                elements: [],
                appState: { theme: 'dark' },
                files: {},
            };
        }
    }, [note.content]);

    // Load Excalidraw dynamically (only in browser)
    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                const mod = await import('@excalidraw/excalidraw');
                if (!cancelled) {
                    ExcalidrawComponent = mod.Excalidraw;
                    setLoaded(true);
                }
            } catch (e) {
                console.error('Failed to load Excalidraw:', e);
            }
        })();
        return () => { cancelled = true; };
    }, []);

    const handleSave = async () => {
        if (!excalidrawAPI) return;
        setSaving(true);
        try {
            const elements = excalidrawAPI.getSceneElements();
            const appState = excalidrawAPI.getAppState();
            const files = excalidrawAPI.getFiles();

            const data = {
                elements: elements.map((el: any) => ({
                    ...el,
                    // Strip volatile properties
                    selected: undefined,
                    dragging: undefined,
                })),
                appState: {
                    theme: appState.theme || 'dark',
                    viewBackgroundColor: appState.viewBackgroundColor,
                    gridSize: appState.gridSize,
                },
                files: files || {},
            };

            await onSave(title, JSON.stringify(data));
        } finally {
            setSaving(false);
        }
    };

    const initialData = getInitialData();

    return (
        <div className="h-full flex flex-col bg-dark-950">
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-3 border-b border-dark-800 bg-dark-900/50 z-10">
                <div className="flex items-center gap-3 flex-1">
                    <button
                        onClick={onClose}
                        className="p-2 hover:bg-dark-800 rounded-lg transition-colors"
                    >
                        <FiArrowLeft className="w-4 h-4 text-dark-400" />
                    </button>
                    <input
                        type="text"
                        value={title}
                        onChange={(e) => setTitle(e.target.value)}
                        className="text-lg font-semibold bg-transparent text-white border-b border-dark-700 focus:border-brain-500 focus:outline-none px-1 py-0.5 flex-1 max-w-xl"
                        placeholder="Zeichnung Titel..."
                    />
                    <span className="text-xs text-purple-400 bg-purple-500/10 px-2 py-0.5 rounded">
                        Excalidraw
                    </span>
                </div>
                <div className="flex items-center gap-2">
                    <button
                        onClick={handleSave}
                        disabled={saving}
                        className="flex items-center gap-1.5 px-3 py-2 text-sm bg-brain-600 hover:bg-brain-500 text-white rounded-lg transition-colors disabled:opacity-50"
                    >
                        <FiSave className="w-4 h-4" />
                        {saving ? 'Speichert...' : 'Speichern'}
                    </button>
                    <button
                        onClick={onClose}
                        className="p-2 hover:bg-dark-800 rounded-lg transition-colors"
                    >
                        <FiX className="w-4 h-4 text-dark-400" />
                    </button>
                </div>
            </div>

            {/* Excalidraw Canvas */}
            <div className="flex-1 relative">
                {loaded && ExcalidrawComponent ? (
                    <ExcalidrawComponent
                        ref={excalidrawRef}
                        excalidrawAPI={(api: any) => setExcalidrawAPI(api)}
                        initialData={initialData}
                        theme="dark"
                        langCode="de-DE"
                        UIOptions={{
                            canvasActions: {
                                loadScene: false,
                                saveToActiveFile: false,
                                export: false,
                            },
                        }}
                    />
                ) : (
                    <div className="flex items-center justify-center h-full">
                        <div className="text-center">
                            <div className="w-8 h-8 border-2 border-brain-400 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
                            <p className="text-sm text-dark-500">Excalidraw wird geladen...</p>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
