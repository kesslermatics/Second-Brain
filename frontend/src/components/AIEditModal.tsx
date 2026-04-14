'use client';

import { useState } from 'react';
import { FiCheck, FiX, FiZap, FiSend } from 'react-icons/fi';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { aiEditNote } from '@/lib/api';

interface Props {
    noteId: string;
    currentContent: string;
    onClose: () => void;
    onAccept: (newContent: string) => Promise<void>;
}

export default function AIEditModal({ noteId, currentContent, onClose, onAccept }: Props) {
    const [instruction, setInstruction] = useState('');
    const [suggestedContent, setSuggestedContent] = useState<string | null>(null);
    const [loading, setLoading] = useState(false);
    const [accepting, setAccepting] = useState(false);

    const handleGenerate = async () => {
        if (!instruction.trim()) return;
        setLoading(true);
        try {
            const result = await aiEditNote(noteId, instruction);
            setSuggestedContent(result.suggested_content);
        } catch (e) {
            console.error(e);
            alert('Fehler bei der KI-Bearbeitung.');
        } finally {
            setLoading(false);
        }
    };

    const handleAccept = async () => {
        if (!suggestedContent) return;
        setAccepting(true);
        try {
            await onAccept(suggestedContent);
        } finally {
            setAccepting(false);
        }
    };

    return (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4" onClick={onClose}>
            <div
                className="bg-dark-900 rounded-2xl border border-dark-800 w-full max-w-4xl max-h-[80vh] flex flex-col shadow-2xl"
                onClick={(e) => e.stopPropagation()}
            >
                {/* Header */}
                <div className="flex items-center justify-between px-6 py-4 border-b border-dark-800">
                    <div className="flex items-center gap-2">
                        <FiZap className="w-5 h-5 text-purple-400" />
                        <h2 className="text-lg font-semibold text-white">KI-Bearbeitung</h2>
                    </div>
                    <button onClick={onClose} className="p-2 hover:bg-dark-800 rounded-lg">
                        <FiX className="w-5 h-5 text-dark-500" />
                    </button>
                </div>

                {/* Instruction input */}
                <div className="px-6 py-4 border-b border-dark-800">
                    <p className="text-sm text-dark-400 mb-2">
                        Beschreibe, was die KI an der Notiz ändern soll:
                    </p>
                    <div className="flex gap-2">
                        <input
                            type="text"
                            value={instruction}
                            onChange={(e) => setInstruction(e.target.value)}
                            onKeyDown={(e) => e.key === 'Enter' && handleGenerate()}
                            placeholder="z.B. 'Füge eine Zusammenfassung am Anfang hinzu' oder 'Übersetze ins Englische'"
                            className="flex-1 px-4 py-3 bg-dark-950 border border-dark-700 rounded-xl text-white text-sm placeholder-dark-600 focus:outline-none focus:border-purple-500"
                            autoFocus
                        />
                        <button
                            onClick={handleGenerate}
                            disabled={!instruction.trim() || loading}
                            className="px-4 py-3 bg-purple-600 hover:bg-purple-500 text-white rounded-xl transition-colors disabled:opacity-50 flex items-center gap-2"
                        >
                            {loading ? (
                                <div className="animate-spin w-4 h-4 border-2 border-white border-t-transparent rounded-full" />
                            ) : (
                                <FiSend className="w-4 h-4" />
                            )}
                            Generieren
                        </button>
                    </div>
                </div>

                {/* Content comparison */}
                <div className="flex-1 overflow-hidden flex">
                    {/* Original */}
                    <div className="flex-1 overflow-y-auto border-r border-dark-800">
                        <div className="px-4 py-2 bg-dark-800/50 text-xs font-semibold text-dark-400 uppercase tracking-wider sticky top-0">
                            Original
                        </div>
                        <div className="p-4 markdown-content text-sm">
                            <ReactMarkdown remarkPlugins={[remarkGfm]}>{currentContent}</ReactMarkdown>
                        </div>
                    </div>

                    {/* Suggested */}
                    <div className="flex-1 overflow-y-auto">
                        <div className="px-4 py-2 bg-purple-600/10 text-xs font-semibold text-purple-400 uppercase tracking-wider sticky top-0">
                            KI-Vorschlag
                        </div>
                        <div className="p-4 markdown-content text-sm">
                            {suggestedContent ? (
                                <ReactMarkdown remarkPlugins={[remarkGfm]}>{suggestedContent}</ReactMarkdown>
                            ) : (
                                <p className="text-dark-600 text-center mt-8">
                                    {loading ? 'Generiert...' : 'Gib oben eine Anweisung ein und klicke auf "Generieren"'}
                                </p>
                            )}
                        </div>
                    </div>
                </div>

                {/* Actions */}
                {suggestedContent && (
                    <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-dark-800">
                        <button
                            onClick={onClose}
                            className="flex items-center gap-1.5 px-4 py-2 text-sm text-dark-400 hover:text-white transition-colors"
                        >
                            <FiX className="w-4 h-4" />
                            Ablehnen
                        </button>
                        <button
                            onClick={handleAccept}
                            disabled={accepting}
                            className="flex items-center gap-1.5 px-4 py-2 text-sm bg-green-600 hover:bg-green-500 text-white rounded-lg transition-colors disabled:opacity-50"
                        >
                            <FiCheck className="w-4 h-4" />
                            {accepting ? 'Übernehme...' : 'Übernehmen'}
                        </button>
                    </div>
                )}
            </div>
        </div>
    );
}
