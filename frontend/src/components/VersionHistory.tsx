'use client';

import { useState, useEffect, useCallback } from 'react';
import { FiClock, FiRotateCw, FiX, FiEye, FiArrowLeft } from 'react-icons/fi';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { markdownComponents } from '@/lib/markdownComponents';
import { getNoteVersions, restoreNoteVersion } from '@/lib/api';
import type { NoteVersion, Note } from '@/lib/types';

interface Props {
    note: Note;
    onClose: () => void;
    onRestore: (note: Note) => void;
}

export default function VersionHistory({ note, onClose, onRestore }: Props) {
    const [versions, setVersions] = useState<NoteVersion[]>([]);
    const [loading, setLoading] = useState(true);
    const [selectedVersion, setSelectedVersion] = useState<NoteVersion | null>(null);
    const [restoring, setRestoring] = useState(false);

    const loadVersions = useCallback(async () => {
        setLoading(true);
        try {
            const v = await getNoteVersions(note.id);
            setVersions(v);
        } catch (e) {
            console.error(e);
        } finally {
            setLoading(false);
        }
    }, [note.id]);

    useEffect(() => {
        loadVersions();
    }, [loadVersions]);

    const handleRestore = async (version: NoteVersion) => {
        if (!confirm(`Version ${version.version_number} wiederherstellen? Der aktuelle Stand wird vorher als neue Version gespeichert.`)) return;
        setRestoring(true);
        try {
            const restored = await restoreNoteVersion(note.id, version.id);
            onRestore(restored);
        } catch (e) {
            console.error(e);
        } finally {
            setRestoring(false);
        }
    };

    const formatDate = (date: string) =>
        new Date(date).toLocaleDateString('de-DE', {
            day: '2-digit', month: '2-digit', year: 'numeric',
            hour: '2-digit', minute: '2-digit',
        });

    if (selectedVersion) {
        return (
            <div className="h-full flex flex-col bg-dark-950">
                <div className="flex items-center justify-between px-6 py-4 border-b border-dark-800 bg-dark-900/50">
                    <div className="flex items-center gap-3">
                        <button
                            onClick={() => setSelectedVersion(null)}
                            className="p-2 hover:bg-dark-800 rounded-lg transition-colors"
                        >
                            <FiArrowLeft className="w-4 h-4 text-dark-400" />
                        </button>
                        <div>
                            <h2 className="text-sm font-semibold text-white">
                                Version {selectedVersion.version_number}
                            </h2>
                            <p className="text-xs text-dark-500">{formatDate(selectedVersion.created_at)}</p>
                        </div>
                    </div>
                    <div className="flex gap-2">
                        <button
                            onClick={() => handleRestore(selectedVersion)}
                            disabled={restoring}
                            className="flex items-center gap-1.5 px-3 py-2 text-sm bg-brain-600 hover:bg-brain-500 text-white rounded-lg transition-colors disabled:opacity-50"
                        >
                            <FiRotateCw className={`w-4 h-4 ${restoring ? 'animate-spin' : ''}`} />
                            Wiederherstellen
                        </button>
                        <button onClick={onClose} className="p-2 hover:bg-dark-800 rounded-lg transition-colors">
                            <FiX className="w-4 h-4 text-dark-400" />
                        </button>
                    </div>
                </div>
                <div className="flex-1 overflow-y-auto">
                    <div className="max-w-4xl mx-auto px-8 py-8">
                        <h1 className="text-xl font-bold text-white mb-4">{selectedVersion.title}</h1>
                        <article className="markdown-content">
                            <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                                {selectedVersion.content}
                            </ReactMarkdown>
                        </article>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="h-full flex flex-col bg-dark-950">
            <div className="flex items-center justify-between px-6 py-4 border-b border-dark-800 bg-dark-900/50">
                <div className="flex items-center gap-3">
                    <div className="p-2 bg-orange-600/20 rounded-xl">
                        <FiClock className="w-5 h-5 text-orange-400" />
                    </div>
                    <div>
                        <h2 className="text-sm font-semibold text-white">Versionshistorie</h2>
                        <p className="text-xs text-dark-500">{note.title}</p>
                    </div>
                </div>
                <button onClick={onClose} className="p-2 hover:bg-dark-800 rounded-lg transition-colors">
                    <FiX className="w-4 h-4 text-dark-400" />
                </button>
            </div>

            <div className="flex-1 overflow-y-auto p-4">
                <div className="max-w-2xl mx-auto">
                    {loading ? (
                        <div className="flex items-center justify-center py-12">
                            <div className="animate-spin w-6 h-6 border-2 border-brain-500 border-t-transparent rounded-full" />
                        </div>
                    ) : versions.length === 0 ? (
                        <div className="text-center py-12">
                            <FiClock className="w-12 h-12 text-dark-700 mx-auto mb-4" />
                            <p className="text-dark-500">Keine früheren Versionen</p>
                            <p className="text-xs text-dark-600 mt-1">Versionen werden beim Bearbeiten automatisch erstellt</p>
                        </div>
                    ) : (
                        <div className="space-y-2">
                            {/* Current version */}
                            <div className="bg-dark-800 border border-brain-500/30 rounded-xl p-4">
                                <div className="flex items-center justify-between">
                                    <div>
                                        <div className="flex items-center gap-2">
                                            <span className="text-sm font-semibold text-white">Aktuelle Version</span>
                                            <span className="px-2 py-0.5 text-[10px] bg-brain-600/20 text-brain-400 rounded-full">Aktuell</span>
                                        </div>
                                        <p className="text-xs text-dark-500 mt-0.5">{formatDate(note.updated_at)}</p>
                                    </div>
                                </div>
                            </div>

                            {/* Historical versions */}
                            {versions.map((version) => (
                                <div key={version.id} className="bg-dark-800 border border-dark-700 rounded-xl p-4 hover:border-dark-600 transition-colors">
                                    <div className="flex items-center justify-between">
                                        <div>
                                            <span className="text-sm font-medium text-white">
                                                Version {version.version_number}
                                            </span>
                                            <p className="text-xs text-dark-500 mt-0.5">{formatDate(version.created_at)}</p>
                                            <p className="text-xs text-dark-400 mt-1 truncate max-w-md">{version.title}</p>
                                        </div>
                                        <div className="flex gap-1.5">
                                            <button
                                                onClick={() => setSelectedVersion(version)}
                                                className="flex items-center gap-1 px-2.5 py-1.5 text-xs bg-dark-700 hover:bg-dark-600 text-white rounded-lg transition-colors"
                                            >
                                                <FiEye className="w-3 h-3" />
                                                Ansehen
                                            </button>
                                            <button
                                                onClick={() => handleRestore(version)}
                                                disabled={restoring}
                                                className="flex items-center gap-1 px-2.5 py-1.5 text-xs bg-brain-600/20 text-brain-400 hover:bg-brain-600/30 rounded-lg transition-colors disabled:opacity-50"
                                            >
                                                <FiRotateCw className="w-3 h-3" />
                                                Restore
                                            </button>
                                        </div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
