'use client';

import { useState, useEffect } from 'react';
import { FiDownload, FiFolder, FiFile, FiCheck, FiPackage } from 'react-icons/fi';
import { getFolderTree, exportNotes } from '@/lib/api';
import type { FolderTree } from '@/lib/types';

export default function ExportView() {
    const [folders, setFolders] = useState<FolderTree[]>([]);
    const [selectedFolders, setSelectedFolders] = useState<Set<string>>(new Set());
    const [format, setFormat] = useState<'markdown' | 'json'>('markdown');
    const [exportAll, setExportAll] = useState(true);
    const [exporting, setExporting] = useState(false);
    const [done, setDone] = useState(false);

    useEffect(() => {
        const load = async () => {
            try {
                const tree = await getFolderTree();
                setFolders(tree);
            } catch (e) {
                console.error(e);
            }
        };
        load();
    }, []);

    const toggleFolder = (folderId: string) => {
        setSelectedFolders((prev) => {
            const next = new Set(prev);
            if (next.has(folderId)) {
                next.delete(folderId);
            } else {
                next.add(folderId);
            }
            return next;
        });
        setExportAll(false);
    };

    const handleExport = async () => {
        setExporting(true);
        setDone(false);
        try {
            await exportNotes({
                include_all: exportAll,
                folder_ids: exportAll ? undefined : Array.from(selectedFolders),
                format,
            });
            setDone(true);
            setTimeout(() => setDone(false), 3000);
        } catch (e) {
            console.error(e);
        } finally {
            setExporting(false);
        }
    };

    const renderFolderTree = (items: FolderTree[], level: number = 0) => (
        items.map((folder) => (
            <div key={folder.id}>
                <button
                    onClick={() => toggleFolder(folder.id)}
                    disabled={exportAll}
                    className={`w-full flex items-center gap-2 px-3 py-2 text-sm rounded-lg transition-colors ${exportAll ? 'opacity-50 cursor-not-allowed' :
                            selectedFolders.has(folder.id)
                                ? 'bg-brain-600/20 text-brain-400'
                                : 'text-dark-300 hover:bg-dark-700'
                        }`}
                    style={{ paddingLeft: `${level * 20 + 12}px` }}
                >
                    {selectedFolders.has(folder.id) ? (
                        <FiCheck className="w-4 h-4 text-brain-400" />
                    ) : (
                        <FiFolder className="w-4 h-4 text-dark-500" />
                    )}
                    <span className="truncate">{folder.name}</span>
                    <span className="ml-auto text-xs text-dark-600">{folder.notes.length} Notizen</span>
                </button>
                {folder.children.length > 0 && renderFolderTree(folder.children, level + 1)}
            </div>
        ))
    );

    return (
        <div className="h-full flex flex-col">
            {/* Header */}
            <div className="flex items-center justify-between px-4 sm:px-6 py-4 border-b border-dark-800 bg-dark-900/50">
                <div className="flex items-center gap-3">
                    <div className="p-2 bg-cyan-600/20 rounded-xl">
                        <FiPackage className="w-5 h-5 text-cyan-400" />
                    </div>
                    <div>
                        <h1 className="text-lg font-semibold text-white">Export</h1>
                        <p className="text-xs text-dark-500">Notizen als ZIP herunterladen</p>
                    </div>
                </div>
            </div>

            <div className="flex-1 overflow-y-auto p-4 sm:p-6">
                <div className="max-w-2xl mx-auto space-y-6">
                    {/* Scope */}
                    <div>
                        <h2 className="text-sm font-semibold text-white mb-3">Umfang</h2>
                        <label className="flex items-center gap-3 p-3 bg-dark-800 border border-dark-700 rounded-xl cursor-pointer hover:border-dark-600 transition-colors">
                            <input
                                type="checkbox"
                                checked={exportAll}
                                onChange={(e) => {
                                    setExportAll(e.target.checked);
                                    if (e.target.checked) setSelectedFolders(new Set());
                                }}
                                className="w-4 h-4 rounded border-dark-600 text-brain-600 focus:ring-brain-500 bg-dark-900"
                            />
                            <div>
                                <span className="text-sm text-white font-medium">Alles exportieren</span>
                                <p className="text-xs text-dark-500">Alle Ordner und Notizen</p>
                            </div>
                        </label>
                    </div>

                    {/* Folder selection */}
                    <div>
                        <h2 className="text-sm font-semibold text-white mb-3">
                            Ordner auswählen
                            {!exportAll && selectedFolders.size > 0 && (
                                <span className="ml-2 text-xs text-dark-500 font-normal">
                                    ({selectedFolders.size} ausgewählt)
                                </span>
                            )}
                        </h2>
                        <div className="bg-dark-800 border border-dark-700 rounded-xl overflow-hidden max-h-64 overflow-y-auto">
                            {folders.length === 0 ? (
                                <p className="text-sm text-dark-500 p-4 text-center">Keine Ordner vorhanden</p>
                            ) : (
                                <div className="p-1">
                                    {renderFolderTree(folders)}
                                </div>
                            )}
                        </div>
                    </div>

                    {/* Format */}
                    <div>
                        <h2 className="text-sm font-semibold text-white mb-3">Format</h2>
                        <div className="flex gap-3">
                            <button
                                onClick={() => setFormat('markdown')}
                                className={`flex-1 flex items-center gap-3 p-4 border rounded-xl transition-colors ${format === 'markdown'
                                        ? 'bg-brain-600/10 border-brain-500/40 text-brain-400'
                                        : 'bg-dark-800 border-dark-700 text-dark-300 hover:border-dark-600'
                                    }`}
                            >
                                <FiFile className="w-5 h-5" />
                                <div className="text-left">
                                    <p className="text-sm font-medium">Markdown</p>
                                    <p className="text-xs text-dark-500">.md Dateien</p>
                                </div>
                            </button>
                            <button
                                onClick={() => setFormat('json')}
                                className={`flex-1 flex items-center gap-3 p-4 border rounded-xl transition-colors ${format === 'json'
                                        ? 'bg-brain-600/10 border-brain-500/40 text-brain-400'
                                        : 'bg-dark-800 border-dark-700 text-dark-300 hover:border-dark-600'
                                    }`}
                            >
                                <FiFile className="w-5 h-5" />
                                <div className="text-left">
                                    <p className="text-sm font-medium">JSON</p>
                                    <p className="text-xs text-dark-500">.json Dateien</p>
                                </div>
                            </button>
                        </div>
                    </div>

                    {/* Export button */}
                    <button
                        onClick={handleExport}
                        disabled={exporting || (!exportAll && selectedFolders.size === 0)}
                        className="w-full flex items-center justify-center gap-2 px-6 py-4 text-base font-semibold bg-brain-600 hover:bg-brain-500 text-white rounded-xl transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                        {exporting ? (
                            <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                        ) : done ? (
                            <FiCheck className="w-5 h-5" />
                        ) : (
                            <FiDownload className="w-5 h-5" />
                        )}
                        {exporting ? 'Exportiert...' : done ? 'Download gestartet!' : 'Exportieren'}
                    </button>
                </div>
            </div>
        </div>
    );
}
