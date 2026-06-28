'use client';

import { useState, useRef, useEffect, memo, useCallback, type RefObject, type ClipboardEvent as RClipboardEvent, type DragEvent as RDragEvent, type SetStateAction, type Dispatch } from 'react';
import {
    FiSend, FiCheck, FiX, FiCheckCircle, FiCpu,
    FiChevronDown, FiChevronRight, FiZap, FiLoader,
    FiFilePlus, FiEdit3, FiTrash2, FiToggleLeft, FiToggleRight,
    FiEdit2, FiImage, FiEye, FiColumns,
    FiFile,
} from 'react-icons/fi';
import ReactMarkdown from 'react-markdown';
import { markdownComponents, remarkPlugins, rehypePlugins } from '@/lib/markdownComponents';
import { runAgentStream, applyAgentProposals, markProposalsApplied, createChatSession, getChatSession, getNote } from '@/lib/api';
import type { AgentStreamEvent } from '@/lib/api';
import { useStore } from '@/lib/store';
import type { AgentStep, AgentProposal, ChatMessage, ChatSessionDetail, Note } from '@/lib/types';

// ── Types ────────────────────────────────────────────────────────────

interface ParsedAgentMessage {
    id: string;
    role: 'user' | 'assistant';
    content: string;
    steps?: AgentStep[];
    proposals?: AgentProposal[];
    appliedIndices?: number[];
    attachments?: { name: string; type: string; url?: string }[];
    created_at: string;
}

interface DiffViewData {
    proposal: AgentProposal;
    msgId: string;
    proposalIndex: number;
}

function parseAgentMessage(msg: ChatMessage): ParsedAgentMessage {
    let content = msg.content;
    let steps: AgentStep[] | undefined;
    let proposals: AgentProposal[] | undefined;
    let appliedIndices: number[] | undefined;
    const metaMatch = content.match(/<!-- AGENT_META\n([\s\S]*?)\nAGENT_META -->/);
    if (metaMatch) {
        content = content.replace(metaMatch[0], '').trim();
        try {
            const meta = JSON.parse(metaMatch[1]);
            steps = meta.steps;
            proposals = meta.proposals;
            appliedIndices = meta.applied_indices;
        } catch { }
    }
    return { id: msg.id, role: msg.role, content, steps, proposals, appliedIndices, created_at: msg.created_at };
}

// ── Main Component ───────────────────────────────────────────────────

export default function AgentView() {
    const { loadFolderTree, loadAgentSessions, activeAgentSession, setActiveAgentSession, agentViewingNote, setAgentViewingNote } = useStore();
    const [loading, setLoading] = useState(false);
    const [autoAccept, setAutoAccept] = useState(true);
    const [parsedMessages, setParsedMessages] = useState<ParsedAgentMessage[]>([]);
    const [streamingThought, setStreamingThought] = useState('');
    const [streamingContent, setStreamingContent] = useState('');
    const [streamingSteps, setStreamingSteps] = useState<AgentStep[]>([]);
    const [appliedProposals, setAppliedProposals] = useState(new Set<string>());
    const [rejectedProposals, setRejectedProposals] = useState(new Set<string>());
    const [expandedSteps, setExpandedSteps] = useState(new Set<string>());
    const [pendingFiles, setPendingFiles] = useState<File[]>([]);

    // Left panel: note viewer
    const [diffData, setDiffData] = useState<DiffViewData | null>(null);
    const [leftMode, setLeftMode] = useState<'note' | 'diff'>('note');

    const messagesEndRef = useRef<HTMLDivElement>(null);
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);

    useEffect(() => { loadAgentSessions(); loadFolderTree(); }, [loadAgentSessions, loadFolderTree]);

    // When a note is opened from the sidebar explorer, switch to note view
    useEffect(() => {
        if (agentViewingNote) {
            setLeftMode('note');
        }
    }, [agentViewingNote]);

    useEffect(() => {
        if (activeAgentSession) {
            const parsed = activeAgentSession.messages.map(parseAgentMessage);
            setParsedMessages(parsed);
            // Restore applied state from persisted metadata
            const restored = new Set<string>();
            for (const msg of parsed) {
                if (msg.appliedIndices) {
                    for (const idx of msg.appliedIndices) {
                        restored.add(`${msg.id}-${idx}`);
                    }
                }
            }
            setAppliedProposals(restored);
        } else {
            setParsedMessages([]);
            setAppliedProposals(new Set());
        }
        setRejectedProposals(new Set());
    }, [activeAgentSession]);

    useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [parsedMessages, loading]);

    const adjustTextarea = () => { const ta = textareaRef.current; if (ta) { ta.style.height = 'auto'; ta.style.height = `${Math.min(ta.scrollHeight, 200)}px`; } };

    const handlePaste = (e: RClipboardEvent) => {
        const items = e.clipboardData?.items; if (!items) return;
        const imgs: File[] = [];
        for (let i = 0; i < items.length; i++) { if (items[i].type.startsWith('image/')) { const f = items[i].getAsFile(); if (f) imgs.push(f); } }
        if (imgs.length > 0) { e.preventDefault(); setPendingFiles((p) => [...p, ...imgs]); }
    };

    // Fullscreen drag & drop
    const [isDragging, setIsDragging] = useState(false);
    const dragCounter = useRef(0);

    const handleDragEnter = (e: RDragEvent) => { e.preventDefault(); dragCounter.current++; setIsDragging(true); };
    const handleDragLeave = (e: RDragEvent) => { e.preventDefault(); dragCounter.current--; if (dragCounter.current === 0) setIsDragging(false); };
    const handleDragOver = (e: RDragEvent) => { e.preventDefault(); };
    const handleDrop = (e: RDragEvent) => {
        e.preventDefault();
        setIsDragging(false);
        dragCounter.current = 0;
        const files = Array.from(e.dataTransfer.files);
        if (files.length > 0) setPendingFiles((p) => [...p, ...files]);
    };

    // ── Send message ─────────────────────────────────────────────

    const handleSend = async () => {
        const inputVal = textareaRef.current?.value?.trim() || '';
        if ((!inputVal && pendingFiles.length === 0) || loading) return;
        let session = activeAgentSession;
        if (!session) { try { const ns = await createChatSession('agent', inputVal.slice(0, 50)); session = await getChatSession(ns.id); setActiveAgentSession(session); await loadAgentSessions(); } catch (e) { console.error(e); return; } }

        const currentInput = inputVal;
        const currentFiles = [...pendingFiles];
        setPendingFiles([]);
        if (textareaRef.current) { textareaRef.current.value = ''; textareaRef.current.style.height = 'auto'; }
        setLoading(true);

        // Build attachments preview for the user message
        const attachments = currentFiles.map(f => ({
            name: f.name,
            type: f.type.startsWith('image/') ? 'image' : 'document',
            url: f.type.startsWith('image/') ? URL.createObjectURL(f) : undefined,
        }));

        setParsedMessages((p) => [...p, { id: `temp-${Date.now()}`, role: 'user', content: currentInput, attachments: attachments.length > 0 ? attachments : undefined, created_at: new Date().toISOString() }]);
        setStreamingThought('');
        setStreamingContent('');
        setStreamingSteps([]);

        try {
            const msgId = `stream-${Date.now()}`;
            let fullContent = '';
            let fullThought = '';
            const allSteps: AgentStep[] = [];
            const allProposals: AgentProposal[] = [];

            await runAgentStream(
                session.id,
                currentInput,
                autoAccept,
                currentFiles.length > 0 ? currentFiles : undefined,
                (event: AgentStreamEvent) => {
                    switch (event.type) {
                        case 'thinking':
                            fullThought += event.content;
                            setStreamingThought(fullThought);
                            break;
                        case 'chunk':
                            fullContent += event.content;
                            setStreamingContent(fullContent);
                            break;
                        case 'tool_call':
                            allSteps.push({ type: 'tool_call', content: event.content });
                            setStreamingSteps([...allSteps]);
                            break;
                        case 'tool_result':
                            allSteps.push({ type: 'tool_result', content: event.content });
                            setStreamingSteps([...allSteps]);
                            break;
                        case 'proposal':
                            allProposals.push(event.proposal);
                            break;
                        case 'done':
                            // Final event — finalize the message
                            break;
                    }
                },
            );

            setStreamingThought('');
            setStreamingContent('');
            setStreamingSteps([]);

            // Add the final message to the list
            setParsedMessages((p) => [...p, {
                id: msgId,
                role: 'assistant',
                content: fullContent,
                steps: allSteps.length > 0 ? allSteps : undefined,
                proposals: allProposals.length > 0 ? allProposals : undefined,
                created_at: new Date().toISOString(),
            }]);

            if (autoAccept && allProposals.length > 0) {
                const keys = allProposals.map((_, i) => `${msgId}-${i}`);
                setAppliedProposals((p) => { const n = new Set(p); keys.forEach(k => n.add(k)); return n; });
            }
            loadFolderTree(); await loadAgentSessions();
        } catch (e) {
            console.error(e);
            setStreamingThought('');
            setStreamingContent('');
            setStreamingSteps([]);
            setParsedMessages((p) => [...p, { id: `err-${Date.now()}`, role: 'assistant', content: 'Fehler bei der Verarbeitung.', created_at: new Date().toISOString() }]);
        } finally { setLoading(false); }
    };

    // ── Proposal actions (memoized to prevent re-renders) ──────

    const handleAcceptProposal = useCallback(async (msgId: string, idx: number, proposal: AgentProposal) => {
        try {
            await applyAgentProposals([proposal]);
            setAppliedProposals((p) => { const n = new Set(p); n.add(`${msgId}-${idx}`); return n; });
            markProposalsApplied(msgId, [idx]).catch(() => { });
            loadFolderTree();
        } catch (e) { console.error(e); }
    }, [loadFolderTree]);

    const handleRejectProposal = useCallback((msgId: string, idx: number) => {
        setRejectedProposals((p) => { const n = new Set(p); n.add(`${msgId}-${idx}`); return n; });
    }, []);

    const handleAcceptAll = useCallback(async (msgId: string, proposals: AgentProposal[]) => {
        const pendingIndices = proposals.map((_, i) => i).filter(i => !appliedProposals.has(`${msgId}-${i}`));
        if (pendingIndices.length === 0) return;
        const pending = pendingIndices.map(i => proposals[i]);
        try {
            await applyAgentProposals(pending);
            setAppliedProposals((prev) => {
                const n = new Set(prev);
                pendingIndices.forEach(i => n.add(`${msgId}-${i}`));
                return n;
            });
            markProposalsApplied(msgId, pendingIndices).catch(() => { });
            loadFolderTree();
        } catch (e) { console.error(e); }
    }, [appliedProposals, loadFolderTree]);

    // ── Left panel actions ───────────────────────────────────────

    const openNoteInLeft = useCallback(async (noteId: string) => {
        try { const note = await getNote(noteId); setAgentViewingNote(note); setLeftMode('note'); setDiffData(null); } catch (e) { console.error(e); }
    }, [setAgentViewingNote]);

    const openDiffInLeft = useCallback((proposal: AgentProposal, msgId: string, idx: number) => {
        setDiffData({ proposal, msgId, proposalIndex: idx }); setLeftMode('diff');
    }, []);

    // ── Render ───────────────────────────────────────────────────

    return (
        <div className="h-full flex flex-col relative"
            onDragEnter={handleDragEnter} onDragLeave={handleDragLeave} onDragOver={handleDragOver} onDrop={handleDrop}>

            {/* Fullscreen drag overlay */}
            {isDragging && (
                <div className="absolute inset-0 z-50 bg-dark-900/90 backdrop-blur-sm flex items-center justify-center border-2 border-dashed border-rose-500 rounded-xl m-2 pointer-events-none">
                    <div className="text-center">
                        <div className="text-4xl mb-3">📎</div>
                        <p className="text-lg font-medium text-white">Dateien hier ablegen</p>
                        <p className="text-sm text-dark-400 mt-1">Bilder, PDFs, Dokumente</p>
                    </div>
                </div>
            )}

            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-dark-800 bg-dark-900/50 flex-shrink-0">
                <div className="flex items-center gap-3">
                    <div className="p-1.5 bg-rose-600/20 rounded-xl"><FiCpu className="w-4 h-4 text-rose-400" /></div>
                    <h1 className="text-base font-semibold text-white">Agent</h1>
                </div>
                <div className="flex items-center gap-2">
                    <button onClick={() => setAutoAccept(!autoAccept)}
                        className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-colors ${autoAccept ? 'bg-green-600/20 text-green-400 border border-green-600/30' : 'bg-dark-800 text-dark-400 border border-dark-700 hover:text-white'}`}
                        title={autoAccept ? 'Änderungen werden automatisch angewendet' : 'Änderungen müssen manuell bestätigt werden'}>
                        {autoAccept ? <FiToggleRight className="w-3.5 h-3.5" /> : <FiToggleLeft className="w-3.5 h-3.5" />}
                        {autoAccept ? 'Auto-Apply' : 'Manuell'}
                    </button>
                </div>
            </div>

            {/* Split layout: LEFT (Note/Diff) | RIGHT (Chat) */}
            <div className="flex-1 flex overflow-hidden">

                {/* LEFT PANEL: Note Viewer / Diff — connected to sidebar explorer */}
                <div className="w-[45%] border-r border-dark-800 flex flex-col overflow-hidden">
                    {/* Left panel tabs */}
                    <div className="flex items-center border-b border-dark-800 px-2 py-1.5 gap-1 flex-shrink-0">
                        {agentViewingNote && (
                            <button onClick={() => setLeftMode('note')} className={`px-2.5 py-1 text-xs rounded-md transition-colors flex items-center gap-1 max-w-[200px] ${leftMode === 'note' ? 'bg-dark-700 text-white' : 'text-dark-500 hover:text-white'}`}>
                                <FiFile className="w-3 h-3 flex-shrink-0" /><span className="truncate">{agentViewingNote.title}</span>
                                <button onClick={(e) => { e.stopPropagation(); setAgentViewingNote(null); }} className="ml-1 hover:text-red-400"><FiX className="w-2.5 h-2.5" /></button>
                            </button>
                        )}
                        {diffData && (
                            <button onClick={() => setLeftMode('diff')} className={`px-2.5 py-1 text-xs rounded-md transition-colors flex items-center gap-1 ${leftMode === 'diff' ? 'bg-amber-600/20 text-amber-400' : 'text-dark-500 hover:text-white'}`}>
                                <FiColumns className="w-3 h-3" />Diff
                                <button onClick={(e) => { e.stopPropagation(); setDiffData(null); if (leftMode === 'diff') setLeftMode('note'); }} className="ml-1 hover:text-red-400"><FiX className="w-2.5 h-2.5" /></button>
                            </button>
                        )}
                        {!agentViewingNote && !diffData && (
                            <span className="text-xs text-dark-600 px-2">← Notiz im Explorer öffnen</span>
                        )}
                    </div>

                    {/* Left panel content */}
                    <div className="flex-1 overflow-y-auto">
                        {leftMode === 'note' && agentViewingNote && (
                            <div className="p-4">
                                <h2 className="text-base font-semibold text-white mb-1">{agentViewingNote.title}</h2>
                                <div className="text-xs text-dark-500 mb-3 flex items-center gap-2">
                                    {agentViewingNote.folder_path && <span>📁 {agentViewingNote.folder_path}</span>}
                                    {agentViewingNote.tags?.length > 0 && <span>· {agentViewingNote.tags.map((t: any) => t.name).join(', ')}</span>}
                                </div>
                                <div className="markdown-content text-sm">
                                    <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins} components={markdownComponents}>{agentViewingNote.content}</ReactMarkdown>
                                </div>
                            </div>
                        )}
                        {leftMode === 'note' && !agentViewingNote && (
                            <div className="flex flex-col items-center justify-center h-full text-dark-600 px-6 text-center">
                                <FiFile className="w-8 h-8 mb-3 opacity-30" />
                                <p className="text-sm">Klicke eine Notiz im Explorer an, um sie hier zu sehen.</p>
                                <p className="text-xs mt-1 text-dark-700">Du kannst dann mit dem Agent darüber sprechen.</p>
                            </div>
                        )}
                        {leftMode === 'diff' && diffData && (
                            <DiffPanel data={diffData}
                                isApplied={appliedProposals.has(`${diffData.msgId}-${diffData.proposalIndex}`)}
                                isRejected={rejectedProposals.has(`${diffData.msgId}-${diffData.proposalIndex}`)}
                                onAccept={() => handleAcceptProposal(diffData.msgId, diffData.proposalIndex, diffData.proposal)}
                                onReject={() => handleRejectProposal(diffData.msgId, diffData.proposalIndex)}
                            />
                        )}
                    </div>
                </div>

                {/* RIGHT PANEL: Agent Chat */}
                <div className="flex-1 flex flex-col overflow-hidden">
                    {/* Chat messages */}
                    <div className="flex-1 overflow-y-auto p-3 space-y-3">
                        {parsedMessages.length === 0 && !loading && <EmptyState textareaRef={textareaRef} />}

                        {parsedMessages.map((msg) => (
                            <MessageBubble key={msg.id} msg={msg}
                                expandedSteps={expandedSteps} setExpandedSteps={setExpandedSteps}
                                appliedProposals={appliedProposals} rejectedProposals={rejectedProposals}
                                onAcceptProposal={handleAcceptProposal} onRejectProposal={handleRejectProposal}
                                onAcceptAll={handleAcceptAll} onOpenDiff={openDiffInLeft} onOpenNote={openNoteInLeft} />
                        ))}
                        {loading && (streamingContent || streamingThought || streamingSteps.length > 0) && (
                            <div className="flex gap-2">
                                <div className="w-7 h-7 rounded-lg bg-rose-600/20 flex items-center justify-center flex-shrink-0 mt-0.5">
                                    <FiCpu className="w-3.5 h-3.5 text-rose-400 animate-pulse" />
                                </div>
                                <div className="flex-1 min-w-0 space-y-2">
                                    {/* Steps: clean timeline */}
                                    {streamingSteps.length > 0 && (
                                        <div className="flex flex-wrap gap-1.5">
                                            {streamingSteps.map((step, i) => (
                                                <span key={i} className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium ${step.type === 'tool_call'
                                                    ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20'
                                                    : 'bg-green-500/10 text-green-400 border border-green-500/20'
                                                    }`}>
                                                    {step.type === 'tool_call' ? '○' : '✓'} {step.content}
                                                </span>
                                            ))}
                                        </div>
                                    )}
                                    {/* Streaming response text */}
                                    {streamingContent && (
                                        <div className="bg-dark-800/50 border border-dark-700 rounded-2xl px-3 py-2.5">
                                            <div className="prose prose-invert prose-sm max-w-none text-sm text-dark-200">
                                                <ReactMarkdown components={markdownComponents} remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins}>
                                                    {streamingContent}
                                                </ReactMarkdown>
                                            </div>
                                        </div>
                                    )}
                                    {/* Thinking indicator (subtle, no raw text) */}
                                    {!streamingContent && (
                                        <div className="flex items-center gap-2 text-xs text-dark-500">
                                            <div className="flex gap-0.5">
                                                <div className="w-1.5 h-1.5 bg-rose-400 rounded-full animate-pulse" />
                                                <div className="w-1.5 h-1.5 bg-rose-400 rounded-full animate-pulse" style={{ animationDelay: '0.15s' }} />
                                                <div className="w-1.5 h-1.5 bg-rose-400 rounded-full animate-pulse" style={{ animationDelay: '0.3s' }} />
                                            </div>
                                            <span>{streamingSteps.length > 0 ? 'Formuliere Antwort...' : 'Denkt nach...'}</span>
                                        </div>
                                    )}
                                </div>
                            </div>
                        )}
                        {loading && !streamingContent && !streamingThought && streamingSteps.length === 0 && <ThinkingIndicator />}
                        <div ref={messagesEndRef} />
                    </div>

                    {/* Input */}
                    <div className="p-3 border-t border-dark-800 flex-shrink-0">
                        {pendingFiles.length > 0 && (
                            <div className="flex gap-2 mb-2 flex-wrap">
                                {pendingFiles.map((file, i) => (
                                    <div key={i} className="relative group flex items-center gap-1.5 px-2 py-1 bg-dark-800 border border-dark-700 rounded-lg">
                                        {file.type.startsWith('image/') ? (
                                            <img src={URL.createObjectURL(file)} alt="" className="w-8 h-8 object-cover rounded" />
                                        ) : (
                                            <span className="text-lg">📄</span>
                                        )}
                                        <span className="text-xs text-dark-300 max-w-[100px] truncate">{file.name}</span>
                                        <button onClick={() => setPendingFiles((p) => p.filter((_, j) => j !== i))} className="ml-1 text-dark-500 hover:text-red-400"><FiX className="w-3 h-3" /></button>
                                    </div>
                                ))}
                            </div>
                        )}
                        <div className="flex items-end gap-2">
                            <textarea ref={textareaRef}
                                onChange={() => { adjustTextarea(); }}
                                onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
                                onPaste={handlePaste}
                                placeholder="Schreib dem Agent..."
                                className="flex-1 px-3 py-2 bg-dark-800 border border-dark-700 rounded-xl text-white text-sm placeholder-dark-600 focus:outline-none focus:border-rose-500 resize-none min-h-[40px] max-h-[140px]" rows={1} />
                            <input ref={fileInputRef} type="file" accept="image/*,.pdf,.doc,.docx,.txt,.md,.csv,.xlsx" multiple className="hidden" onChange={(e) => { const f = Array.from(e.target.files || []); if (f.length) setPendingFiles((p) => [...p, ...f]); e.target.value = ''; }} />
                            <button onClick={() => fileInputRef.current?.click()} className="p-2 rounded-xl bg-dark-800 border border-dark-700 text-dark-400 hover:text-white" title="Datei anhängen (Bilder, PDFs, Dokumente)"><FiImage className="w-4 h-4" /></button>
                            <button onClick={handleSend} disabled={loading}
                                className={`p-2 rounded-xl ${!loading ? 'bg-rose-600 hover:bg-rose-500 text-white' : 'bg-dark-800 text-dark-600 cursor-not-allowed'}`}>
                                <FiSend className="w-4 h-4" />
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}

// ── Sub-components ───────────────────────────────────────────────────

function EmptyState({ textareaRef }: { textareaRef: RefObject<HTMLTextAreaElement | null> }) {
    const setInput = (text: string) => { if (textareaRef.current) { textareaRef.current.value = text; textareaRef.current.focus(); } };
    return (
        <div className="h-full flex items-center justify-center">
            <div className="text-center max-w-sm">
                <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-dark-800 mb-3"><FiCpu className="w-7 h-7 text-rose-400/60" /></div>
                <h3 className="text-base font-semibold text-white mb-1">Agentic Workspace</h3>
                <p className="text-xs text-dark-500 mb-3">Brainstorme, plane und arbeite mit deinen Notizen.</p>
                <div className="grid grid-cols-1 gap-1.5 text-left">
                    {['Lass uns eine Wohnungsplanung machen', 'Was habe ich zum Thema X notiert?', 'Hilf mir ein Projekt zu strukturieren'].map((t) => (
                        <button key={t} onClick={() => setInput(t)} className="text-xs text-left px-2.5 py-1.5 bg-dark-800/50 border border-dark-700 rounded-lg text-dark-400 hover:text-white hover:border-rose-600/30 transition-colors">💡 {t}</button>
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
            <div className="bg-dark-800/50 border border-dark-700 rounded-2xl px-4 py-2.5">
                <div className="flex items-center gap-2.5 text-sm">
                    <div className="relative w-3.5 h-3.5"><div className="absolute inset-0 bg-rose-400 rounded-full animate-ping opacity-30" /><div className="absolute inset-0.5 bg-rose-500 rounded-full" /></div>
                    <span className="text-dark-300">Lese Notizen, plane und formuliere{dots}</span>
                </div>
            </div>
        </div>
    );
}

interface MessageBubbleProps {
    msg: ParsedAgentMessage;
    expandedSteps: Set<string>;
    setExpandedSteps: (fn: (prev: Set<string>) => Set<string>) => void;
    appliedProposals: Set<string>;
    rejectedProposals: Set<string>;
    onAcceptProposal: (msgId: string, idx: number, p: AgentProposal) => void;
    onRejectProposal: (msgId: string, idx: number) => void;
    onAcceptAll: (msgId: string, proposals: AgentProposal[]) => void;
    onOpenDiff: (p: AgentProposal, msgId: string, idx: number) => void;
    onOpenNote: (noteId: string) => void;
}

const MessageBubble = memo(function MessageBubble({ msg, expandedSteps, setExpandedSteps, appliedProposals, rejectedProposals, onAcceptProposal, onRejectProposal, onAcceptAll, onOpenDiff, onOpenNote }: MessageBubbleProps) {
    if (msg.role === 'user') {
        return (
            <div className="flex justify-end">
                <div className="max-w-[80%] space-y-1.5">
                    {msg.attachments && msg.attachments.length > 0 && (
                        <div className="flex flex-wrap gap-1.5 justify-end">
                            {msg.attachments.map((att, i) => (
                                <div key={i} className="flex items-center gap-1.5 px-2 py-1 bg-dark-800/80 border border-dark-700 rounded-lg">
                                    {att.type === 'image' && att.url ? (
                                        <img src={att.url} alt={att.name} className="w-8 h-8 object-cover rounded" />
                                    ) : (
                                        <span className="text-sm">📄</span>
                                    )}
                                    <span className="text-[11px] text-dark-300 max-w-[120px] truncate">{att.name}</span>
                                </div>
                            ))}
                        </div>
                    )}
                    <div className="bg-rose-900/30 border border-rose-800/30 rounded-2xl px-3 py-2">
                        <p className="text-sm text-white whitespace-pre-wrap">{msg.content}</p>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="flex justify-start">
            <div className="max-w-[95%] space-y-2">
                {msg.steps && msg.steps.length > 0 && (
                    <div className="bg-dark-800/30 border border-dark-700/50 rounded-xl overflow-hidden">
                        <button onClick={() => setExpandedSteps((p) => { const n = new Set(p); n.has(msg.id) ? n.delete(msg.id) : n.add(msg.id); return n; })}
                            className="flex items-center gap-2 w-full px-3 py-1.5 text-xs text-dark-400 hover:text-white">
                            {expandedSteps.has(msg.id) ? <FiChevronDown className="w-3 h-3" /> : <FiChevronRight className="w-3 h-3" />}
                            <FiZap className="w-3 h-3 text-amber-400" /> {msg.steps.length} Schritte
                        </button>
                        {expandedSteps.has(msg.id) && (<div className="px-3 pb-2 space-y-0.5">{msg.steps.map((s, i) => (<div key={i} className="flex items-start gap-2 text-xs text-dark-400"><span>{s.type === 'tool_call' ? '🔧' : s.type === 'tool_result' ? '✅' : '🧠'}</span><span>{s.content}</span></div>))}</div>)}
                    </div>
                )}

                {msg.content && (
                    <div className="bg-dark-800/50 border border-dark-700 rounded-2xl px-3 py-2.5">
                        <div className="markdown-content text-sm text-dark-200"><ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins} components={markdownComponents}>{msg.content}</ReactMarkdown></div>
                    </div>
                )}

                {msg.proposals && msg.proposals.length > 0 && (
                    <div className="space-y-1.5">
                        <div className="flex items-center justify-between px-1">
                            <span className="text-xs font-medium text-dark-400">{msg.proposals.length} Vorschläge</span>
                            <button onClick={() => onAcceptAll(msg.id, msg.proposals!)} className="flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-green-600 hover:bg-green-500 text-white rounded-lg"><FiCheckCircle className="w-3 h-3" /> Alle</button>
                        </div>
                        {msg.proposals.map((p, i) => (
                            <ProposalCard key={i} proposal={p} msgId={msg.id} index={i}
                                isApplied={appliedProposals.has(`${msg.id}-${i}`)} isRejected={rejectedProposals.has(`${msg.id}-${i}`)}
                                onAccept={() => onAcceptProposal(msg.id, i, p)} onReject={() => onRejectProposal(msg.id, i)}
                                onOpenDiff={() => onOpenDiff(p, msg.id, i)} onOpenNote={p.note_id ? () => onOpenNote(p.note_id!) : undefined} />
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
});

function ProposalCard({ proposal, msgId, index, isApplied, isRejected, onAccept, onReject, onOpenDiff, onOpenNote }: {
    proposal: AgentProposal; msgId: string; index: number; isApplied: boolean; isRejected: boolean;
    onAccept: () => void; onReject: () => void; onOpenDiff: () => void; onOpenNote?: () => void;
}) {
    const cfg = { create: { icon: FiFilePlus, color: 'text-green-400', bg: 'bg-green-600/10 border-green-600/20' }, update: { icon: FiEdit3, color: 'text-blue-400', bg: 'bg-blue-600/10 border-blue-600/20' }, delete: { icon: FiTrash2, color: 'text-red-400', bg: 'bg-red-600/10 border-red-600/20' } }[proposal.type];
    const Icon = cfg.icon;

    return (
        <div
            onClick={onOpenDiff}
            className={`border rounded-lg overflow-hidden cursor-pointer transition-colors hover:border-amber-500/40 ${isApplied ? 'border-green-600/30 bg-green-900/10' : isRejected ? 'border-dark-700 opacity-40' : cfg.bg}`}
        >
            <div className="flex items-center gap-2 px-2.5 py-1.5">
                <Icon className={`w-3.5 h-3.5 flex-shrink-0 ${cfg.color}`} />
                <div className="flex-1 min-w-0">
                    <span className="text-xs font-medium text-white truncate block">{proposal.title || proposal.new_title || ''}</span>
                    {proposal.folder_path && <span className="text-[10px] text-dark-500">📁 {proposal.folder_path}</span>}
                </div>
                <div className="flex items-center gap-1 flex-shrink-0" onClick={(e) => e.stopPropagation()}>
                    {onOpenNote && <button onClick={onOpenNote} className="p-1 hover:bg-dark-700 rounded text-dark-400 hover:text-brain-400" title="Notiz anzeigen"><FiEye className="w-3 h-3" /></button>}
                    {isApplied ? <span className="text-[10px] text-green-400 font-medium">✓ Angewendet</span> : isRejected ? <span className="text-[10px] text-dark-500">—</span> : (
                        <><button onClick={onAccept} className="p-1 bg-green-600 hover:bg-green-500 text-white rounded" title="Annehmen"><FiCheck className="w-3 h-3" /></button><button onClick={onReject} className="p-1 bg-red-600/20 hover:bg-red-600/40 text-red-400 rounded" title="Ablehnen"><FiX className="w-3 h-3" /></button></>
                    )}
                </div>
            </div>
        </div>
    );
}

function DiffPanel({ data, isApplied, isRejected, onAccept, onReject }: { data: DiffViewData; isApplied: boolean; isRejected: boolean; onAccept: () => void; onReject: () => void; }) {
    const { proposal } = data;
    return (
        <div className="flex flex-col h-full">
            <div className="px-4 py-3 border-b border-dark-800 space-y-1.5">
                <div className="flex items-center gap-2">
                    <span className={`text-xs font-medium px-2 py-0.5 rounded ${proposal.type === 'create' ? 'bg-green-600/20 text-green-400' : proposal.type === 'update' ? 'bg-blue-600/20 text-blue-400' : 'bg-red-600/20 text-red-400'}`}>
                        {proposal.type === 'create' ? 'NEU' : proposal.type === 'update' ? 'EDIT' : 'DEL'}
                    </span>
                    <span className="text-sm text-white font-medium truncate">{proposal.title || proposal.new_title || ''}</span>
                </div>
                {proposal.folder_path && <p className="text-xs text-dark-500">📁 {proposal.folder_path}</p>}
                {proposal.reason && <p className="text-xs text-dark-400 italic">{proposal.reason}</p>}
                {proposal.tags && proposal.tags.length > 0 && (<div className="flex gap-1 flex-wrap">{proposal.tags.map((t) => <span key={t} className="px-1.5 py-0.5 text-[10px] bg-dark-700 text-dark-300 rounded-full">{t}</span>)}</div>)}
            </div>
            <div className="flex-1 overflow-y-auto p-4">
                {(proposal.content || proposal.new_content) && (
                    <div className={`border rounded-xl p-4 ${proposal.type === 'create' ? 'border-green-600/20 bg-green-900/5' : 'border-blue-600/20 bg-blue-900/5'}`}>
                        <div className="markdown-content text-sm text-dark-200"><ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins} components={markdownComponents}>{proposal.content || proposal.new_content || ''}</ReactMarkdown></div>
                    </div>
                )}
                {proposal.type === 'delete' && (<div className="border border-red-600/20 rounded-xl p-4 bg-red-900/5"><p className="text-sm text-red-400">Diese Notiz wird gelöscht.</p></div>)}
            </div>
            {!isApplied && !isRejected && (
                <div className="px-4 py-3 border-t border-dark-800 flex gap-2">
                    <button onClick={onAccept} className="flex-1 flex items-center justify-center gap-2 py-2 bg-green-600 hover:bg-green-500 text-white text-sm font-medium rounded-xl"><FiCheck className="w-4 h-4" /> Annehmen</button>
                    <button onClick={onReject} className="flex-1 flex items-center justify-center gap-2 py-2 bg-dark-800 hover:bg-dark-700 text-dark-300 text-sm font-medium rounded-xl border border-dark-700"><FiX className="w-4 h-4" /> Ablehnen</button>
                </div>
            )}
            {isApplied && <div className="px-4 py-3 border-t border-dark-800 text-center"><span className="text-sm text-green-400"><FiCheckCircle className="w-4 h-4 inline mr-1" />Angewendet</span></div>}
        </div>
    );
}
