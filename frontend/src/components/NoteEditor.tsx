'use client';

import { useState } from 'react';
import { FiSave, FiX } from 'react-icons/fi';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { markdownComponents } from '@/lib/markdownComponents';
import type { Note } from '@/lib/types';

interface Props {
    note: Note;
    onClose: () => void;
    onSave: (title: string, content: string) => Promise<void>;
}

export default function NoteEditor({ note, onClose, onSave }: Props) {
    const [title, setTitle] = useState(note.title);
    const [content, setContent] = useState(note.content);
    const [saving, setSaving] = useState(false);
    const [preview, setPreview] = useState(false);

    const handleSave = async () => {
        setSaving(true);
        try {
            await onSave(title, content);
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="h-full flex flex-col">
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-dark-800 bg-dark-900/50">
                <div className="flex items-center gap-3">
                    <input
                        type="text"
                        value={title}
                        onChange={(e) => setTitle(e.target.value)}
                        className="text-lg font-semibold bg-transparent text-white border-b border-dark-700 focus:border-brain-500 focus:outline-none px-1 py-0.5"
                    />
                </div>
                <div className="flex items-center gap-2">
                    <button
                        onClick={() => setPreview(!preview)}
                        className={`px-3 py-2 text-sm rounded-lg transition-colors ${preview
                            ? 'bg-brain-600/20 text-brain-400'
                            : 'bg-dark-800 text-dark-400 hover:text-white'
                            }`}
                    >
                        {preview ? 'Editor' : 'Vorschau'}
                    </button>
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

            {/* Editor / Preview */}
            <div className="flex-1 overflow-y-auto">
                {preview ? (
                    <div className="max-w-4xl mx-auto px-8 py-8">
                        <article className="markdown-content">
                            <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>{content}</ReactMarkdown>
                        </article>
                    </div>
                ) : (
                    <textarea
                        value={content}
                        onChange={(e) => setContent(e.target.value)}
                        className="w-full h-full px-8 py-8 bg-transparent text-white text-sm font-mono leading-relaxed resize-none focus:outline-none"
                        placeholder="Notiz in Markdown schreiben..."
                    />
                )}
            </div>
        </div>
    );
}
