'use client';

import { useState, useRef, useEffect } from 'react';
import { FiSend, FiSave, FiX, FiCheck, FiRefreshCw, FiMessageSquare } from 'react-icons/fi';
import { LuBrain } from 'react-icons/lu';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { markdownComponents } from '@/lib/markdownComponents';
import { useStore } from '@/lib/store';
import {
    sendChatMessage, getChatSession, createChatSession,
    ensureFolderPath, createNote, getStreamingUrl,
} from '@/lib/api';
import type { ChatSessionDetail, ChatMessage } from '@/lib/types';

interface Props {
    session: ChatSessionDetail | null;
    type: 'notes' | 'qa';
}

export default function ChatPanel({ session, type }: Props) {
    const [message, setMessage] = useState('');
    const [loading, setLoading] = useState(false);
    const [messages, setMessages] = useState<ChatMessage[]>([]);
    const [savingNote, setSavingNote] = useState<string | null>(null);
    const [savedNotes, setSavedNotes] = useState<Set<string>>(new Set());
    const [dismissedNotes, setDismissedNotes] = useState<Set<string>>(new Set());
    const [refineMessageId, setRefineMessageId] = useState<string | null>(null);
    const [refineInput, setRefineInput] = useState('');
    const [refining, setRefining] = useState(false);
    const messagesEndRef = useRef<HTMLDivElement>(null);
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const refineInputRef = useRef<HTMLInputElement>(null);
    const {
        setActiveNotesSession, setActiveQASession,
        loadNotesSessions, loadQASessions, loadFolderTree,
    } = useStore();

    useEffect(() => {
        if (session) {
            setMessages(session.messages);
        } else {
            setMessages([]);
        }
    }, [session]);

    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [messages]);

    const adjustTextarea = () => {
        const textarea = textareaRef.current;
        if (textarea) {
            textarea.style.height = 'auto';
            textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`;
        }
    };

    const handleSend = async () => {
        if (!message.trim() || loading) return;

        let currentSession = session;

        // Create session if none exists
        if (!currentSession) {
            try {
                const newSession = await createChatSession(type, message.slice(0, 50));
                const detail = await getChatSession(newSession.id);
                currentSession = detail;
                if (type === 'notes') {
                    setActiveNotesSession(detail);
                } else {
                    setActiveQASession(detail);
                }
            } catch (e) {
                console.error(e);
                return;
            }
        }

        const userMsg: ChatMessage = {
            id: `temp-${Date.now()}`,
            session_id: currentSession.id,
            role: 'user',
            content: message,
            created_at: new Date().toISOString(),
        };

        setMessages((prev) => [...prev, userMsg]);
        setMessage('');
        setLoading(true);

        if (textareaRef.current) {
            textareaRef.current.style.height = 'auto';
        }

        try {
            if (type === 'qa') {
                // SSE streaming for QA
                const streamUrl = getStreamingUrl();
                const token = typeof window !== 'undefined' ? localStorage.getItem('brain_token') : '';
                const response = await fetch(`${streamUrl}/chat/sessions/${currentSession.id}/messages/stream`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': `Bearer ${token}`,
                    },
                    body: JSON.stringify({ content: userMsg.content }),
                });

                if (!response.ok) throw new Error('Stream failed');

                const reader = response.body?.getReader();
                const decoder = new TextDecoder();
                let fullContent = '';
                const streamMsgId = `stream-${Date.now()}`;

                // Add placeholder message
                setMessages((prev) => [...prev, {
                    id: streamMsgId,
                    session_id: currentSession.id,
                    role: 'assistant',
                    content: '',
                    created_at: new Date().toISOString(),
                }]);

                if (reader) {
                    let buffer = '';
                    while (true) {
                        const { done, value } = await reader.read();
                        if (done) break;
                        buffer += decoder.decode(value, { stream: true });
                        const lines = buffer.split('\n');
                        buffer = lines.pop() || '';
                        for (const line of lines) {
                            if (line.startsWith('data: ')) {
                                try {
                                    const event = JSON.parse(line.slice(6));
                                    if (event.type === 'chunk') {
                                        fullContent += event.content;
                                        setMessages((prev) =>
                                            prev.map((m) =>
                                                m.id === streamMsgId ? { ...m, content: fullContent } : m
                                            )
                                        );
                                    }
                                } catch {
                                    // skip invalid JSON
                                }
                            }
                        }
                    }
                }

                // Refresh session after streaming
                const updated = await getChatSession(currentSession.id);
                setActiveQASession(updated);
                await loadQASessions();
            } else {
                // Normal request for notes
                const response = await sendChatMessage(currentSession.id, userMsg.content);
                setMessages((prev) => [...prev, response]);

                const updated = await getChatSession(currentSession.id);
                setActiveNotesSession(updated);
                await loadNotesSessions();
            }
        } catch (e) {
            console.error(e);
            setMessages((prev) => [
                ...prev,
                {
                    id: `error-${Date.now()}`,
                    session_id: currentSession.id,
                    role: 'assistant',
                    content: 'Fehler bei der Verarbeitung. Bitte versuche es erneut.',
                    created_at: new Date().toISOString(),
                },
            ]);
        } finally {
            setLoading(false);
        }
    };

    const extractNoteData = (content: string) => {
        const match = content.match(/<!-- AI_NOTE_DATA\s*([\s\S]*?)\s*AI_NOTE_DATA -->/);
        if (match) {
            try {
                return JSON.parse(match[1]);
            } catch {
                return null;
            }
        }
        return null;
    };

    const handleSaveNote = async (content: string) => {
        const noteData = extractNoteData(content);
        if (!noteData) return;

        setSavingNote(content);
        try {
            const folder = await ensureFolderPath(noteData.folder);
            await createNote(noteData.title, noteData.content, folder.id, noteData.tag_ids);
            await loadFolderTree();
            setSavedNotes((prev) => new Set(prev).add(content));
            setDismissedNotes((prev) => new Set(prev).add(content));
        } catch (e) {
            console.error(e);
        } finally {
            setSavingNote(null);
        }
    };

    const handleDismissNote = (content: string) => {
        setDismissedNotes((prev) => new Set(prev).add(content));
    };

    const handleRefine = async (msgContent: string) => {
        if (!refineInput.trim() || refining || !session) return;
        setRefining(true);

        // Send a follow-up message asking to improve the note
        const refinementPrompt = `Bitte überarbeite den letzten Notiz-Vorschlag basierend auf diesem Feedback: ${refineInput}`;

        try {
            const response = await sendChatMessage(session.id, refinementPrompt);
            // Add user refinement message + AI response
            setMessages((prev) => [
                ...prev,
                {
                    id: `refine-user-${Date.now()}`,
                    session_id: session.id,
                    role: 'user',
                    content: `Nachbesserung: ${refineInput}`,
                    created_at: new Date().toISOString(),
                },
                response,
            ]);

            // Dismiss old suggestion, new one will have buttons
            setDismissedNotes((prev) => new Set(prev).add(msgContent));
            setRefineMessageId(null);
            setRefineInput('');

            const updated = await getChatSession(session.id);
            setActiveNotesSession(updated);
            await loadNotesSessions();
        } catch (e) {
            console.error(e);
        } finally {
            setRefining(false);
        }
    };

    const cleanMessageContent = (content: string) => {
        return content.replace(/<!-- AI_NOTE_DATA[\s\S]*?AI_NOTE_DATA -->/g, '').trim();
    };

    return (
        <div className="h-full flex flex-col">
            {/* Messages */}
            <div className="flex-1 overflow-y-auto p-4 space-y-4">
                {messages.length === 0 && (
                    <div className="h-full flex items-center justify-center">
                        <div className="text-center">
                            <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-dark-800 mb-4">
                                <LuBrain className={`w-8 h-8 ${type === 'notes' ? 'text-brain-400' : 'text-green-400'}`} />
                            </div>
                            <h3 className="text-lg font-semibold text-white mb-2">
                                {type === 'notes' ? 'Notizen-Assistent' : 'Fragen an dein Second Brain'}
                            </h3>
                            <p className="text-sm text-dark-500 max-w-sm">
                                {type === 'notes'
                                    ? 'Gib deine Notizen oder Informationen ein und ich strukturiere und speichere sie für dich.'
                                    : 'Stelle eine Frage und ich durchsuche dein Second Brain nach relevanten Antworten.'}
                            </p>
                        </div>
                    </div>
                )}

                {messages.map((msg) => (
                    <div
                        key={msg.id}
                        className={`chat-message flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                    >
                        <div
                            className={`max-w-[85%] rounded-2xl px-4 py-3 ${msg.role === 'user'
                                ? 'bg-brain-800 text-white'
                                : 'bg-dark-800 border border-dark-700'
                                }`}
                        >
                            <div className="markdown-content text-sm">
                                <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                                    {cleanMessageContent(msg.content)}
                                </ReactMarkdown>
                            </div>

                            {/* Action buttons for assistant messages with note data */}
                            {msg.role === 'assistant' && type === 'notes' && extractNoteData(msg.content) && !dismissedNotes.has(msg.content) && (
                                <div className="mt-3 pt-3 border-t border-dark-600 space-y-2">
                                    <div className="flex gap-2">
                                        {/* Accept */}
                                        <button
                                            onClick={() => handleSaveNote(msg.content)}
                                            disabled={savingNote === msg.content}
                                            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-green-600 hover:bg-green-500 text-white rounded-lg transition-colors disabled:opacity-50"
                                        >
                                            <FiCheck className="w-3.5 h-3.5" />
                                            {savingNote === msg.content ? 'Speichert...' : 'Akzeptieren'}
                                        </button>

                                        {/* Refine */}
                                        <button
                                            onClick={() => {
                                                setRefineMessageId(refineMessageId === msg.id ? null : msg.id);
                                                setTimeout(() => refineInputRef.current?.focus(), 100);
                                            }}
                                            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${refineMessageId === msg.id
                                                ? 'bg-brain-600 text-white'
                                                : 'bg-brain-600/20 text-brain-400 hover:bg-brain-600/30'
                                                }`}
                                        >
                                            <FiRefreshCw className="w-3.5 h-3.5" />
                                            Nachbessern
                                        </button>

                                        {/* Dismiss */}
                                        <button
                                            onClick={() => handleDismissNote(msg.content)}
                                            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-red-600/10 text-red-400 hover:bg-red-600/20 rounded-lg transition-colors"
                                        >
                                            <FiX className="w-3.5 h-3.5" />
                                            Ablehnen
                                        </button>
                                    </div>

                                    {/* Refine chat input */}
                                    {refineMessageId === msg.id && (
                                        <div className="flex gap-2 items-center bg-dark-900 rounded-lg p-2 border border-dark-600">
                                            <FiMessageSquare className="w-4 h-4 text-brain-400 flex-shrink-0" />
                                            <input
                                                ref={refineInputRef}
                                                type="text"
                                                value={refineInput}
                                                onChange={(e) => setRefineInput(e.target.value)}
                                                onKeyDown={(e) => {
                                                    if (e.key === 'Enter') handleRefine(msg.content);
                                                    if (e.key === 'Escape') { setRefineMessageId(null); setRefineInput(''); }
                                                }}
                                                placeholder="Was soll geändert werden? z.B. 'Mehr Details zu Kapitel 2'"
                                                className="flex-1 px-2 py-1 text-xs bg-transparent text-white placeholder-dark-600 focus:outline-none"
                                                autoFocus
                                            />
                                            <button
                                                onClick={() => handleRefine(msg.content)}
                                                disabled={!refineInput.trim() || refining}
                                                className="p-1.5 bg-brain-600 hover:bg-brain-500 text-white rounded-md transition-colors disabled:opacity-50"
                                            >
                                                {refining ? (
                                                    <div className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                                                ) : (
                                                    <FiSend className="w-3.5 h-3.5" />
                                                )}
                                            </button>
                                        </div>
                                    )}
                                </div>
                            )}

                            {/* Show "saved" badge for dismissed/saved notes */}
                            {msg.role === 'assistant' && type === 'notes' && extractNoteData(msg.content) && dismissedNotes.has(msg.content) && (
                                <div className="mt-3 pt-3 border-t border-dark-600">
                                    {savedNotes.has(msg.content) ? (
                                        <span className="text-xs text-green-400 flex items-center gap-1">
                                            <FiCheck className="w-3 h-3" /> Gespeichert
                                        </span>
                                    ) : (
                                        <span className="text-xs text-dark-500 italic">Abgelehnt</span>
                                    )}
                                </div>
                            )}
                        </div>
                    </div>
                ))}

                {loading && (
                    <div className="flex justify-start">
                        <div className="bg-dark-800 border border-dark-700 rounded-2xl px-4 py-3">
                            <div className="flex items-center gap-2 text-sm text-dark-400">
                                <div className="flex gap-1">
                                    <div className="w-2 h-2 bg-brain-500 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                                    <div className="w-2 h-2 bg-brain-500 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                                    <div className="w-2 h-2 bg-brain-500 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                                </div>
                                Denkt nach...
                            </div>
                        </div>
                    </div>
                )}

                <div ref={messagesEndRef} />
            </div>

            {/* Input */}
            <div className="p-4 border-t border-dark-800">
                <div className="flex items-end gap-2">
                    <textarea
                        ref={textareaRef}
                        value={message}
                        onChange={(e) => {
                            setMessage(e.target.value);
                            adjustTextarea();
                        }}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter' && !e.shiftKey) {
                                e.preventDefault();
                                handleSend();
                            }
                        }}
                        placeholder={
                            type === 'notes'
                                ? 'Notiz hinzufügen... (z.B. "Zusammenfassung von Atomic Habits: Die Macht der Gewohnheiten...")'
                                : 'Frage stellen... (z.B. "Wie kann mir Atomic Habits helfen, ins Gym zu gehen?")'
                        }
                        className="flex-1 px-4 py-3 bg-dark-800 border border-dark-700 rounded-xl text-white text-sm placeholder-dark-600 focus:outline-none focus:border-brain-500 resize-none min-h-[80px] max-h-[200px]"
                        rows={3}
                    />
                    <button
                        onClick={handleSend}
                        disabled={!message.trim() || loading}
                        className={`p-3 rounded-xl transition-colors ${message.trim() && !loading
                            ? 'bg-brain-600 hover:bg-brain-500 text-white'
                            : 'bg-dark-800 text-dark-600 cursor-not-allowed'
                            }`}
                    >
                        <FiSend className="w-5 h-5" />
                    </button>
                </div>
            </div>
        </div>
    );
}
