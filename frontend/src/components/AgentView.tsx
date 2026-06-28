'use client';

import { useState, useRef, useEffect } from 'react';
import {
    FiSend, FiCheck, FiX, FiCheckCircle, FiCpu,
    FiChevronDown, FiChevronRight, FiZap, FiLoader,
    FiFilePlus, FiEdit3, FiTrash2, FiToggleLeft, FiToggleRight,
    FiPlus, FiMessageSquare, FiEdit2, FiImage, FiEye, FiColumns,
    FiXCircle,
} from 'react-icons/fi';
import ReactMarkdown from 'react-markdown';
import { markdownComponents, remarkPlugins, rehypePlugins } from '@/lib/markdownComponents';
import { runAgent, applyAgentProposals, createChatSession, getChatSession, deleteChatSession, updateChatSession, getNote } from '@/lib/api';
import { useStore } from '@/lib/store';
import type { AgentStep, AgentProposal, ChatMessage, ChatSessionDetail, Note } from '@/lib/types';

// ── Types ────────────────────────────────────────────────────────────

interface ParsedAgentMessage {
    id: string;
    role: 'user' | 'assistant';
    content: string;
    steps?: AgentStep[];
    proposals?: AgentProposal[];
    created_at: string;
}

type RightPanelMode = 'none' | 'note' | 'diff';

interface DiffViewData {
    proposal: AgentProposal;
    msgId: string;
    proposalIndex: number;
}

// ── Helpers ──────────────────────────────────────────────────────────

function parseAgentMessage(msg: ChatMessage): ParsedAgentMessage {
    let content = msg.content;
    let steps: AgentStep[] | undefined;
    let proposals: AgentProposal[] | undefined;

    const metaMatch = content.match(/<!-- AGENT_META\n([\s\S]*?)\nAGENT_META -->/);
    if (metaMatch) {
        content = content.replace(metaMatch[0], '').trim();
        try {
            const meta = JSON.parse(metaMatch[1]);
            steps = meta.steps;
            proposals = meta.proposals;
        } catch { /* ignore */ }
    }

    return { id: msg.id, role: msg.role, content, steps, proposals, created_at: msg.created_at };
}

// ── Main Component ───────────────────────────────────────────────────

export default function AgentView() {
    const { loadFolderTree, agentSessions, loadAgentSessions, activeAgentSession, setActiveAgentSession } = useStore();
    const [input, setInput] = useState('');
    const [loading, setLoading] = useState(false);
    const [autoAccept, setAutoAccept] = useState(false);
    const [parsedMessages, setParsedMessages] = useState<ParsedAgentMessage[]>([]);
    const [appliedProposals, setAppliedProposals] = useState<Set<string>>(new Set());
    const [rejectedProposals, setRejectedProposals] = useState<Set<string>>(new Set());
    const [expandedSteps, setExpandedSteps] = useState<Set<string>>(new Set());
    const [renamingSession, setRenamingSession] = useState<string | null>(null);
    const [renameValue, setRenameValue] = useState('');
    const [pendingImages, setPendingImages] = useState<File[]>([]);

    // Right panel state
    const [rightPanel, setRightPanel] = useState<RightPanelMode>('none');
    const [viewingNote, setViewingNote] = useState<Note | null>(null);
    const [diffData, setDiffData] = useState<DiffViewData | null>(null);

    const messagesEndRef = useRef<HTMLDivElement>(null);
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);

    useEffect(() => { loadAgentSessions(); }, [loadAgentSessions]);

    useEffect(() => {
        if (activeAgentSession) {
            setParsedMessages(activeAgentSession.messages.map(parseAgentMessage));
        } else {
            setParsedMessages([]);
        }
        setAppliedProposals(new Set());
        setRejectedProposals(new Set());
    }, [activeAgentSession]);

    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [parsedMessages, loading]);

    const adjustTextarea = () => {
        const ta = textareaRef.current;
        if (ta) { ta.style.height = 'auto'; ta.style.height = `${Math.min(ta.scrollHeight, 200)}px`; }
    };

    const handlePaste = (e: React.ClipboardEvent) => {
        const items = e.clipboardData?.items;
        if (!items) return;
        const imgs: File[] = [];
        for (let i = 0; i < items.length; i++) {
            if (items[i].type.startsWith('image/')) { const f = items[i].getAsFile(); if (f) imgs.push(f); }
        }
        if (imgs.length > 0) { e.preventDefault(); setPendingImages((p) => [...p, ...imgs]); }
    };

    const handleDrop = (e: React.DragEvent) => {
        e.preventDefault();
        const files = Array.from(e.dataTransfer.files).filter(f => f.type.startsWith('image/'));
        if (files.length > 0) setPendingImages((p) => [...p, ...files]);
    };

    // ── Session management ───────────────────────────────────────────

    const handleNewSession = async () => {
        try {
            const s = await createChatSession('agent', 'Neuer Agent-Chat');
            const detail = await getChatSession(s.id);
            setActiveAgentSession(detail);
            await loadAgentSessions();
        } catch (e) { console.error(e); }
    };

    const handleSelectSession = async (id: string) => {
        try { const d = await getChatSession(id); setActiveAgentSession(d); } catch (e) { console.error(e); }
    };

    const handleDeleteSession = async (e: React.MouseEvent, id: string) => {
        e.stopPropagation();
        try {
            await deleteChatSession(id);
            if (activeAgentSession?.id === id) setActiveAgentSession(null);
            await loadAgentSessions();
        } catch (e) { console.error(e); }
    };

    const handleRenameSession = async (id: string) => {
        if (!renameValue.trim()) { setRenamingSession(null); return; }
        try { await updateChatSession(id, renameValue.trim()); setRenamingSession(null); setRenameValue(''); await loadAgentSessions(); } catch (e) { console.error(e); }
    };

    // ── Send message ─────────────────────────────────────────────────

    const handleSend = async () => {
        if ((!input.trim() && pendingImages.length === 0) || loading) return;

        let session = activeAgentSession;
        if (!session) {
            try {
                const ns = await createChatSession('agent', input.slice(0, 50));
                session = await getChatSession(ns.id);
                setActiveAgentSession(session);
                await loadAgentSessions();
            } catch (e) { console.error(e); return; }
        }

        const currentInput = input;
        setInput('');
        setLoading(true);
        if (textareaRef.current) textareaRef.current.style.height = 'auto';

        const tempUser: ParsedAgentMessage = { id: `temp-${Date.now()}`, role: 'user', content: currentInput, created_at: new Date().toISOString() };
        setParsedMessages((p) => [...p, tempUser]);

        try {
            const result = await runAgent(session.id, currentInput, autoAccept, pendingImages.length > 0 ? pendingImages : undefined);
            setPendingImages([]);

            const assistantMsg: ParsedAgentMessage = {
                id: result.message.id, role: 'assistant', content: result.message.content,
                steps: result.steps, proposals: result.proposals, created_at: result.message.created_at,
            };
            setParsedMessages((p) => [...p, assistantMsg]);

            if (autoAccept && result.proposals?.length > 0) {
                const keys = result.proposals.map((_, i) => `${result.message.id}-${i}`);
                setAppliedProposals((p) => { const n = new Set(p); keys.forEach(k => n.add(k)); return n; });
                loadFolderTree();
            }
            await loadAgentSessions();
        } catch (e) {
            console.error(e);
            setParsedMessages((p) => [...p, { id: `err-${Date.now()}`, role: 'assistant', content: 'Fehler bei der Verarbeitung.', created_at: new Date().toISOString() }]);
        } finally { setLoading(false); }
    };

    // ── Proposal actions ─────────────────────────────────────────────

    const handleAcceptProposal = async (msgId: string, idx: number, proposal: AgentProposal) => {
        try {
            await applyAgentProposals([proposal]);
            setAppliedProposals((p) => { const n = new Set(p); n.add(`${msgId}-${idx}`); return n; });
            loadFolderTree();
            if (rightPanel === 'diff' && diffData?.msgId === msgId && diffData?.proposalIndex === idx) {
                setRightPanel('none'); setDiffData(null);
            }
        } catch (e) { console.error(e); }
    };

    const handleRejectProposal = (msgId: string, idx: number) => {
        setRejectedProposals((p) => { const n = new Set(p); n.add(`${msgId}-${idx}`); return n; });
        if (rightPanel === 'diff' && diffData?.msgId === msgId && diffData?.proposalIndex === idx) {
            setRightPanel('none'); setDiffData(null);
        }
    };

    const handleAcceptAll = async (msgId: string, proposals: AgentProposal[]) => {
        const pending = proposals.filter((_, i) => !appliedProposals.has(`${msgId}-${i}`) && !rejectedProposals.has(`${msgId}-${i}`));
        if (pending.length === 0) return;
        try {
            await applyAgentProposals(pending);
            const keys = proposals.map((_, i) => `${msgId}-${i}`).filter(k => !appliedProposals.has(k) && !rejectedProposals.has(k));
            setAppliedProposals((p) => { const n = new Set(p); keys.forEach(k => n.add(k)); return n; });
            loadFolderTree();
        } catch (e) { console.error(e); }
    };

    // ── Right panel actions ──────────────────────────────────────────

    const openNotePreview = async (noteId: string) => {
        try {
            const note = await getNote(noteId);
            setViewingNote(note);
            setRightPanel('note');
            setDiffData(null);
        } catch (e) { console.error(e); }
    };

    const openDiffView = (proposal: AgentProposal, msgId: string, idx: number) => {
        setDiffData({ proposal, msgId, proposalIndex: idx });
        setRightPanel('diff');
        setViewingNote(null);
    };

    const closeRightPanel = () => {
        setRightPanel('none');
        setViewingNote(null);
        setDiffData(null);
    };

    // ── Render ───────────────────────────────────────────────────────

    const showRightPanel = rightPanel !== 'none';

    return (
        <div className="h-full flex flex-col">
            {/* Header */}
            <div className="flex items-center justify-between px-4 sm:px-6 py-3 border-b border-dark-800 bg-dark-900/50">
                <div className="flex items-center gap-3">
                    <div className="p-2 bg-rose-600/20 rounded-xl">
                        <FiCpu className="w-5 h-5 text-rose-400" />
                    </div>
                    <div>
                        <h1 className="text-lg font-semibold text-white">Agent</h1>
                        <p className="text-xs text-dark-500">Brainstorme, plane & arbeite mit deinen Notizen</p>
                    </div>
                </div>
                <div className="flex items-center gap-2">
                    <button onClick={handleNewSession} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-dark-800 text-dark-400 border border-dark-700 hover:text-white transition-colors">
                        <FiPlus className="w-3.5 h-3.5" /> Neuer Chat
                    </button>
                    <button
                        onClick={() => setAutoAccept(!autoAccept)}
                        className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${autoAccept ? 'bg-green-600/20 text-green-400 border border-green-600/30' : 'bg-dark-800 text-dark-400 border border-dark-700 hover:text-white'}`}
                    >
                        {autoAccept ? <FiToggleRight className="w-4 h-4" /> : <FiToggleLeft className="w-4 h-4" />}
                        Auto
                    </button>
                </div>
            </div>

            {/* Main content area */}
            <div className="flex-1 flex overflow-hidden">
                {/* Sessions sidebar */}
                <div className="w-48 border-r border-dark-800 overflow-y-auto flex-shrink-0 hidden md:block">
                    <div className="p-2 space-y-0.5">
                        {agentSessions.map((s) => (
                            <div
                                key={s.id}
                                onClick={() => handleSelectSession(s.id)}
                                className={`group flex items-center gap-2 px-2.5 py-2 rounded-lg text-xs cursor-pointer transition-colors ${activeAgentSession?.id === s.id ? 'bg-rose-600/10 text-rose-400 border border-rose-600/20' : 'text-dark-400 hover:text-white hover:bg-dark-800'}`}
                            >
                                <FiMessageSquare className="w-3 h-3 flex-shrink-0" />
                                {renamingSession === s.id ? (
                                    <input type="text" value={renameValue} onChange={(e) => setRenameValue(e.target.value)}
                                        onKeyDown={(e) => { if (e.key === 'Enter') handleRenameSession(s.id); if (e.key === 'Escape') { setRenamingSession(null); setRenameValue(''); } }}
                                        onBlur={() => handleRenameSession(s.id)} onClick={(e) => e.stopPropagation()}
                                        className="flex-1 px-1 py-0 text-xs bg-dark-950 border border-rose-500 rounded text-white focus:outline-none min-w-0" autoFocus />
                                ) : (
                                    <span className="truncate flex-1">{s.title}</span>
                                )}
                                <div className="opacity-0 group-hover:opacity-100 flex gap-0.5">
                                    <button onClick={(e) => { e.stopPropagation(); setRenamingSession(s.id); setRenameValue(s.title); }} className="p-0.5 hover:bg-dark-700 rounded">
                                        <FiEdit2 className="w-2.5 h-2.5 text-dark-500 hover:text-blue-400" />
                                    </button>
                                    <button onClick={(e) => handleDeleteSession(e, s.id)} className="p-0.5 hover:bg-dark-700 rounded">
                                        <FiTrash2 className="w-2.5 h-2.5 text-dark-500 hover:text-red-400" />
                                    </button>
                                </div>
                            </div>
                        ))}
                        {agentSessions.length === 0 && <p className="text-xs text-dark-600 px-2 py-4 text-center">Noch keine Chats</p>}
                    </div>
                </div>

                {/* Chat + Right Panel Split */}
                <div className="flex-1 flex overflow-hidden">
                    {/* LEFT: Chat area */}
                    <div className={`flex flex-col overflow-hidden transition-all duration-200 ${showRightPanel ? 'w-1/2' : 'flex-1'}`}>
                        <div className="flex-1 overflow-y-auto p-4 space-y-4">
                            {parsedMessages.length === 0 && !loading && (
                                <EmptyState setInput={setInput} />
                            )}

                            {parsedMessages.map((msg) => (
                                <MessageBubble
                                    key={msg.id}
                                    msg={msg}
                                    expandedSteps={expandedSteps}
                                    setExpandedSteps={setExpandedSteps}
                                    appliedProposals={appliedProposals}
                                    rejectedProposals={rejectedProposals}
                                    autoAccept={autoAccept}
                                    onAcceptProposal={handleAcceptProposal}
                                    onRejectProposal={handleRejectProposal}
                                    onAcceptAll={handleAcceptAll}
                                    onOpenDiff={openDiffView}
                                    onOpenNote={openNotePreview}
                                />
                            ))}

                            {loading && <ThinkingIndicator />}
                            <div ref={messagesEndRef} />
                        </div>

                        {/* Input area */}
                        <div className="p-3 border-t border-dark-800">
                            {pendingImages.length > 0 && (
                                <div className="flex gap-2 mb-2 flex-wrap">
                                    {pendingImages.map((img, i) => (
                                        <div key={i} className="relative group">
                                            <img src={URL.createObjectURL(img)} alt="" className="w-12 h-12 object-cover rounded-lg border border-dark-700" />
                                            <button onClick={() => setPendingImages((p) => p.filter((_, j) => j !== i))} className="absolute -top-1 -right-1 w-4 h-4 bg-red-600 text-white rounded-full flex items-center justify-center text-[10px] opacity-0 group-hover:opacity-100">×</button>
                                        </div>
                                    ))}
                                </div>
                            )}
                            <div className="flex items-end gap-2" onDrop={handleDrop} onDragOver={(e) => e.preventDefault()}>
                                <textarea
                                    ref={textareaRef} value={input}
                                    onChange={(e) => { setInput(e.target.value); adjustTextarea(); }}
                                    onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
                                    onPaste={handlePaste}
                                    placeholder="Schreib dem Agent..."
                                    className="flex-1 px-3 py-2.5 bg-dark-800 border border-dark-700 rounded-xl text-white text-sm placeholder-dark-600 focus:outline-none focus:border-rose-500 resize-none min-h-[42px] max-h-[160px]"
                                    rows={1}
                                />
                                <input ref={fileInputRef} type="file" accept="image/*" multiple className="hidden"
                                    onChange={(e) => { const f = Array.from(e.target.files || []); if (f.length) setPendingImages((p) => [...p, ...f]); e.target.value = ''; }} />
                                <button onClick={() => fileInputRef.current?.click()} className="p-2.5 rounded-xl bg-dark-800 border border-dark-700 text-dark-400 hover:text-white transition-colors">
                                    <FiImage className="w-4 h-4" />
                                </button>
                                <button onClick={handleSend} disabled={(!input.trim() && pendingImages.length === 0) || loading}
                                    className={`p-2.5 rounded-xl transition-colors ${(input.trim() || pendingImages.length > 0) && !loading ? 'bg-rose-600 hover:bg-rose-500 text-white' : 'bg-dark-800 text-dark-600 cursor-not-allowed'}`}>
                                    <FiSend className="w-4 h-4" />
                                </button>
                            </div>
                        </div>
                    </div>

                    {/* RIGHT: Note Preview / Diff Manager */}
                    {showRightPanel && (
                        <div className="w-1/2 border-l border-dark-800 flex flex-col overflow-hidden bg-dark-900/50">
                            {/* Right panel header */}
                            <div className="flex items-center justify-between px-4 py-3 border-b border-dark-800">
                                <div className="flex items-center gap-2 min-w-0">
                                    {rightPanel === 'note' && viewingNote && (
                                        <>
                                            <FiEye className="w-4 h-4 text-brain-400 flex-shrink-0" />
                                            <span className="text-sm font-medium text-white truncate">{viewingNote.title}</span>
                                        </>
                                    )}
                                    {rightPanel === 'diff' && diffData && (
                                        <>
                                            <FiColumns className="w-4 h-4 text-amber-400 flex-shrink-0" />
                                            <span className="text-sm font-medium text-white truncate">
                                                {diffData.proposal.type === 'create' ? 'Neue Notiz' : diffData.proposal.type === 'update' ? 'Änderungen' : 'Löschen'}
                                                {diffData.proposal.title && `: ${diffData.proposal.title}`}
                                            </span>
                                        </>
                                    )}
                                </div>
                                <button onClick={closeRightPanel} className="p-1.5 hover:bg-dark-800 rounded-lg text-dark-400 hover:text-white">
                                    <FiX className="w-4 h-4" />
                                </button>
                            </div>

                            {/* Right panel content */}
                            <div className="flex-1 overflow-y-auto">
                                {rightPanel === 'note' && viewingNote && (
                                    <div className="p-4">
                                        <div className="text-xs text-dark-500 mb-3 flex items-center gap-2">
                                            <span>📁 {viewingNote.folder_path}</span>
                                            {viewingNote.tags?.length > 0 && (
                                                <span>· {viewingNote.tags.map(t => t.name).join(', ')}</span>
                                            )}
                                        </div>
                                        <div className="markdown-content text-sm">
                                            <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins} components={markdownComponents}>
                                                {viewingNote.content}
                                            </ReactMarkdown>
                                        </div>
                                    </div>
                                )}

                                {rightPanel === 'diff' && diffData && (
                                    <DiffPanel
                                        data={diffData}
                                        isApplied={appliedProposals.has(`${diffData.msgId}-${diffData.proposalIndex}`)}
                                        isRejected={rejectedProposals.has(`${diffData.msgId}-${diffData.proposalIndex}`)}
                                        onAccept={() => handleAcceptProposal(diffData.msgId, diffData.proposalIndex, diffData.proposal)}
                                        onReject={() => handleRejectProposal(diffData.msgId, diffData.proposalIndex)}
                                    />
                                )}
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}

// ── Sub-components ───────────────────────────────────────────────────

function EmptyState({ setInput }: { setInput: (s: string) => void }) {
    return (
        <div className="h-full flex items-center justify-center">
            <div className="text-center max-w-md">
                <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-dark-800 mb-4">
                    <FiCpu className="w-8 h-8 text-rose-400/60" />
                </div>
                <h3 className="text-lg font-semibold text-white mb-2">Agentic Workspace</h3>
                <p className="text-sm text-dark-500 mb-4">
                    Brainstorme, plane und arbeite mit deinen Notizen. Bilder werden automatisch analysiert und abgelegt.
                </p>
                <div className="grid grid-cols-1 gap-2 text-left">
                    {['Lass uns eine Wohnungsplanung machen', 'Was habe ich zum Thema X notiert?', 'Hilf mir ein Projekt zu strukturieren', 'Finde Duplikate in meinen Notizen'].map((t) => (
                        <button key={t} onClick={() => setInput(t)} className="text-xs text-left px-3 py-2 bg-dark-800/50 border border-dark-700 rounded-lg text-dark-400 hover:text-white hover:border-rose-600/30 transition-colors">
                            💡 {t}
                        </button>
                    ))}
                </div>
            </div>
        </div>
    );
}

function ThinkingIndicator() {
    const [dots, setDots] = useState('');
    useEffect(() => { const i = setInterval(() => setDots((d) => d.length >= 3 ? '' : d + '.'), 500); return () => clearInterval(i); }, []);
    return (
        <div className="flex justify-start">
            <div className="bg-dark-800/50 border border-dark-700 rounded-2xl px-4 py-3">
                <div className="flex items-center gap-3 text-sm">
                    <div className="relative w-4 h-4">
                        <div className="absolute inset-0 bg-rose-400 rounded-full animate-ping opacity-30" />
                        <div className="absolute inset-0.5 bg-rose-500 rounded-full" />
                    </div>
                    <span className="text-dark-300">Lese Notizen, plane und formuliere{dots}</span>
                </div>
            </div>
        </div>
    );
}

function MessageBubble({ msg, expandedSteps, setExpandedSteps, appliedProposals, rejectedProposals, autoAccept, onAcceptProposal, onRejectProposal, onAcceptAll, onOpenDiff, onOpenNote }: {
    msg: ParsedAgentMessage;
    expandedSteps: Set<string>; setExpandedSteps: React.Dispatch<React.SetStateAction<Set<string>>>;
    appliedProposals: Set<string>; rejectedProposals: Set<string>; autoAccept: boolean;
    onAcceptProposal: (msgId: string, idx: number, p: AgentProposal) => void;
    onRejectProposal: (msgId: string, idx: number) => void;
    onAcceptAll: (msgId: string, proposals: AgentProposal[]) => void;
    onOpenDiff: (p: AgentProposal, msgId: string, idx: number) => void;
    onOpenNote: (noteId: string) => void;
}) {
    if (msg.role === 'user') {
        return (
            <div className="flex justify-end">
                <div className="max-w-[80%] bg-rose-900/30 border border-rose-800/30 rounded-2xl px-4 py-3">
                    <p className="text-sm text-white whitespace-pre-wrap">{msg.content}</p>
                </div>
            </div>
        );
    }

    return (
        <div className="flex justify-start">
            <div className="max-w-[90%] space-y-2">
                {/* Steps */}
                {msg.steps && msg.steps.length > 0 && (
                    <div className="bg-dark-800/30 border border-dark-700/50 rounded-xl overflow-hidden">
                        <button onClick={() => setExpandedSteps((p) => { const n = new Set(p); n.has(msg.id) ? n.delete(msg.id) : n.add(msg.id); return n; })}
                            className="flex items-center gap-2 w-full px-3 py-2 text-xs text-dark-400 hover:text-white">
                            {expandedSteps.has(msg.id) ? <FiChevronDown className="w-3 h-3" /> : <FiChevronRight className="w-3 h-3" />}
                            <FiZap className="w-3 h-3 text-amber-400" /> {msg.steps.length} Schritte
                        </button>
                        {expandedSteps.has(msg.id) && (
                            <div className="px-3 pb-2 space-y-1">
                                {msg.steps.map((s, i) => (
                                    <div key={i} className="flex items-start gap-2 text-xs text-dark-400">
                                        <span>{s.type === 'tool_call' ? '🔧' : s.type === 'tool_result' ? '✅' : '🧠'}</span>
                                        <span>{s.content}</span>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                )}

                {/* Response */}
                {msg.content && (
                    <div className="bg-dark-800/50 border border-dark-700 rounded-2xl px-4 py-3">
                        <div className="markdown-content text-sm text-dark-200">
                            <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins} components={markdownComponents}>
                                {msg.content}
                            </ReactMarkdown>
                        </div>
                    </div>
                )}

                {/* Proposals */}
                {msg.proposals && msg.proposals.length > 0 && (
                    <div className="space-y-1.5">
                        <div className="flex items-center justify-between px-1">
                            <span className="text-xs font-medium text-dark-400">{msg.proposals.length} Vorschläge</span>
                            <button onClick={() => onAcceptAll(msg.id, msg.proposals!)}
                                className="flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-green-600 hover:bg-green-500 text-white rounded-lg">
                                <FiCheckCircle className="w-3 h-3" /> Alle
                            </button>
                        </div>
                        {msg.proposals.map((p, i) => (
                            <ProposalCard key={i} proposal={p} msgId={msg.id} index={i}
                                isApplied={appliedProposals.has(`${msg.id}-${i}`)}
                                isRejected={rejectedProposals.has(`${msg.id}-${i}`)}
                                onAccept={() => onAcceptProposal(msg.id, i, p)}
                                onReject={() => onRejectProposal(msg.id, i)}
                                onOpenDiff={() => onOpenDiff(p, msg.id, i)}
                                onOpenNote={p.note_id ? () => onOpenNote(p.note_id!) : undefined}
                            />
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}

function ProposalCard({ proposal, msgId, index, isApplied, isRejected, onAccept, onReject, onOpenDiff, onOpenNote }: {
    proposal: AgentProposal; msgId: string; index: number;
    isApplied: boolean; isRejected: boolean;
    onAccept: () => void; onReject: () => void;
    onOpenDiff: () => void; onOpenNote?: () => void;
}) {
    const typeConfig = {
        create: { icon: FiFilePlus, label: 'Neu', color: 'text-green-400', bg: 'bg-green-600/10 border-green-600/20' },
        update: { icon: FiEdit3, label: 'Edit', color: 'text-blue-400', bg: 'bg-blue-600/10 border-blue-600/20' },
        delete: { icon: FiTrash2, label: 'Del', color: 'text-red-400', bg: 'bg-red-600/10 border-red-600/20' },
    };
    const config = typeConfig[proposal.type];
    const Icon = config.icon;

    return (
        <div className={`border rounded-xl overflow-hidden ${isApplied ? 'border-green-600/30 bg-green-900/10' : isRejected ? 'border-dark-700 opacity-40' : config.bg}`}>
            <div className="flex items-center gap-2 px-3 py-2">
                <Icon className={`w-3.5 h-3.5 flex-shrink-0 ${config.color}`} />
                <div className="flex-1 min-w-0">
                    <span className="text-xs font-medium text-white truncate block">{proposal.title || proposal.new_title || proposal.note_id?.slice(0, 8) || ''}</span>
                    {proposal.folder_path && <span className="text-[10px] text-dark-500">📁 {proposal.folder_path}</span>}
                </div>
                <div className="flex items-center gap-1 flex-shrink-0">
                    {/* View in right panel */}
                    <button onClick={onOpenDiff} className="p-1 hover:bg-dark-700 rounded text-dark-400 hover:text-amber-400" title="Im Diff-Panel öffnen">
                        <FiColumns className="w-3.5 h-3.5" />
                    </button>
                    {onOpenNote && (
                        <button onClick={onOpenNote} className="p-1 hover:bg-dark-700 rounded text-dark-400 hover:text-brain-400" title="Aktuelle Notiz anzeigen">
                            <FiEye className="w-3.5 h-3.5" />
                        </button>
                    )}
                    {isApplied ? (
                        <span className="text-xs text-green-400">✓</span>
                    ) : isRejected ? (
                        <span className="text-xs text-dark-500">—</span>
                    ) : (
                        <>
                            <button onClick={onAccept} className="p-1 bg-green-600 hover:bg-green-500 text-white rounded"><FiCheck className="w-3 h-3" /></button>
                            <button onClick={onReject} className="p-1 bg-red-600/20 hover:bg-red-600/40 text-red-400 rounded"><FiX className="w-3 h-3" /></button>
                        </>
                    )}
                </div>
            </div>
        </div>
    );
}

function DiffPanel({ data, isApplied, isRejected, onAccept, onReject }: {
    data: DiffViewData; isApplied: boolean; isRejected: boolean; onAccept: () => void; onReject: () => void;
}) {
    const { proposal } = data;

    return (
        <div className="flex flex-col h-full">
            {/* Diff header info */}
            <div className="px-4 py-3 border-b border-dark-800 space-y-2">
                <div className="flex items-center gap-2">
                    <span className={`text-xs font-medium px-2 py-0.5 rounded ${proposal.type === 'create' ? 'bg-green-600/20 text-green-400' : proposal.type === 'update' ? 'bg-blue-600/20 text-blue-400' : 'bg-red-600/20 text-red-400'}`}>
                        {proposal.type === 'create' ? 'ERSTELLEN' : proposal.type === 'update' ? 'BEARBEITEN' : 'LÖSCHEN'}
                    </span>
                    {proposal.folder_path && <span className="text-xs text-dark-500">📁 {proposal.folder_path}</span>}
                </div>
                {proposal.reason && <p className="text-xs text-dark-400 italic">{proposal.reason}</p>}
                {proposal.tags && proposal.tags.length > 0 && (
                    <div className="flex gap-1 flex-wrap">
                        {proposal.tags.map((t) => <span key={t} className="px-1.5 py-0.5 text-[10px] bg-dark-700 text-dark-300 rounded-full">{t}</span>)}
                    </div>
                )}
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto p-4">
                {proposal.type === 'create' && proposal.content && (
                    <div className="border border-green-600/20 rounded-xl p-4 bg-green-900/5">
                        <div className="text-xs text-green-400 font-medium mb-2">+ Neuer Inhalt</div>
                        <div className="markdown-content text-sm text-dark-200">
                            <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins} components={markdownComponents}>
                                {proposal.content}
                            </ReactMarkdown>
                        </div>
                    </div>
                )}

                {proposal.type === 'update' && proposal.new_content && (
                    <div className="border border-blue-600/20 rounded-xl p-4 bg-blue-900/5">
                        <div className="text-xs text-blue-400 font-medium mb-2">~ Geänderter Inhalt</div>
                        <div className="markdown-content text-sm text-dark-200">
                            <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins} components={markdownComponents}>
                                {proposal.new_content}
                            </ReactMarkdown>
                        </div>
                    </div>
                )}

                {proposal.type === 'delete' && (
                    <div className="border border-red-600/20 rounded-xl p-4 bg-red-900/5">
                        <div className="text-xs text-red-400 font-medium mb-2">— Wird gelöscht</div>
                        <p className="text-sm text-dark-400">Diese Notiz wird unwiderruflich gelöscht.</p>
                    </div>
                )}
            </div>

            {/* Actions footer */}
            {!isApplied && !isRejected && (
                <div className="px-4 py-3 border-t border-dark-800 flex gap-2">
                    <button onClick={onAccept} className="flex-1 flex items-center justify-center gap-2 py-2 bg-green-600 hover:bg-green-500 text-white text-sm font-medium rounded-xl transition-colors">
                        <FiCheck className="w-4 h-4" /> Annehmen
                    </button>
                    <button onClick={onReject} className="flex-1 flex items-center justify-center gap-2 py-2 bg-dark-800 hover:bg-dark-700 text-dark-300 text-sm font-medium rounded-xl border border-dark-700 transition-colors">
                        <FiX className="w-4 h-4" /> Ablehnen
                    </button>
                </div>
            )}
            {isApplied && (
                <div className="px-4 py-3 border-t border-dark-800 text-center">
                    <span className="text-sm text-green-400 flex items-center justify-center gap-2"><FiCheckCircle className="w-4 h-4" /> Angewendet</span>
                </div>
            )}
            {isRejected && (
                <div className="px-4 py-3 border-t border-dark-800 text-center">
                    <span className="text-sm text-dark-500">Abgelehnt</span>
                </div>
            )}
        </div>
    );
}
