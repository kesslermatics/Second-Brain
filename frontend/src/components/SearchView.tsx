'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { FiSearch, FiX, FiFolder, FiTag, FiArrowRight } from 'react-icons/fi';
import { searchNotes, getNote } from '@/lib/api';
import { useStore } from '@/lib/store';
import type { SearchResultItem } from '@/lib/types';

export default function SearchView() {
    const [query, setQuery] = useState('');
    const [results, setResults] = useState<SearchResultItem[]>([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(false);
    const [searched, setSearched] = useState(false);
    const inputRef = useRef<HTMLInputElement>(null);
    const debounceRef = useRef<ReturnType<typeof setTimeout>>();
    const { setSelectedNote, setActiveView } = useStore();

    useEffect(() => {
        inputRef.current?.focus();
    }, []);

    const doSearch = useCallback(async (q: string) => {
        if (!q.trim()) {
            setResults([]);
            setTotal(0);
            setSearched(false);
            return;
        }
        setLoading(true);
        setSearched(true);
        try {
            const resp = await searchNotes(q.trim(), 20);
            setResults(resp.results);
            setTotal(resp.total);
        } catch (e) {
            console.error(e);
        } finally {
            setLoading(false);
        }
    }, []);

    const handleInput = (value: string) => {
        setQuery(value);
        if (debounceRef.current) clearTimeout(debounceRef.current);
        debounceRef.current = setTimeout(() => doSearch(value), 400);
    };

    const handleNavigate = async (noteId: string) => {
        try {
            const note = await getNote(noteId);
            setSelectedNote(note);
            setActiveView('notes');
        } catch (e) {
            console.error(e);
        }
    };

    const renderSnippet = (snippet: string) => {
        // Snippet contains **bold** highlighting from backend
        const parts = snippet.split(/(\*\*.*?\*\*)/g);
        return parts.map((part, i) => {
            if (part.startsWith('**') && part.endsWith('**')) {
                return (
                    <span key={i} className="font-bold text-brain-400 bg-brain-600/20 px-0.5 rounded">
                        {part.slice(2, -2)}
                    </span>
                );
            }
            return <span key={i}>{part}</span>;
        });
    };

    return (
        <div className="h-full flex flex-col">
            {/* Search header */}
            <div className="px-4 sm:px-6 py-4 sm:py-6 border-b border-dark-800 bg-dark-900/50">
                <div className="max-w-3xl mx-auto">
                    <div className="relative">
                        <FiSearch className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-dark-500" />
                        <input
                            ref={inputRef}
                            type="text"
                            value={query}
                            onChange={(e) => handleInput(e.target.value)}
                            placeholder="Semantische Suche in deinem Second Brain..."
                            className="w-full pl-12 pr-12 py-3 sm:py-4 bg-dark-800 border border-dark-700 rounded-2xl text-white text-base sm:text-lg placeholder-dark-600 focus:outline-none focus:border-brain-500 transition-colors"
                        />
                        {query && (
                            <button
                                onClick={() => { setQuery(''); setResults([]); setSearched(false); inputRef.current?.focus(); }}
                                className="absolute right-4 top-1/2 -translate-y-1/2 p-1 hover:bg-dark-700 rounded-lg transition-colors"
                            >
                                <FiX className="w-5 h-5 text-dark-500" />
                            </button>
                        )}
                    </div>
                    {searched && !loading && (
                        <p className="mt-3 text-sm text-dark-500">
                            {total} {total === 1 ? 'Ergebnis' : 'Ergebnisse'} für &quot;{query}&quot;
                        </p>
                    )}
                </div>
            </div>

            {/* Results */}
            <div className="flex-1 overflow-y-auto p-4 sm:p-6">
                <div className="max-w-3xl mx-auto space-y-3">
                    {loading && (
                        <div className="flex items-center justify-center py-12">
                            <div className="animate-spin w-6 h-6 border-2 border-brain-500 border-t-transparent rounded-full" />
                            <span className="ml-3 text-dark-400">Suche läuft...</span>
                        </div>
                    )}

                    {!loading && searched && results.length === 0 && (
                        <div className="text-center py-12">
                            <FiSearch className="w-12 h-12 text-dark-700 mx-auto mb-4" />
                            <p className="text-dark-500">Keine Ergebnisse gefunden</p>
                        </div>
                    )}

                    {!loading && results.map((item) => (
                        <div
                            key={item.note_id}
                            onClick={() => handleNavigate(item.note_id)}
                            className="group p-4 bg-dark-800/50 border border-dark-700 rounded-xl hover:border-brain-500/50 hover:bg-dark-800 cursor-pointer transition-all"
                        >
                            <div className="flex items-start justify-between gap-3">
                                <div className="flex-1 min-w-0">
                                    <h3 className="text-white font-semibold text-base group-hover:text-brain-400 transition-colors truncate">
                                        {item.title}
                                    </h3>
                                    <div className="flex items-center gap-3 mt-1 text-xs text-dark-500">
                                        <span className="flex items-center gap-1">
                                            <FiFolder className="w-3 h-3" />
                                            {item.folder_path}
                                        </span>
                                        <span className="text-dark-600">
                                            Score: {(item.score * 100).toFixed(0)}%
                                        </span>
                                    </div>
                                    {item.tags.length > 0 && (
                                        <div className="flex flex-wrap gap-1.5 mt-2">
                                            {item.tags.map((tag) => (
                                                <span key={tag} className="flex items-center gap-1 px-2 py-0.5 text-xs bg-brain-600/15 text-brain-400 rounded-full">
                                                    <FiTag className="w-2.5 h-2.5" />
                                                    {tag}
                                                </span>
                                            ))}
                                        </div>
                                    )}
                                    <p className="mt-2 text-sm text-dark-400 leading-relaxed line-clamp-2">
                                        {renderSnippet(item.snippet)}
                                    </p>
                                </div>
                                <FiArrowRight className="w-4 h-4 text-dark-600 group-hover:text-brain-400 flex-shrink-0 mt-1 transition-colors" />
                            </div>
                        </div>
                    ))}

                    {!searched && !loading && (
                        <div className="text-center py-16">
                            <div className="inline-flex items-center justify-center w-20 h-20 rounded-2xl bg-dark-800 mb-6">
                                <FiSearch className="w-10 h-10 text-dark-600" />
                            </div>
                            <h3 className="text-xl font-semibold text-white mb-2">Semantische Suche</h3>
                            <p className="text-sm text-dark-500 max-w-md mx-auto">
                                Durchsuche dein Second Brain mit natürlicher Sprache. Die Suche findet auch inhaltlich verwandte Notizen.
                            </p>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
