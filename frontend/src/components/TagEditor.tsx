'use client';

import { useState, useEffect, useRef } from 'react';
import { FiTag, FiX, FiPlus, FiZap } from 'react-icons/fi';
import { getTags, createTag, suggestTags, updateNote } from '@/lib/api';
import type { Tag, Note } from '@/lib/types';

interface TagEditorProps {
    note: Note;
    onUpdate: (note: Note) => void;
}

const TAG_COLORS = [
    '#8b5cf6', '#3b82f6', '#10b981', '#f59e0b', '#ef4444',
    '#ec4899', '#06b6d4', '#84cc16', '#f97316', '#6366f1',
];

export default function TagEditor({ note, onUpdate }: TagEditorProps) {
    const [allTags, setAllTags] = useState<Tag[]>([]);
    const [showDropdown, setShowDropdown] = useState(false);
    const [newTagName, setNewTagName] = useState('');
    const [suggesting, setSuggesting] = useState(false);
    const [suggestions, setSuggestions] = useState<string[]>([]);
    const dropdownRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        loadTags();
    }, []);

    useEffect(() => {
        const handleClick = (e: MouseEvent) => {
            if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
                setShowDropdown(false);
            }
        };
        document.addEventListener('mousedown', handleClick);
        return () => document.removeEventListener('mousedown', handleClick);
    }, []);

    const loadTags = async () => {
        try {
            const tags = await getTags();
            setAllTags(tags);
        } catch (e) {
            console.error(e);
        }
    };

    const handleAddTag = async (tagId: string) => {
        const currentTagIds = note.tags.map((t) => t.id);
        if (currentTagIds.includes(tagId)) return;
        try {
            const updated = await updateNote(note.id, { tag_ids: [...currentTagIds, tagId] });
            onUpdate(updated);
        } catch (e) {
            console.error(e);
        }
    };

    const handleRemoveTag = async (tagId: string) => {
        const newTagIds = note.tags.filter((t) => t.id !== tagId).map((t) => t.id);
        try {
            const updated = await updateNote(note.id, { tag_ids: newTagIds });
            onUpdate(updated);
        } catch (e) {
            console.error(e);
        }
    };

    const handleCreateAndAdd = async () => {
        if (!newTagName.trim()) return;
        try {
            const color = TAG_COLORS[Math.floor(Math.random() * TAG_COLORS.length)];
            const tag = await createTag(newTagName.trim(), color);
            await loadTags();
            const currentTagIds = note.tags.map((t) => t.id);
            const updated = await updateNote(note.id, { tag_ids: [...currentTagIds, tag.id] });
            onUpdate(updated);
            setNewTagName('');
        } catch (e) {
            console.error(e);
        }
    };

    const handleSuggest = async () => {
        setSuggesting(true);
        try {
            const resp = await suggestTags(note.title, note.content);
            setSuggestions(resp.suggested_tags);
            // Auto-add existing matches
            for (const match of resp.existing_matches) {
                const currentTagIds = note.tags.map((t) => t.id);
                if (!currentTagIds.includes(match.id)) {
                    const updated = await updateNote(note.id, { tag_ids: [...currentTagIds, match.id] });
                    onUpdate(updated);
                }
            }
        } catch (e) {
            console.error(e);
        } finally {
            setSuggesting(false);
        }
    };

    const handleAddSuggested = async (name: string) => {
        // Check if exists
        const existing = allTags.find((t) => t.name.toLowerCase() === name.toLowerCase());
        if (existing) {
            await handleAddTag(existing.id);
        } else {
            const color = TAG_COLORS[Math.floor(Math.random() * TAG_COLORS.length)];
            const tag = await createTag(name, color);
            await loadTags();
            const currentTagIds = note.tags.map((t) => t.id);
            const updated = await updateNote(note.id, { tag_ids: [...currentTagIds, tag.id] });
            onUpdate(updated);
        }
        setSuggestions((prev) => prev.filter((s) => s !== name));
    };

    const availableTags = allTags.filter(
        (t) => !note.tags.find((nt) => nt.id === t.id)
    );

    return (
        <div className="space-y-2">
            {/* Current tags */}
            <div className="flex flex-wrap items-center gap-1.5">
                {note.tags.map((tag) => (
                    <span
                        key={tag.id}
                        className="inline-flex items-center gap-1 px-2.5 py-1 text-xs rounded-full border"
                        style={{
                            backgroundColor: `${tag.color || '#6366f1'}15`,
                            borderColor: `${tag.color || '#6366f1'}40`,
                            color: tag.color || '#6366f1',
                        }}
                    >
                        <FiTag className="w-2.5 h-2.5" />
                        {tag.name}
                        <button
                            onClick={() => handleRemoveTag(tag.id)}
                            className="ml-0.5 hover:opacity-70 transition-opacity"
                        >
                            <FiX className="w-3 h-3" />
                        </button>
                    </span>
                ))}

                <div className="relative" ref={dropdownRef}>
                    <button
                        onClick={() => setShowDropdown(!showDropdown)}
                        className="inline-flex items-center gap-1 px-2 py-1 text-xs text-dark-500 hover:text-white bg-dark-800 hover:bg-dark-700 rounded-full transition-colors"
                    >
                        <FiPlus className="w-3 h-3" />
                        Tag
                    </button>

                    {showDropdown && (
                        <div className="absolute left-0 top-full mt-1 w-56 bg-dark-800 border border-dark-700 rounded-xl shadow-xl z-50 overflow-hidden">
                            {/* New tag input */}
                            <div className="p-2 border-b border-dark-700">
                                <div className="flex gap-1">
                                    <input
                                        type="text"
                                        value={newTagName}
                                        onChange={(e) => setNewTagName(e.target.value)}
                                        onKeyDown={(e) => { if (e.key === 'Enter') handleCreateAndAdd(); }}
                                        placeholder="Neuer Tag..."
                                        className="flex-1 px-2 py-1.5 text-xs bg-dark-900 border border-dark-600 rounded-lg text-white placeholder-dark-600 focus:outline-none focus:border-brain-500"
                                    />
                                    <button
                                        onClick={handleCreateAndAdd}
                                        disabled={!newTagName.trim()}
                                        className="px-2 py-1.5 text-xs bg-brain-600 text-white rounded-lg hover:bg-brain-500 disabled:opacity-40 transition-colors"
                                    >
                                        <FiPlus className="w-3 h-3" />
                                    </button>
                                </div>
                            </div>

                            {/* AI suggest */}
                            <div className="p-2 border-b border-dark-700">
                                <button
                                    onClick={handleSuggest}
                                    disabled={suggesting}
                                    className="w-full flex items-center justify-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-purple-600/20 text-purple-400 hover:bg-purple-600/30 rounded-lg transition-colors disabled:opacity-50"
                                >
                                    {suggesting ? (
                                        <div className="w-3 h-3 border-2 border-purple-400 border-t-transparent rounded-full animate-spin" />
                                    ) : (
                                        <FiZap className="w-3 h-3" />
                                    )}
                                    KI-Vorschläge
                                </button>
                            </div>

                            {/* Suggestions */}
                            {suggestions.length > 0 && (
                                <div className="p-2 border-b border-dark-700">
                                    <p className="text-[10px] uppercase text-dark-500 font-semibold tracking-wider mb-1 px-1">Vorschläge</p>
                                    <div className="flex flex-wrap gap-1">
                                        {suggestions.map((s) => (
                                            <button
                                                key={s}
                                                onClick={() => handleAddSuggested(s)}
                                                className="px-2 py-1 text-xs bg-brain-600/15 text-brain-400 rounded-full hover:bg-brain-600/25 transition-colors"
                                            >
                                                + {s}
                                            </button>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {/* Existing tags */}
                            <div className="max-h-40 overflow-y-auto p-1">
                                {availableTags.length === 0 ? (
                                    <p className="text-xs text-dark-500 text-center py-2">Keine weiteren Tags</p>
                                ) : (
                                    availableTags.map((tag) => (
                                        <button
                                            key={tag.id}
                                            onClick={() => handleAddTag(tag.id)}
                                            className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-dark-300 hover:bg-dark-700 rounded-lg transition-colors"
                                        >
                                            <span
                                                className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                                                style={{ backgroundColor: tag.color || '#6366f1' }}
                                            />
                                            {tag.name}
                                            <span className="ml-auto text-dark-600">{tag.note_count}</span>
                                        </button>
                                    ))
                                )}
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
