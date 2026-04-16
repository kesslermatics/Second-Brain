'use client';

import { useState, useEffect } from 'react';
import {
    FiFileText, FiFolder, FiTag, FiGlobe, FiZap, FiRefreshCw,
} from 'react-icons/fi';
import ReactMarkdown from 'react-markdown';
import { markdownComponents, remarkPlugins, rehypePlugins } from '@/lib/markdownComponents';
import { generateSummary, getFolderTree, getTags } from '@/lib/api';
import type { FolderTree, Tag, SummaryResponse } from '@/lib/types';

type Scope = 'folder' | 'tag' | 'all';

export default function SummaryView() {
    const [scope, setScope] = useState<Scope>('all');
    const [folders, setFolders] = useState<FolderTree[]>([]);
    const [tags, setTags] = useState<Tag[]>([]);
    const [selectedFolderId, setSelectedFolderId] = useState('');
    const [selectedTagName, setSelectedTagName] = useState('');
    const [result, setResult] = useState<SummaryResponse | null>(null);
    const [loading, setLoading] = useState(false);

    useEffect(() => {
        const load = async () => {
            try {
                const [tree, tagList] = await Promise.all([getFolderTree(), getTags()]);
                setFolders(tree);
                setTags(tagList);
            } catch (e) {
                console.error(e);
            }
        };
        load();
    }, []);

    const flattenFolders = (items: FolderTree[], level: number = 0): { id: string; name: string; level: number }[] => {
        const result: { id: string; name: string; level: number }[] = [];
        for (const f of items) {
            result.push({ id: f.id, name: f.path || f.name, level });
            result.push(...flattenFolders(f.children, level + 1));
        }
        return result;
    };

    const handleGenerate = async () => {
        setLoading(true);
        setResult(null);
        try {
            const resp = await generateSummary({
                scope,
                folder_id: scope === 'folder' ? selectedFolderId : undefined,
                tag_name: scope === 'tag' ? selectedTagName : undefined,
            });
            setResult(resp);
        } catch (e) {
            console.error(e);
        } finally {
            setLoading(false);
        }
    };

    const canGenerate = () => {
        if (scope === 'all') return true;
        if (scope === 'folder') return !!selectedFolderId;
        if (scope === 'tag') return !!selectedTagName;
        return false;
    };

    const flatFolders = flattenFolders(folders);

    return (
        <div className="h-full flex flex-col">
            {/* Header */}
            <div className="flex items-center justify-between px-4 sm:px-6 py-4 border-b border-dark-800 bg-dark-900/50">
                <div className="flex items-center gap-3">
                    <div className="p-2 bg-purple-600/20 rounded-xl">
                        <FiFileText className="w-5 h-5 text-purple-400" />
                    </div>
                    <div>
                        <h1 className="text-lg font-semibold text-white">KI-Zusammenfassung</h1>
                        <p className="text-xs text-dark-500">Lass deine Notizen automatisch zusammenfassen</p>
                    </div>
                </div>
            </div>

            <div className="flex-1 overflow-y-auto p-4 sm:p-6">
                <div className="max-w-3xl mx-auto space-y-6">
                    {/* Scope selection */}
                    <div>
                        <h2 className="text-sm font-semibold text-white mb-3">Umfang wählen</h2>
                        <div className="grid grid-cols-3 gap-3">
                            <button
                                onClick={() => setScope('all')}
                                className={`flex flex-col items-center gap-2 p-4 border rounded-xl transition-colors ${scope === 'all'
                                        ? 'bg-brain-600/10 border-brain-500/40 text-brain-400'
                                        : 'bg-dark-800 border-dark-700 text-dark-300 hover:border-dark-600'
                                    }`}
                            >
                                <FiGlobe className="w-5 h-5" />
                                <span className="text-sm font-medium">Alles</span>
                            </button>
                            <button
                                onClick={() => setScope('folder')}
                                className={`flex flex-col items-center gap-2 p-4 border rounded-xl transition-colors ${scope === 'folder'
                                        ? 'bg-brain-600/10 border-brain-500/40 text-brain-400'
                                        : 'bg-dark-800 border-dark-700 text-dark-300 hover:border-dark-600'
                                    }`}
                            >
                                <FiFolder className="w-5 h-5" />
                                <span className="text-sm font-medium">Ordner</span>
                            </button>
                            <button
                                onClick={() => setScope('tag')}
                                className={`flex flex-col items-center gap-2 p-4 border rounded-xl transition-colors ${scope === 'tag'
                                        ? 'bg-brain-600/10 border-brain-500/40 text-brain-400'
                                        : 'bg-dark-800 border-dark-700 text-dark-300 hover:border-dark-600'
                                    }`}
                            >
                                <FiTag className="w-5 h-5" />
                                <span className="text-sm font-medium">Tag</span>
                            </button>
                        </div>
                    </div>

                    {/* Scope-specific selection */}
                    {scope === 'folder' && (
                        <div>
                            <label className="block text-sm font-medium text-white mb-2">Ordner auswählen</label>
                            <select
                                value={selectedFolderId}
                                onChange={(e) => setSelectedFolderId(e.target.value)}
                                className="w-full px-4 py-3 bg-dark-800 border border-dark-700 rounded-xl text-white focus:outline-none focus:border-brain-500"
                            >
                                <option value="">Ordner wählen...</option>
                                {flatFolders.map((f) => (
                                    <option key={f.id} value={f.id}>
                                        {'  '.repeat(f.level)}{f.name}
                                    </option>
                                ))}
                            </select>
                        </div>
                    )}

                    {scope === 'tag' && (
                        <div>
                            <label className="block text-sm font-medium text-white mb-2">Tag auswählen</label>
                            <select
                                value={selectedTagName}
                                onChange={(e) => setSelectedTagName(e.target.value)}
                                className="w-full px-4 py-3 bg-dark-800 border border-dark-700 rounded-xl text-white focus:outline-none focus:border-brain-500"
                            >
                                <option value="">Tag wählen...</option>
                                {tags.map((t) => (
                                    <option key={t.id} value={t.name}>
                                        {t.name} ({t.note_count})
                                    </option>
                                ))}
                            </select>
                        </div>
                    )}

                    {/* Generate button */}
                    <button
                        onClick={handleGenerate}
                        disabled={loading || !canGenerate()}
                        className="w-full flex items-center justify-center gap-2 px-6 py-4 text-base font-semibold bg-purple-600 hover:bg-purple-500 text-white rounded-xl transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                        {loading ? (
                            <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                        ) : (
                            <FiZap className="w-5 h-5" />
                        )}
                        {loading ? 'Generiert Zusammenfassung...' : 'Zusammenfassung generieren'}
                    </button>

                    {/* Result */}
                    {result && (
                        <div className="bg-dark-800/50 border border-dark-700 rounded-xl p-6">
                            <div className="flex items-center justify-between mb-4">
                                <div className="flex items-center gap-2">
                                    <FiFileText className="w-4 h-4 text-purple-400" />
                                    <h3 className="text-sm font-semibold text-white">Zusammenfassung</h3>
                                </div>
                                <span className="text-xs text-dark-500">{result.source_count} Notizen analysiert</span>
                            </div>
                            <article className="markdown-content text-sm">
                                <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins} components={markdownComponents}>
                                    {result.summary}
                                </ReactMarkdown>
                            </article>
                            <div className="mt-4 pt-4 border-t border-dark-700 flex justify-end">
                                <button
                                    onClick={handleGenerate}
                                    disabled={loading}
                                    className="flex items-center gap-1.5 px-3 py-2 text-xs bg-dark-700 hover:bg-dark-600 text-white rounded-lg transition-colors"
                                >
                                    <FiRefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
                                    Neu generieren
                                </button>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
