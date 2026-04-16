'use client';

import { useState, useEffect } from 'react';
import { FiEdit2, FiTrash2, FiFolder, FiClock, FiArrowLeft, FiZap, FiLink, FiBookOpen, FiChevronDown, FiChevronRight, FiTag } from 'react-icons/fi';
import ReactMarkdown from 'react-markdown';
import { markdownComponents, remarkPlugins, rehypePlugins } from '@/lib/markdownComponents';
import { useStore } from '@/lib/store';
import { deleteNote, updateNote, autoLinkNote, generateFlashcards } from '@/lib/api';
import RichTextEditor from './RichTextEditor';
import AIEditModal from './AIEditModal';
import TagEditor from './TagEditor';
import VersionHistory from './VersionHistory';
import type { Note } from '@/lib/types';

export default function NoteViewer() {
    const { selectedNote, setSelectedNote, loadFolderTree, pendingEdit, setPendingEdit } = useStore();
    const [editing, setEditing] = useState(false);
    const [showAIEdit, setShowAIEdit] = useState(false);
    const [showHistory, setShowHistory] = useState(false);
    const [linking, setLinking] = useState(false);
    const [generatingCards, setGeneratingCards] = useState(false);
    const [linkResult, setLinkResult] = useState<string | null>(null);
    const [cardResult, setCardResult] = useState<string | null>(null);
    const [tagsCollapsed, setTagsCollapsed] = useState(true);

    // Auto-open editor for newly created notes
    useEffect(() => {
        if (pendingEdit && selectedNote) {
            setEditing(true);
            setPendingEdit(false);
        }
    }, [pendingEdit, selectedNote, setPendingEdit]);

    if (!selectedNote) return null;

    if (showHistory) {
        return (
            <VersionHistory
                note={selectedNote}
                onClose={() => setShowHistory(false)}
                onRestore={(restored: Note) => {
                    setSelectedNote(restored);
                    setShowHistory(false);
                }}
            />
        );
    }

    const handleDelete = async () => {
        if (!confirm('Notiz wirklich löschen?')) return;
        try {
            await deleteNote(selectedNote.id);
            setSelectedNote(null);
            await loadFolderTree();
        } catch (e) {
            console.error(e);
        }
    };

    const handleAutoLink = async () => {
        setLinking(true);
        setLinkResult(null);
        try {
            const links = await autoLinkNote(selectedNote.id);
            setLinkResult(`${links.length} Verknüpfung${links.length !== 1 ? 'en' : ''} erstellt`);
            setTimeout(() => setLinkResult(null), 3000);
        } catch (e) {
            console.error(e);
        } finally {
            setLinking(false);
        }
    };

    const handleGenerateCards = async () => {
        setGeneratingCards(true);
        setCardResult(null);
        try {
            const cards = await generateFlashcards(selectedNote.id);
            setCardResult(`${cards.length} Karteikarte${cards.length !== 1 ? 'n' : ''} erstellt`);
            setTimeout(() => setCardResult(null), 3000);
        } catch (e) {
            console.error(e);
        } finally {
            setGeneratingCards(false);
        }
    };

    if (editing) {
        return (
            <RichTextEditor
                note={selectedNote}
                onClose={() => setEditing(false)}
                onSave={async (title, content) => {
                    try {
                        const updated = await updateNote(selectedNote.id, { title, content });
                        setSelectedNote(updated);
                        setEditing(false);
                        await loadFolderTree();
                    } catch (e) {
                        console.error(e);
                    }
                }}
            />
        );
    }

    const formatDate = (date: string) => {
        return new Date(date).toLocaleDateString('de-DE', {
            day: '2-digit',
            month: '2-digit',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
        });
    };

    return (
        <div className="h-full flex flex-col">
            {/* Header */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between px-3 sm:px-6 py-3 sm:py-4 border-b border-dark-800 bg-dark-900/50 gap-2">
                <div className="flex items-center gap-3 min-w-0">
                    <button
                        onClick={() => setSelectedNote(null)}
                        className="p-2 hover:bg-dark-800 rounded-lg transition-colors flex-shrink-0"
                    >
                        <FiArrowLeft className="w-4 h-4 text-dark-400" />
                    </button>
                    <div className="min-w-0">
                        <div className="flex items-center gap-2">
                            <h1 className="text-base sm:text-lg font-semibold text-white truncate">{selectedNote.title}</h1>
                        </div>
                        <div className="flex items-center gap-3 text-xs text-dark-500 mt-0.5">
                            {selectedNote.folder_path && (
                                <span className="flex items-center gap-1 truncate">
                                    <FiFolder className="w-3 h-3 flex-shrink-0" />
                                    <span className="truncate">{selectedNote.folder_path}</span>
                                </span>
                            )}
                            <span className="flex items-center gap-1 flex-shrink-0">
                                <FiClock className="w-3 h-3" />
                                {formatDate(selectedNote.updated_at)}
                            </span>
                        </div>
                    </div>
                </div>
                <div className="flex items-center gap-1.5 sm:gap-2 overflow-x-auto pb-1 sm:pb-0 flex-shrink-0">
                    <button
                        onClick={handleAutoLink}
                        disabled={linking}
                        className="flex items-center gap-1.5 px-2 sm:px-3 py-1.5 sm:py-2 text-xs sm:text-sm bg-cyan-600/20 text-cyan-400 hover:bg-cyan-600/30 rounded-lg transition-colors disabled:opacity-50 flex-shrink-0"
                        title="KI-Verknüpfungen erstellen"
                    >
                        {linking ? (
                            <div className="w-4 h-4 border-2 border-cyan-400 border-t-transparent rounded-full animate-spin" />
                        ) : (
                            <FiLink className="w-4 h-4" />
                        )}
                        <span className="hidden sm:inline">{linkResult || 'Verknüpfen'}</span>
                    </button>
                    <button
                        onClick={handleGenerateCards}
                        disabled={generatingCards}
                        className="flex items-center gap-1.5 px-2 sm:px-3 py-1.5 sm:py-2 text-xs sm:text-sm bg-green-600/20 text-green-400 hover:bg-green-600/30 rounded-lg transition-colors disabled:opacity-50 flex-shrink-0"
                        title="Karteikarten generieren"
                    >
                        {generatingCards ? (
                            <div className="w-4 h-4 border-2 border-green-400 border-t-transparent rounded-full animate-spin" />
                        ) : (
                            <FiBookOpen className="w-4 h-4" />
                        )}
                        <span className="hidden sm:inline">{cardResult || 'Lernkarten'}</span>
                    </button>
                    <button
                        onClick={() => setShowHistory(true)}
                        className="flex items-center gap-1.5 px-2 sm:px-3 py-1.5 sm:py-2 text-xs sm:text-sm bg-orange-600/20 text-orange-400 hover:bg-orange-600/30 rounded-lg transition-colors flex-shrink-0"
                    >
                        <FiClock className="w-4 h-4" />
                        <span className="hidden sm:inline">Verlauf</span>
                    </button>
                    <button
                        onClick={() => setShowAIEdit(true)}
                        className="flex items-center gap-1.5 px-2 sm:px-3 py-1.5 sm:py-2 text-xs sm:text-sm bg-purple-600/20 text-purple-400 hover:bg-purple-600/30 rounded-lg transition-colors flex-shrink-0"
                    >
                        <FiZap className="w-4 h-4" />
                        <span className="hidden sm:inline">KI-Bearbeitung</span>
                    </button>
                    <button
                        onClick={() => setEditing(true)}
                        className="flex items-center gap-1.5 px-2 sm:px-3 py-1.5 sm:py-2 text-xs sm:text-sm bg-dark-800 hover:bg-dark-700 text-white rounded-lg transition-colors flex-shrink-0"
                    >
                        <FiEdit2 className="w-4 h-4" />
                        <span className="hidden sm:inline">Bearbeiten</span>
                    </button>
                    <button
                        onClick={handleDelete}
                        className="flex items-center gap-1.5 px-2 sm:px-3 py-1.5 sm:py-2 text-xs sm:text-sm bg-red-600/10 text-red-400 hover:bg-red-600/20 rounded-lg transition-colors flex-shrink-0"
                    >
                        <FiTrash2 className="w-4 h-4" />
                        <span className="hidden sm:inline">Löschen</span>
                    </button>
                </div>
            </div>

            {/* Tags */}
            <div className="px-6 py-2 border-b border-dark-800 bg-dark-900/30">
                <button
                    onClick={() => setTagsCollapsed(!tagsCollapsed)}
                    className="flex items-center gap-1.5 text-xs text-dark-500 hover:text-white transition-colors mb-1"
                >
                    {tagsCollapsed ? <FiChevronRight className="w-3 h-3" /> : <FiChevronDown className="w-3 h-3" />}
                    <FiTag className="w-3 h-3" />
                    Tags ({(selectedNote.tags || []).length})
                </button>
                {!tagsCollapsed && (
                    <TagEditor
                        note={selectedNote}
                        onUpdate={(updated) => setSelectedNote(updated)}
                    />
                )}
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto">
                <div className="max-w-4xl mx-auto px-4 sm:px-8 py-4 sm:py-8">
                    <article className="markdown-content">
                        <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins} components={markdownComponents}>
                            {selectedNote.content}
                        </ReactMarkdown>
                    </article>
                </div>
            </div>

            {/* AI Edit Modal */}
            {showAIEdit && (
                <AIEditModal
                    noteId={selectedNote.id}
                    currentContent={selectedNote.content}
                    onClose={() => setShowAIEdit(false)}
                    onAccept={async (newContent) => {
                        try {
                            const updated = await updateNote(selectedNote.id, { content: newContent });
                            setSelectedNote(updated);
                            setShowAIEdit(false);
                            await loadFolderTree();
                        } catch (e) {
                            console.error(e);
                        }
                    }}
                />
            )}
        </div>
    );
}
