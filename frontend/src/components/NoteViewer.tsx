'use client';

import { useState } from 'react';
import { FiEdit2, FiTrash2, FiFolder, FiClock, FiArrowLeft, FiZap } from 'react-icons/fi';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { markdownComponents } from '@/lib/markdownComponents';
import { useStore } from '@/lib/store';
import { deleteNote, updateNote } from '@/lib/api';
import NoteEditor from './NoteEditor';
import AIEditModal from './AIEditModal';

export default function NoteViewer() {
    const { selectedNote, setSelectedNote, loadFolderTree } = useStore();
    const [editing, setEditing] = useState(false);
    const [showAIEdit, setShowAIEdit] = useState(false);

    if (!selectedNote) return null;

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

    if (editing) {
        return (
            <NoteEditor
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
            <div className="flex items-center justify-between px-6 py-4 border-b border-dark-800 bg-dark-900/50">
                <div className="flex items-center gap-3">
                    <button
                        onClick={() => setSelectedNote(null)}
                        className="p-2 hover:bg-dark-800 rounded-lg transition-colors"
                    >
                        <FiArrowLeft className="w-4 h-4 text-dark-400" />
                    </button>
                    <div>
                        <h1 className="text-lg font-semibold text-white">{selectedNote.title}</h1>
                        <div className="flex items-center gap-3 text-xs text-dark-500 mt-0.5">
                            {selectedNote.folder_path && (
                                <span className="flex items-center gap-1">
                                    <FiFolder className="w-3 h-3" />
                                    {selectedNote.folder_path}
                                </span>
                            )}
                            <span className="flex items-center gap-1">
                                <FiClock className="w-3 h-3" />
                                {formatDate(selectedNote.updated_at)}
                            </span>
                        </div>
                    </div>
                </div>
                <div className="flex items-center gap-2">
                    <button
                        onClick={() => setShowAIEdit(true)}
                        className="flex items-center gap-1.5 px-3 py-2 text-sm bg-purple-600/20 text-purple-400 hover:bg-purple-600/30 rounded-lg transition-colors"
                    >
                        <FiZap className="w-4 h-4" />
                        KI-Bearbeitung
                    </button>
                    <button
                        onClick={() => setEditing(true)}
                        className="flex items-center gap-1.5 px-3 py-2 text-sm bg-dark-800 hover:bg-dark-700 text-white rounded-lg transition-colors"
                    >
                        <FiEdit2 className="w-4 h-4" />
                        Bearbeiten
                    </button>
                    <button
                        onClick={handleDelete}
                        className="flex items-center gap-1.5 px-3 py-2 text-sm bg-red-600/10 text-red-400 hover:bg-red-600/20 rounded-lg transition-colors"
                    >
                        <FiTrash2 className="w-4 h-4" />
                        Löschen
                    </button>
                </div>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto">
                <div className="max-w-4xl mx-auto px-8 py-8">
                    <article className="markdown-content">
                        <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
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
