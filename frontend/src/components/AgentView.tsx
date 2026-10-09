'use client';

import { useState, useRef, useEffect, useMemo, memo, useCallback, type RefObject, type ClipboardEvent as RClipboardEvent, type DragEvent as RDragEvent, type SetStateAction, type Dispatch } from 'react';
import {
    FiSend, FiCheck, FiX, FiCheckCircle, FiCpu,
    FiChevronDown, FiChevronRight, FiLoader,
    FiFilePlus, FiEdit3, FiTrash2, FiToggleLeft, FiToggleRight,
    FiEdit2, FiImage, FiEye, FiColumns,
    FiFile,
} from 'react-icons/fi';
import ReactMarkdown from 'react-markdown';
import { markdownComponents, remarkPlugins, rehypePlugins } from '@/lib/markdownComponents';
import { runAgentStream, cancelAgentJob, updateChatMessage, applyAgentProposals, markProposalsApplied, createChatSession, getChatSession, getNote } from '@/lib/api';
import type { AgentStreamEvent } from '@/lib/api';
import { useStore } from '@/lib/store';
import type { AgentStep, AgentProposal, AgentStats, AgentCitation, ChatMessage, ChatSessionDetail, Note } from '@/lib/types';

// ── Types ────────────────────────────────────────────────────────────

interface ParsedAgentMessage {
    id: string;
    role: 'user' | 'assistant';
    content: string;
    thought?: string;
    steps?: AgentStep[];
    proposals?: AgentProposal[];
    appliedIndices?: number[];
    attachments?: { name: string; type: string; url?: string }[];
    sources?: { title: string; url: string }[];
    stats?: AgentStats;
    citations?: Record<string, AgentCitation>;
    created_at: string;
}

interface DiffViewData {
    proposal: AgentProposal;
    msgId: string;
    proposalIndex: number;
}

// Rewrite the agent's [[cite:N]] markers into markdown fragment links so they
// survive the markdown pipeline and can be rendered as chips by the `a` override.
// Within each paragraph/list block (text between blank lines), keep only the LAST
// occurrence of each cite id — so a list where every item cites the same note ends
// up with a single chip at the end instead of one per line.
const CITE_MARKER = /\[\[cite:(\d+)\]\]/g;

function collapseBlockCites(block: string): string {
    // Collect positions of every marker grouped by cite-id
    const positions = new Map<string, number[]>(); // id → [start, ...]
    const re = /\[\[cite:(\d+)\]\]/g;
    let m: RegExpExecArray | null;
    while ((m = re.exec(block)) !== null) {
        const id = m[1];
        if (!positions.has(id)) positions.set(id, []);
        positions.get(id)!.push(m.index);
    }

    // Build a set of indices to remove (all but last per id)
    const remove = new Set<number>();
    positions.forEach((idxs) => {
        idxs.slice(0, -1).forEach((idx) => remove.add(idx));
    });
    if (remove.size === 0) return block;

    // Rebuild string, skipping removed markers
    let result = '';
    let cursor = 0;
    const matchRe = /\[\[cite:(\d+)\]\]/g;
    while ((m = matchRe.exec(block)) !== null) {
        if (remove.has(m.index)) {
            result += block.slice(cursor, m.index);
            cursor = m.index + m[0].length;
        }
    }
    result += block.slice(cursor);
    return result;
}

function injectCitationLinks(content: string, citations?: Record<string, AgentCitation>): string {
    if (!citations) return content.replace(CITE_MARKER, '');

    // Collapse duplicate cites within each block (paragraph / list)
    const collapsed = content
        .split(/\n{2,}/)
        .map(collapseBlockCites)
        .join('\n\n');

    // Convert remaining markers to fragment links (unknown ids are dropped)
    return collapsed.replace(CITE_MARKER, (_full, n: string) =>
        citations[n] ? `[${n}](#cite-${n})` : ''
    );
}

function stripCitationMarkers(content: string): string {
    return content.replace(CITE_MARKER, '');
}

function parseAgentMessage(msg: ChatMessage): ParsedAgentMessage {
    let content = msg.content;
    let steps: AgentStep[] | undefined;
    let proposals: AgentProposal[] | undefined;
    let appliedIndices: number[] | undefined;
    let stats: AgentStats | undefined;
    let citations: Record<string, AgentCitation> | undefined;
    const metaMatch = content.match(/<!-- AGENT_META\n([\s\S]*?)\nAGENT_META -->/);
    if (metaMatch) {
        content = content.replace(metaMatch[0], '').trim();
        try {
            const meta = JSON.parse(metaMatch[1]);
            steps = meta.steps;
            proposals = meta.proposals;
            appliedIndices = meta.applied_indices;
            stats = meta.stats;
            citations = meta.citations;
        } catch { }
    }
    return { id: msg.id, role: msg.role, content, steps, proposals, appliedIndices, stats, citations, created_at: msg.created_at };
}

// ── Main Component ───────────────────────────────────────────────────

export default function AgentView() {
    const { loadFolderTree, loadAgentSessions, activeAgentSession, setActiveAgentSession, agentViewingNote, setAgentViewingNote } = useStore();
    const [loading, setLoading] = useState(false);
    const [autoAccept, setAutoAccept] = useState(true);
    const [parsedMessages, setParsedMessages] = useState<ParsedAgentMessage[]>([]);
    const [streamingThought, setStreamingThought] = useState('');
    const [streamingSteps, setStreamingSteps] = useState<AgentStep[]>([]);
    const [streamingStatus, setStreamingStatus] = useState('Denkt nach');
    const [appliedProposals, setAppliedProposals] = useState(new Set<string>());
    const [rejectedProposals, setRejectedProposals] = useState(new Set<string>());
    const [pendingFiles, setPendingFiles] = useState<File[]>([]);
    const [editingMessageId, setEditingMessageId] = useState<string | null>(null);
    const [editingContent, setEditingContent] = useState('');
    const [restartableMessage, setRestartableMessage] = useState<{ id: string; content: string } | null>(null);
    const [runNotice, setRunNotice] = useState<string | null>(null);
    const activeJobIdRef = useRef<string | null>(null);
    const stopRequestedRef = useRef(false);

    // Left panel: note viewer
    const [diffData, setDiffData] = useState<DiffViewData | null>(null);
    const [leftMode, setLeftMode] = useState<'note' | 'diff'>('note');

    const messagesEndRef = useRef<HTMLDivElement>(null);
    const lastAssistantRef = useRef<HTMLDivElement>(null);
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

    useEffect(() => {
        // When the newest message is from the assistant, scroll to its TOP so the
        // user starts reading from the beginning of the answer. Otherwise (a new
        // user message or while loading) keep the latest content in view at the bottom.
        const last = parsedMessages[parsedMessages.length - 1];
        if (!loading && last?.role === 'assistant' && lastAssistantRef.current) {
            lastAssistantRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
        } else {
            messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
        }
    }, [parsedMessages, loading]);

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

    // ── Send, stop, restart, and edit ─────────────────────────────

    const runAgentMessage = async (
        session: ChatSessionDetail,
        content: string,
        files?: File[],
        existingMessageId?: string,
    ) => {
        setLoading(true);
        stopRequestedRef.current = false;
        setRunNotice(null);
        setStreamingThought('');
        setStreamingSteps([]);
        setStreamingStatus('Denkt nach');
        let fullContent = '';
        let fullThought = '';
        const allSteps: AgentStep[] = [];
        const allProposals: AgentProposal[] = [];
        let cancelled = false;

        try {
            await runAgentStream(
                session.id,
                content,
                autoAccept,
                files,
                (event: AgentStreamEvent) => {
                    switch (event.type) {
                        case 'thinking':
                            fullThought += event.content;
                            setStreamingThought(fullThought);
                            allSteps.push({ type: 'thinking', content: event.content, round: event.round ?? undefined });
                            setStreamingSteps([...allSteps]);
                            break;
                        case 'chunk': fullContent += event.content; setStreamingStatus('Formuliert Antwort'); break;
                        case 'tool_call':
                            allSteps.push({
                                type: 'tool_call',
                                content: event.content,
                                tool: event.tool ?? undefined,
                                args: event.args ?? undefined,
                                round: event.round ?? undefined,
                            });
                            setStreamingSteps([...allSteps]);
                            if (event.status) setStreamingStatus(event.status);
                            break;
                        case 'tool_result':
                            allSteps.push({
                                type: 'tool_result',
                                content: event.content,
                                tool: event.tool ?? undefined,
                                details: event.details ?? undefined,
                                round: event.round ?? undefined,
                            });
                            setStreamingSteps([...allSteps]);
                            break;
                        case 'proposal': allProposals.push(event.proposal); break;
                        case 'cancelled': cancelled = true; setRunNotice('Antwort wurde abgebrochen. Du kannst sie neu starten oder die Nachricht bearbeiten.'); break;
                        case 'error': setRunNotice(event.detail ? `${event.message}\n${event.detail}` : event.message); break;
                    }
                },
                {
                    existingMessageId,
                    onJobStarted: (jobId, messageId) => {
                        activeJobIdRef.current = jobId;
                        setRestartableMessage({ id: messageId, content });
                        if (stopRequestedRef.current) void cancelAgentJob(jobId);
                    },
                },
            );

            const refreshed = await getChatSession(session.id);
            setActiveAgentSession(refreshed);
            setParsedMessages(refreshed.messages.map(parseAgentMessage));
            await loadAgentSessions();
            await loadFolderTree();
            if (!cancelled) setRestartableMessage(null);
        } catch (error) {
            console.error(error);
            setRunNotice(error instanceof Error ? error.message : 'Fehler bei der Verarbeitung.');
            try {
                const refreshed = await getChatSession(session.id);
                setActiveAgentSession(refreshed);
                setParsedMessages(refreshed.messages.map(parseAgentMessage));
                await loadAgentSessions();
            } catch (refreshError) { console.error(refreshError); }
        } finally {
            activeJobIdRef.current = null;
            setStreamingThought('');
            setStreamingSteps([]);
            setStreamingStatus('Denkt nach');
            setLoading(false);
        }
    };

    const handleSend = async () => {
        const inputVal = textareaRef.current?.value?.trim() || '';
        if ((!inputVal && pendingFiles.length === 0) || loading) return;
        let session = activeAgentSession;
        if (!session) {
            try {
                const created = await createChatSession('agent', inputVal.slice(0, 50));
                session = await getChatSession(created.id);
                setActiveAgentSession(session);
                await loadAgentSessions();
            } catch (error) { console.error(error); return; }
        }

        if (!session) return;

        const currentFiles = [...pendingFiles];
        setPendingFiles([]);
        if (textareaRef.current) { textareaRef.current.value = ''; textareaRef.current.style.height = 'auto'; }
        const attachments = currentFiles.map((file) => ({
            name: file.name,
            type: file.type.startsWith('image/') ? 'image' : 'document',
            url: file.type.startsWith('image/') ? URL.createObjectURL(file) : undefined,
        }));
        setParsedMessages((messages) => [...messages, {
            id: `temp-${Date.now()}`, role: 'user', content: inputVal,
            attachments: attachments.length ? attachments : undefined, created_at: new Date().toISOString(),
        }]);
        await runAgentMessage(session, inputVal, currentFiles.length ? currentFiles : undefined);
    };

    const handleStop = async () => {
        stopRequestedRef.current = true;
        const jobId = activeJobIdRef.current;
        if (!jobId) {
            setRunNotice('Abbruch wird ausgeführt, sobald der Agentenlauf gestartet ist.');
            return;
        }
        try { await cancelAgentJob(jobId); }
        catch (error) { setRunNotice(error instanceof Error ? error.message : 'Abbruch fehlgeschlagen.'); }
    };

    const handleRestart = async () => {
        if (!activeAgentSession || !restartableMessage || loading) return;
        await runAgentMessage(activeAgentSession, restartableMessage.content, undefined, restartableMessage.id);
    };

    const beginEdit = (message: ParsedAgentMessage) => {
        setEditingMessageId(message.id);
        setEditingContent(message.content);
    };

    const saveEdit = async () => {
        if (!activeAgentSession || !editingMessageId || !editingContent.trim() || loading) return;
        const editedContent = editingContent.trim();
        const msgId = editingMessageId;
        try {
            const updated = await updateChatMessage(activeAgentSession.id, msgId, editedContent);
            setActiveAgentSession(updated);
            setParsedMessages(updated.messages.map(parseAgentMessage));
            setEditingMessageId(null);
            setEditingContent('');
            await loadAgentSessions();
            // Immediately re-run the agent with the edited message
            await runAgentMessage(updated, editedContent, undefined, msgId);
        } catch (error) {
            setRunNotice(error instanceof Error ? error.message : 'Nachricht konnte nicht geändert werden.');
        }
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
            <div className="flex-1 flex flex-col lg:flex-row overflow-hidden">

                {/* LEFT PANEL: Note Viewer / Diff — hidden on mobile, shown on desktop */}
                <div className="hidden lg:flex lg:w-[45%] border-r border-dark-800 flex-col overflow-hidden">
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
                    <div className="flex-1 overflow-y-auto px-4 sm:px-6 py-6">
                        <div className="max-w-3xl mx-auto w-full space-y-6">
                            {parsedMessages.length === 0 && !loading && <EmptyState textareaRef={textareaRef} />}

                            {parsedMessages.map((msg, idx) => {
                                const isLast = idx === parsedMessages.length - 1;
                                return (
                                    <div key={msg.id} ref={isLast && msg.role === 'assistant' ? lastAssistantRef : undefined}>
                                        <MessageBubble msg={msg}
                                            appliedProposals={appliedProposals} rejectedProposals={rejectedProposals}
                                            onAcceptProposal={handleAcceptProposal} onRejectProposal={handleRejectProposal}
                                            onAcceptAll={handleAcceptAll} onOpenDiff={openDiffInLeft} onOpenNote={openNoteInLeft}
                                            onEdit={beginEdit}
                                            isEditing={editingMessageId === msg.id}
                                            editingContent={editingMessageId === msg.id ? editingContent : ''}
                                            onEditChange={setEditingContent}
                                            onEditSubmit={saveEdit}
                                            onEditCancel={() => { setEditingMessageId(null); setEditingContent(''); }}
                                        />
                                    </div>
                                );
                            })}
                            {runNotice && (
                                <div className="flex items-center justify-between gap-3 rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
                                    <span className="whitespace-pre-line">{runNotice}</span>
                                    <div className="flex gap-1.5 flex-shrink-0">
                                        {restartableMessage && !loading && <button onClick={handleRestart} className="rounded-md bg-rose-600 px-2 py-1 font-medium text-white hover:bg-rose-500">Neu starten</button>}
                                        <button onClick={() => setRunNotice(null)} className="p-1 text-amber-200 hover:text-white" title="Hinweis schließen"><FiX className="w-3.5 h-3.5" /></button>
                                    </div>
                                </div>
                            )}
                            {loading && (
                                <div className="agent-message-in py-1">
                                    <ActivityLine
                                        status={streamingStatus}
                                        thought={streamingThought}
                                        steps={streamingSteps}
                                        live
                                    />
                                </div>
                            )}
                            <div ref={messagesEndRef} />
                        </div>
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
                            {loading ? (
                                <button onClick={handleStop} className="flex items-center gap-1.5 rounded-xl bg-red-600 px-3 py-2 text-xs font-medium text-white hover:bg-red-500" title="Antwort abbrechen"><FiX className="w-4 h-4" /> Stop</button>
                            ) : (
                                <button onClick={handleSend} className="p-2 rounded-xl bg-rose-600 text-white hover:bg-rose-500" title="Senden"><FiSend className="w-4 h-4" /></button>
                            )}
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

// ── Gemini-style activity line ───────────────────────────────────────
// A single shimmering status phrase that rotates as the agent moves from
// tool to tool. Click to expand the full timeline grouped by round.

function ActivityLine({ status, thought, steps, live = false }: {
    status: string;
    thought?: string;
    steps?: AgentStep[];
    live?: boolean;
}) {
    const [expanded, setExpanded] = useState(false);
    const hasDetail = !!(thought || (steps && steps.length > 0));

    return (
        <div>
            <button
                onClick={() => hasDetail && setExpanded((e) => !e)}
                className={`flex items-center gap-1.5 text-sm ${hasDetail ? 'cursor-pointer' : 'cursor-default'}`}
            >
                <span
                    key={status}
                    className={`agent-phrase ${live ? 'agent-shimmer font-medium' : 'text-dark-500 hover:text-dark-300 transition-colors'}`}
                >
                    {status}
                </span>
                {hasDetail && (
                    <FiChevronRight className={`w-3 h-3 text-dark-600 transition-transform ${expanded ? 'rotate-90' : ''}`} />
                )}
            </button>

            {expanded && hasDetail && (
                <div className="agent-expand mt-2">
                    <TimelineView steps={steps || []} fallbackThought={thought} />
                </div>
            )}
        </div>
    );
}

// ── Timeline: round-grouped tool trace ──────────────────────────────
// Each round contains the model's thought summary + every tool call it
// decided to make, with the tool arguments and the structured result.

const TOOL_META: Record<string, { icon: string; label: string }> = {
    search_notes: { icon: '🔎', label: 'Notizen-Suche' },
    read_note: { icon: '📖', label: 'Notiz gelesen' },
    list_folders: { icon: '📂', label: 'Ordner geladen' },
    list_notes_in_folder: { icon: '📂', label: 'Notizen im Ordner' },
    search_images: { icon: '🖼️', label: 'Bild-Suche' },
    view_image: { icon: '🖼️', label: 'Bild angesehen' },
    view_document: { icon: '📄', label: 'Dokument gelesen' },
    get_recent_notes: { icon: '🕐', label: 'Letzte Notizen' },
    create_note: { icon: '✏️', label: 'Notiz erstellt' },
    update_note: { icon: '✏️', label: 'Notiz bearbeitet' },
    delete_note: { icon: '🗑️', label: 'Notiz gelöscht' },
    rename_note: { icon: '✏️', label: 'Notiz umbenannt' },
    move_note: { icon: '📦', label: 'Notiz verschoben' },
    create_folder: { icon: '📁', label: 'Ordner angelegt' },
    rename_folder: { icon: '📁', label: 'Ordner umbenannt' },
    delete_folder: { icon: '🗑️', label: 'Ordner gelöscht' },
    web_search: { icon: '🌐', label: 'Web-Recherche' },
    get_fitness_overview: { icon: '💪', label: 'Fitness-Status' },
    get_workout_data: { icon: '🏋️', label: 'Workouts' },
    get_health_data: { icon: '🥗', label: 'Ernährung/Schlaf' },
    get_wardrobe: { icon: '👔', label: 'Garderobe' },
    get_wardrobe_analytics: { icon: '📊', label: 'Garderobe-Analyse' },
    _summarize: { icon: '✨', label: 'Zusammenfassung' },
};

interface RoundGroup {
    round: number;
    thoughts: string[];
    calls: Array<{ call?: AgentStep; result?: AgentStep }>;
}

function groupStepsByRound(steps: AgentStep[]): RoundGroup[] {
    const rounds = new Map<number, RoundGroup>();
    const getRound = (r: number) => {
        if (!rounds.has(r)) rounds.set(r, { round: r, thoughts: [], calls: [] });
        return rounds.get(r)!;
    };

    // Pair tool_call with the next tool_result that has the same tool+round.
    const pendingByRound: Record<number, Array<{ call?: AgentStep; result?: AgentStep }>> = {};

    for (const step of steps) {
        const r = step.round ?? 0;
        const g = getRound(r);
        if (step.type === 'thinking') {
            g.thoughts.push(step.content);
        } else if (step.type === 'tool_call') {
            const pending = (pendingByRound[r] ||= []);
            const slot = { call: step };
            pending.push(slot);
            g.calls.push(slot);
        } else if (step.type === 'tool_result') {
            const pending = pendingByRound[r] || [];
            // Attach to the earliest open call that doesn't have a result yet
            const open = pending.find((p) => p.call && !p.result);
            if (open) open.result = step;
            else {
                const slot = { result: step };
                (pendingByRound[r] ||= []).push(slot);
                g.calls.push(slot);
            }
        }
    }

    return Array.from(rounds.values()).sort((a, b) => a.round - b.round);
}

function TimelineView({ steps, fallbackThought }: { steps: AgentStep[]; fallbackThought?: string }) {
    const groups = useMemo(() => groupStepsByRound(steps), [steps]);
    const hasAnything = groups.length > 0 || !!fallbackThought;
    if (!hasAnything) return null;

    return (
        <div className="rounded-lg border border-dark-800 bg-dark-900/40 p-3 space-y-3">
            {fallbackThought && groups.length === 0 && (
                <ThoughtBlock text={fallbackThought} />
            )}
            {groups.map((g, i) => (
                <RoundBlock key={g.round} group={g} index={i} total={groups.length} />
            ))}
        </div>
    );
}

function RoundBlock({ group, index, total }: { group: RoundGroup; index: number; total: number }) {
    return (
        <div className="space-y-2">
            {total > 1 && (
                <div className="flex items-center gap-2 text-[10px] uppercase tracking-wide text-dark-600">
                    <span>Runde {index + 1}</span>
                    <div className="flex-1 h-px bg-dark-800" />
                </div>
            )}
            {group.thoughts.map((t, i) => (
                <ThoughtBlock key={`t-${i}`} text={t} />
            ))}
            {group.calls.map((c, i) => (
                <ToolBlock key={`c-${i}`} call={c.call} result={c.result} />
            ))}
        </div>
    );
}

function ThoughtBlock({ text }: { text: string }) {
    return (
        <div className="flex items-start gap-2 text-xs text-dark-400">
            <span className="mt-0.5 flex-shrink-0 text-purple-400">🧠</span>
            <span className="italic whitespace-pre-wrap leading-relaxed">{text}</span>
        </div>
    );
}

function ToolBlock({ call, result }: { call?: AgentStep; result?: AgentStep }) {
    const toolName = call?.tool || result?.tool || '';
    const meta = TOOL_META[toolName] || { icon: '🔧', label: toolName || 'Tool' };
    const isError = result?.details && typeof result.details === 'object' && 'error' in (result.details as Record<string, unknown>);

    return (
        <div className="rounded-md border border-dark-800 bg-dark-950/50 overflow-hidden">
            <div className="flex items-center gap-2 px-2.5 py-1.5 text-xs">
                <span className="flex-shrink-0">{meta.icon}</span>
                <span className="text-dark-300 font-medium">{meta.label}</span>
                {call?.args && Object.keys(call.args).length > 0 && (
                    <ArgsPreview args={call.args} />
                )}
                {result?.content && (
                    <span className={`ml-auto text-[11px] ${isError ? 'text-red-400' : 'text-dark-500'}`}>
                        {result.content}
                    </span>
                )}
            </div>
            {result?.details && Object.keys(result.details as object).length > 0 && (
                <div className="px-2.5 py-1.5 border-t border-dark-800/60 bg-dark-950/40">
                    <ResultDetails tool={toolName} details={result.details as Record<string, unknown>} />
                </div>
            )}
        </div>
    );
}

function ArgsPreview({ args }: { args: Record<string, unknown> }) {
    const entries = Object.entries(args).filter(([, v]) => v !== null && v !== undefined && v !== '');
    if (entries.length === 0) return null;
    const primary = entries.find(([k]) => k === 'query' || k === 'q') || entries[0];
    const [k, v] = primary;
    const value = typeof v === 'string' ? v : JSON.stringify(v);
    return (
        <code className="text-[11px] text-dark-500 font-mono bg-dark-900/60 px-1.5 py-0.5 rounded truncate max-w-[260px]" title={`${k}: ${value}`}>
            {k === 'query' ? `„${value}"` : `${k}: ${value}`}
        </code>
    );
}

function ResultDetails({ tool, details }: { tool: string; details: Record<string, unknown> }) {
    if ('error' in details) {
        return <div className="text-[11px] text-red-400">{String(details.error)}</div>;
    }

    // search_notes / get_recent_notes / list_notes_in_folder-style hit lists
    if (Array.isArray(details.hits)) {
        return (
            <ul className="space-y-0.5 text-[11px]">
                {(details.hits as Array<Record<string, unknown>>).map((h, i) => (
                    <li key={i} className="text-dark-300">
                        <span className="text-dark-400">·</span>{' '}
                        <span className="text-white">{String(h.title)}</span>
                        {h.folder_path ? <span className="text-dark-600"> · 📁 {String(h.folder_path)}</span> : null}
                        {h.snippet ? <div className="text-dark-500 ml-2 italic">{String(h.snippet)}</div> : null}
                    </li>
                ))}
            </ul>
        );
    }
    if (Array.isArray(details.sources)) {
        return (
            <ul className="space-y-0.5 text-[11px]">
                {(details.sources as Array<Record<string, unknown>>).map((s, i) => (
                    <li key={i}>
                        <a href={String(s.url)} target="_blank" rel="noopener noreferrer"
                            className="text-blue-400 hover:underline">
                            🌐 {String(s.title || s.url)}
                        </a>
                    </li>
                ))}
            </ul>
        );
    }
    if (Array.isArray(details.images)) {
        return (
            <ul className="space-y-0.5 text-[11px] text-dark-300">
                {(details.images as Array<Record<string, unknown>>).map((img, i) => (
                    <li key={i}>
                        <span className="text-white">{String(img.filename)}</span>
                        {img.snippet ? <span className="text-dark-500"> — {String(img.snippet)}</span> : null}
                    </li>
                ))}
            </ul>
        );
    }
    if (Array.isArray(details.folders)) {
        return (
            <div className="text-[11px] text-dark-400 flex flex-wrap gap-1">
                {(details.folders as string[]).map((f, i) => (
                    <span key={i} className="bg-dark-800/60 px-1.5 py-0.5 rounded">📁 {f}</span>
                ))}
                {typeof details.total === 'number' && details.total > (details.folders as string[]).length && (
                    <span className="text-dark-600">+{details.total - (details.folders as string[]).length} weitere</span>
                )}
            </div>
        );
    }
    if (Array.isArray(details.notes)) {
        return (
            <ul className="space-y-0.5 text-[11px] text-dark-300">
                {(details.notes as string[]).map((n, i) => <li key={i}>· {n}</li>)}
            </ul>
        );
    }
    if (typeof details.snippet === 'string') {
        return (
            <div className="text-[11px]">
                {details.title ? <div className="text-white">{String(details.title)}</div> : null}
                <div className="text-dark-500 italic">{String(details.snippet)}</div>
                {typeof details.chars === 'number' && (
                    <div className="text-dark-700 mt-0.5">{details.chars} Zeichen</div>
                )}
            </div>
        );
    }

    // Fallback: compact key/value grid
    const entries = Object.entries(details).filter(([, v]) => v !== null && v !== undefined && v !== '');
    if (entries.length === 0) return null;
    return (
        <div className="text-[11px] text-dark-400 space-y-0.5">
            {entries.map(([k, v]) => (
                <div key={k} className="flex gap-2">
                    <span className="text-dark-600">{k}:</span>
                    <span className="text-dark-300 break-all">{typeof v === 'string' ? v : JSON.stringify(v)}</span>
                </div>
            ))}
        </div>
    );
}

// ── Compact stats line under each answer ─────────────────────────────

function shortModel(model: string): string {
    return model.includes('/') ? model.split('/').pop()! : model;
}

function formatDuration(ms: number): string {
    if (ms < 1000) return `${ms} ms`;
    const s = ms / 1000;
    if (s < 60) return `${s.toFixed(1)} s`;
    const m = Math.floor(s / 60);
    return `${m}m ${Math.round(s % 60)}s`;
}

// ── Inline citation chip ─────────────────────────────────────────────
// Rendered in place of a [[cite:N]] marker. Notes open in the left panel,
// web sources open in a new tab.

function CitationChip({ citation, onOpenNote }: {
    citation: AgentCitation;
    onOpenNote: (noteId: string) => void;
}) {
    const label = citation.title || (citation.type === 'web' ? 'Quelle' : 'Notiz');

    if (citation.type === 'note' && citation.note_id) {
        const tooltip = citation.folder_path ? `${citation.folder_path} / ${label}` : label;
        return (
            <button
                type="button"
                onClick={() => onOpenNote(citation.note_id!)}
                className="agent-cite"
                title={`Notiz öffnen: ${tooltip}`}
            >
                <span className="agent-cite-icon">📄</span>
                <span className="agent-cite-label">{label}</span>
            </button>
        );
    }

    if (citation.url) {
        let host = '';
        try { host = new URL(citation.url).hostname.replace(/^www\./, ''); } catch { }
        return (
            <a
                href={citation.url}
                target="_blank"
                rel="noopener noreferrer"
                className="agent-cite"
                title={`${label}${host ? ` — ${host}` : ''}`}
            >
                <span className="agent-cite-icon">{citation.type === 'file' ? '🖼️' : '🌐'}</span>
                <span className="agent-cite-label">{host || label}</span>
            </a>
        );
    }

    return (
        <span className="agent-cite" title={label}>
            <span className="agent-cite-label">{label}</span>
        </span>
    );
}

function StatsBar({ content, stats }: { content: string; stats?: AgentStats }) {
    const wordCount = useMemo(() => {
        const trimmed = stripCitationMarkers(content).trim();
        return trimmed ? trimmed.split(/\s+/).length : 0;
    }, [content]);

    const parts: string[] = [`${wordCount} Wörter`];
    if (stats) {
        if (stats.total_tokens) parts.push(`${stats.input_tokens} ↑ · ${stats.output_tokens} ↓ Tokens`);
        if (stats.cost) parts.push(`$${stats.cost.toFixed(4)}`);
        if (stats.model) parts.push(shortModel(stats.model));
        if (stats.duration_ms) parts.push(formatDuration(stats.duration_ms));
    }

    return (
        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] text-dark-600 select-none">
            {parts.map((p, i) => (
                <span key={i} className="flex items-center gap-2">
                    {i > 0 && <span className="text-dark-700">·</span>}
                    {p}
                </span>
            ))}
        </div>
    );
}

interface MessageBubbleProps {
    msg: ParsedAgentMessage;
    appliedProposals: Set<string>;
    rejectedProposals: Set<string>;
    onAcceptProposal: (msgId: string, idx: number, p: AgentProposal) => void;
    onRejectProposal: (msgId: string, idx: number) => void;
    onAcceptAll: (msgId: string, proposals: AgentProposal[]) => void;
    onOpenDiff: (p: AgentProposal, msgId: string, idx: number) => void;
    onOpenNote: (noteId: string) => void;
    onEdit: (message: ParsedAgentMessage) => void;
    // Inline editing state — passed down so the textarea renders in place
    isEditing: boolean;
    editingContent: string;
    onEditChange: (value: string) => void;
    onEditSubmit: () => void;
    onEditCancel: () => void;
}

const MessageBubble = memo(function MessageBubble({ msg, appliedProposals, rejectedProposals, onAcceptProposal, onRejectProposal, onAcceptAll, onOpenDiff, onOpenNote, onEdit, isEditing, editingContent, onEditChange, onEditSubmit, onEditCancel }: MessageBubbleProps) {
    // Turn [[cite:N]] markers into fragment links, then render those as chips.
    const citedContent = useMemo(
        () => injectCitationLinks(msg.content, msg.citations),
        [msg.content, msg.citations],
    );

    const mdComponents = useMemo(() => ({
        ...markdownComponents,
        a: ({ href, children, ...props }: any) => {
            const match = typeof href === 'string' ? href.match(/^#cite-(\d+)$/) : null;
            const citation = match && msg.citations ? msg.citations[match[1]] : undefined;
            if (citation) {
                return <CitationChip citation={citation} onOpenNote={onOpenNote} />;
            }
            return <a href={href} target="_blank" rel="noopener noreferrer" {...props}>{children}</a>;
        },
    }), [msg.citations, onOpenNote]);

    if (msg.role === 'user') {
        return (
            <div className="group flex flex-col items-end gap-1.5">
                {msg.attachments && msg.attachments.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 justify-end">
                        {msg.attachments.map((att, i) => (
                            <div key={i} className="flex items-center gap-1.5 px-2 py-1 bg-dark-800/60 rounded-lg">
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
                {isEditing ? (
                    <div className="w-full max-w-[85%] space-y-2">
                        <textarea
                            value={editingContent}
                            onChange={(e) => onEditChange(e.target.value)}
                            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); onEditSubmit(); } }}
                            rows={3}
                            autoFocus
                            className="w-full resize-y rounded-xl border border-dark-700 bg-dark-900 px-3 py-2 text-[15px] text-white focus:border-rose-500 focus:outline-none text-right"
                        />
                        <div className="flex justify-end gap-2">
                            <button onClick={onEditCancel} className="rounded-lg px-2.5 py-1 text-xs text-dark-400 hover:text-white">Abbrechen</button>
                            <button
                                onClick={onEditSubmit}
                                disabled={!editingContent.trim()}
                                className="flex items-center gap-1.5 rounded-xl bg-rose-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-rose-500 disabled:opacity-50"
                            >
                                <FiSend className="w-3 h-3" /> Erneut senden
                            </button>
                        </div>
                    </div>
                ) : (
                    <>
                        <p className="text-[15px] leading-relaxed text-white whitespace-pre-wrap text-right max-w-[85%]">{msg.content}</p>
                        <button onClick={() => onEdit(msg)} className="flex items-center gap-1 text-[11px] text-dark-600 opacity-0 group-hover:opacity-100 transition-opacity hover:text-rose-300" title="Nachricht bearbeiten und erneut senden"><FiEdit2 className="w-3 h-3" /> Bearbeiten</button>
                    </>
                )}
            </div>
        );
    }

    return (
        <div className="space-y-3">
            {(msg.thought || (msg.steps && msg.steps.length > 0)) && (
                <ActivityLine
                    status={msg.steps && msg.steps.length > 0 ? `${msg.steps.length} Schritte` : 'Gedankengang'}
                    thought={msg.thought}
                    steps={msg.steps}
                />
            )}

            {msg.content && (
                <div className="markdown-content lesson-prose text-[15px] text-dark-100">
                    <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins} components={mdComponents}>{citedContent}</ReactMarkdown>
                </div>
            )}

            {msg.content && <StatsBar content={msg.content} stats={msg.stats} />}

            {msg.sources && msg.sources.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                    {msg.sources.map((src, i) => (
                        <a key={i} href={src.url} target="_blank" rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 px-2 py-0.5 bg-blue-600/10 border border-blue-600/20 rounded-full text-[11px] text-blue-400 hover:bg-blue-600/20 hover:text-blue-300 transition-colors">
                            🌐 {src.title || new URL(src.url).hostname}
                        </a>
                    ))}
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
    );
});

const PROPOSAL_CONFIG: Record<string, { icon: typeof FiFilePlus; color: string; bg: string; label: string }> = {
    create: { icon: FiFilePlus, color: 'text-green-400', bg: 'bg-green-600/10 border-green-600/20', label: 'Neue Notiz' },
    update: { icon: FiEdit3, color: 'text-blue-400', bg: 'bg-blue-600/10 border-blue-600/20', label: 'Notiz bearbeiten' },
    delete: { icon: FiTrash2, color: 'text-red-400', bg: 'bg-red-600/10 border-red-600/20', label: 'Notiz löschen' },
    rename_note: { icon: FiEdit2, color: 'text-blue-400', bg: 'bg-blue-600/10 border-blue-600/20', label: 'Notiz umbenennen' },
    move_note: { icon: FiFile, color: 'text-cyan-400', bg: 'bg-cyan-600/10 border-cyan-600/20', label: 'Notiz verschieben' },
    create_folder: { icon: FiFilePlus, color: 'text-yellow-400', bg: 'bg-yellow-600/10 border-yellow-600/20', label: 'Ordner erstellen' },
    rename_folder: { icon: FiEdit2, color: 'text-yellow-400', bg: 'bg-yellow-600/10 border-yellow-600/20', label: 'Ordner umbenennen' },
    delete_folder: { icon: FiTrash2, color: 'text-red-400', bg: 'bg-red-600/10 border-red-600/20', label: 'Ordner löschen' },
};

function ProposalCard({ proposal, msgId, index, isApplied, isRejected, onAccept, onReject, onOpenDiff, onOpenNote }: {
    proposal: AgentProposal; msgId: string; index: number; isApplied: boolean; isRejected: boolean;
    onAccept: () => void; onReject: () => void; onOpenDiff: () => void; onOpenNote?: () => void;
}) {
    const [expanded, setExpanded] = useState(false);
    const cfg = PROPOSAL_CONFIG[proposal.type] || PROPOSAL_CONFIG.update;
    const Icon = cfg.icon;

    const noteBody = proposal.content || proposal.new_content || '';
    const hasBody = !!noteBody;
    // Folder ops and rename/move have a short structured description instead of a body
    const isStructural = ['rename_note', 'move_note', 'create_folder', 'rename_folder', 'delete_folder'].includes(proposal.type);

    const displayTitle = proposal.title || proposal.new_title || proposal.folder_path || '';

    return (
        <div className={`border rounded-lg overflow-hidden transition-colors ${isApplied ? 'border-green-600/30 bg-green-900/10' : isRejected ? 'border-dark-700 opacity-40' : cfg.bg}`}>
            <div className="flex items-center gap-2 px-2.5 py-1.5">
                <Icon className={`w-3.5 h-3.5 flex-shrink-0 ${cfg.color}`} />
                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5">
                        <span className={`text-[9px] uppercase font-semibold tracking-wide ${cfg.color}`}>{cfg.label}</span>
                    </div>
                    <span className="text-xs font-medium text-white truncate block">{displayTitle}</span>
                    {proposal.type === 'move_note' && <span className="text-[10px] text-dark-500">→ 📁 {proposal.target_folder_path}</span>}
                    {proposal.type === 'rename_note' && <span className="text-[10px] text-dark-500">„{proposal.title}" → „{proposal.new_title}"</span>}
                    {proposal.type === 'rename_folder' && <span className="text-[10px] text-dark-500">→ „{proposal.new_name}"</span>}
                    {proposal.folder_path && proposal.type !== 'move_note' && proposal.type !== 'create_folder' && proposal.type !== 'rename_folder' && proposal.type !== 'delete_folder' && <span className="text-[10px] text-dark-500">📁 {proposal.folder_path}</span>}
                </div>
                <div className="flex items-center gap-1 flex-shrink-0">
                    {(hasBody || isStructural) && (
                        <button onClick={() => setExpanded((e) => !e)} className="p-1 hover:bg-dark-700 rounded text-dark-400 hover:text-white" title="Vorschau anzeigen">
                            {expanded ? <FiChevronDown className="w-3 h-3" /> : <FiChevronRight className="w-3 h-3" />}
                        </button>
                    )}
                    {onOpenNote && <button onClick={onOpenNote} className="p-1 hover:bg-dark-700 rounded text-dark-400 hover:text-brain-400 hidden lg:inline-flex" title="Im Seitenpanel öffnen"><FiEye className="w-3 h-3" /></button>}
                    {isApplied ? <span className="text-[10px] text-green-400 font-medium">✓ Angewendet</span> : isRejected ? <span className="text-[10px] text-dark-500">—</span> : (
                        <><button onClick={onAccept} className="p-1 bg-green-600 hover:bg-green-500 text-white rounded" title="Annehmen"><FiCheck className="w-3 h-3" /></button><button onClick={onReject} className="p-1 bg-red-600/20 hover:bg-red-600/40 text-red-400 rounded" title="Ablehnen"><FiX className="w-3 h-3" /></button></>
                    )}
                </div>
            </div>

            {/* Inline preview — full note content right in the chat */}
            {expanded && (
                <div className="border-t border-dark-700/60 bg-dark-950/40 px-3 py-2.5 max-h-80 overflow-y-auto">
                    {proposal.tags && proposal.tags.length > 0 && (
                        <div className="flex gap-1 flex-wrap mb-2">
                            {proposal.tags.map((t) => <span key={t} className="px-1.5 py-0.5 text-[10px] bg-dark-700 text-dark-300 rounded-full">#{t}</span>)}
                        </div>
                    )}
                    {hasBody ? (
                        <div className="markdown-content text-xs text-dark-200">
                            <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins} components={markdownComponents}>{noteBody}</ReactMarkdown>
                        </div>
                    ) : proposal.type === 'delete' ? (
                        <p className="text-xs text-red-400">Diese Notiz wird gelöscht.</p>
                    ) : proposal.type === 'delete_folder' ? (
                        <p className="text-xs text-red-400">Ordner „{proposal.folder_path}" und sein gesamter Inhalt werden gelöscht.</p>
                    ) : proposal.type === 'create_folder' ? (
                        <p className="text-xs text-dark-300">Neuer Ordner: <span className="text-white">{proposal.folder_path}</span></p>
                    ) : proposal.type === 'move_note' ? (
                        <p className="text-xs text-dark-300">Notiz wird verschoben nach: <span className="text-white">📁 {proposal.target_folder_path}</span></p>
                    ) : proposal.type === 'rename_note' ? (
                        <p className="text-xs text-dark-300">Titel: „{proposal.title}" → <span className="text-white">„{proposal.new_title}"</span></p>
                    ) : proposal.type === 'rename_folder' ? (
                        <p className="text-xs text-dark-300">Ordner „{proposal.folder_path}" → <span className="text-white">„{proposal.new_name}"</span></p>
                    ) : null}
                </div>
            )}
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
