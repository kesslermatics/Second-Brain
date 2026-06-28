'use client';

import { useState, useEffect } from 'react';
import { FiX, FiDownload, FiUpload, FiTrash2, FiPlus, FiClock, FiHardDrive } from 'react-icons/fi';
import { listBackups, createBackup, restoreBackup, deleteBackup } from '@/lib/api';
import type { BackupItem } from '@/lib/api';

interface Props {
    open: boolean;
    onClose: () => void;
}

export default function BackupModal({ open, onClose }: Props) {
    const [backups, setBackups] = useState<BackupItem[]>([]);
    const [loading, setLoading] = useState(false);
    const [creating, setCreating] = useState(false);
    const [restoring, setRestoring] = useState<string | null>(null);
    const [label, setLabel] = useState('');
    const [showLabelInput, setShowLabelInput] = useState(false);

    useEffect(() => {
        if (open) loadBackups();
    }, [open]);

    const loadBackups = async () => {
        setLoading(true);
        try {
            const list = await listBackups();
            setBackups(list);
        } catch (e) {
            console.error(e);
        } finally {
            setLoading(false);
        }
    };

    const handleCreate = async () => {
        setCreating(true);
        try {
            await createBackup(label || undefined);
            setLabel('');
            setShowLabelInput(false);
            await loadBackups();
        } catch (e) {
            console.error(e);
        } finally {
            setCreating(false);
        }
    };

    const handleRestore = async (id: string) => {
        if (!confirm('Backup wiederherstellen? Alle aktuellen Daten werden durch das Backup ersetzt. Ein Sicherheitsbackup wird empfohlen.')) return;
        setRestoring(id);
        try {
            await restoreBackup(id);
            alert('Backup erfolgreich wiederhergestellt. Seite wird neu geladen.');
            window.location.reload();
        } catch (e) {
            console.error(e);
            alert('Fehler beim Wiederherstellen.');
        } finally {
            setRestoring(null);
        }
    };

    const handleDelete = async (id: string) => {
        if (!confirm('Backup endgültig löschen?')) return;
        try {
            await deleteBackup(id);
            await loadBackups();
        } catch (e) {
            console.error(e);
        }
    };

    const formatSize = (bytes: number) => {
        if (bytes < 1024) return `${bytes} B`;
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
        return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    };

    const formatDate = (iso: string) => {
        const d = new Date(iso);
        return d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
    };

    if (!open) return null;

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
            <div className="bg-dark-900 border border-dark-700 rounded-2xl w-full max-w-lg max-h-[80vh] flex flex-col shadow-2xl" onClick={(e) => e.stopPropagation()}>
                {/* Header */}
                <div className="flex items-center justify-between px-5 py-4 border-b border-dark-800">
                    <div className="flex items-center gap-3">
                        <div className="p-2 bg-blue-600/20 rounded-xl">
                            <FiHardDrive className="w-5 h-5 text-blue-400" />
                        </div>
                        <div>
                            <h2 className="text-lg font-semibold text-white">Backups</h2>
                            <p className="text-xs text-dark-500">Automatisch täglich um 03:00 UTC</p>
                        </div>
                    </div>
                    <button onClick={onClose} className="p-2 hover:bg-dark-800 rounded-lg text-dark-400 hover:text-white">
                        <FiX className="w-5 h-5" />
                    </button>
                </div>

                {/* Create backup */}
                <div className="px-5 py-3 border-b border-dark-800">
                    {showLabelInput ? (
                        <div className="flex gap-2">
                            <input
                                type="text"
                                value={label}
                                onChange={(e) => setLabel(e.target.value)}
                                onKeyDown={(e) => { if (e.key === 'Enter') handleCreate(); if (e.key === 'Escape') setShowLabelInput(false); }}
                                placeholder="Backup-Beschreibung (optional)"
                                className="flex-1 px-3 py-2 bg-dark-800 border border-dark-700 rounded-lg text-white text-sm placeholder-dark-600 focus:outline-none focus:border-blue-500"
                                autoFocus
                            />
                            <button onClick={handleCreate} disabled={creating}
                                className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium rounded-lg disabled:opacity-50">
                                {creating ? '...' : 'Erstellen'}
                            </button>
                            <button onClick={() => setShowLabelInput(false)} className="px-3 py-2 bg-dark-800 text-dark-400 rounded-lg hover:text-white">
                                <FiX className="w-4 h-4" />
                            </button>
                        </div>
                    ) : (
                        <button onClick={() => setShowLabelInput(true)}
                            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium rounded-lg w-full justify-center">
                            <FiPlus className="w-4 h-4" /> Backup jetzt erstellen
                        </button>
                    )}
                </div>

                {/* Backup list */}
                <div className="flex-1 overflow-y-auto px-5 py-3 space-y-2">
                    {loading && <p className="text-sm text-dark-500 text-center py-4">Lade Backups...</p>}
                    {!loading && backups.length === 0 && (
                        <p className="text-sm text-dark-500 text-center py-8">Noch keine Backups vorhanden.</p>
                    )}
                    {backups.map((backup) => (
                        <div key={backup.id} className="border border-dark-700 rounded-xl p-3 hover:border-dark-600 transition-colors">
                            <div className="flex items-start justify-between gap-3">
                                <div className="flex-1 min-w-0">
                                    <p className="text-sm font-medium text-white truncate">{backup.label}</p>
                                    <div className="flex items-center gap-3 mt-1 text-xs text-dark-500">
                                        <span className="flex items-center gap-1"><FiClock className="w-3 h-3" />{formatDate(backup.created_at)}</span>
                                        <span>{backup.notes_count} Notizen</span>
                                        <span>{backup.folders_count} Ordner</span>
                                        <span>{formatSize(backup.size_bytes)}</span>
                                    </div>
                                </div>
                                <div className="flex items-center gap-1 flex-shrink-0">
                                    <button
                                        onClick={() => handleRestore(backup.id)}
                                        disabled={restoring === backup.id}
                                        className="flex items-center gap-1 px-2.5 py-1.5 bg-green-600/20 text-green-400 hover:bg-green-600/30 text-xs font-medium rounded-lg disabled:opacity-50"
                                        title="Backup wiederherstellen"
                                    >
                                        <FiUpload className="w-3 h-3" />
                                        {restoring === backup.id ? '...' : 'Restore'}
                                    </button>
                                    <button
                                        onClick={() => handleDelete(backup.id)}
                                        className="p-1.5 text-dark-500 hover:text-red-400 hover:bg-dark-800 rounded-lg"
                                        title="Backup löschen"
                                    >
                                        <FiTrash2 className="w-3.5 h-3.5" />
                                    </button>
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
}
