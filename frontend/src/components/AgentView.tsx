'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import {
    FiSend, FiCheck, FiX, FiCheckCircle, FiCpu,
    FiChevronDown, FiChevronRight, FiZap, FiLoader,
    FiFilePlus, FiEdit3, FiTrash2, FiToggleLeft, FiToggleRight,
    FiPlus, FiMessageSquare, FiEdit2,
} from 'react-icons/fi';
import ReactMarkdown from 'react-markdown';
import { markdownComponents, remarkPlugins, rehypePlugins } from '@/lib/markdownComponents';
import { runAgent, applyAgentProposals, createChatSession, getChatSession, deleteChatSession, updateChatSession } from '@/lib/api';
import { useStore } from '@/lib/store';
import type { AgentStep, AgentProposal, ChatMessage, ChatSessionDetail } from '@/lib/types';

interface ParsedAgentMessage {
    id: string;
    role: 'user' | 'assistant';
    content: string;
    steps?: AgentStep[];
    proposals?: AgentProposal[];
    created_at: string;
}

function parseAgentMessage(msg: ChatMessage): ParsedAgentMessage {
    let content = msg.content;
    let steps: AgentStep[] | undefined;
    let proposals: AgentProposal[] | undefined;

    // Extract hidden metadata
    const metaMatch = content.match(/<!-- AGENT_META\n([\s\S]*?)\nAGENT_META -->/);
    if (metaMatch) {
        content = content.replace(metaMatch[0], '').trim();
        try {
            const meta = JSON.parse(metaMatch[1]);
            steps = meta.steps;
            proposals = meta.proposals;
        } catch { /* ignore parse errors */ }
    }

    return { id: msg.id, role: msg.role, content, steps, proposals, created_at: msg.created_at };
}

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
    const messagesEndRef = useRef<HTMLDivElement>(null);
    const textareaRef = useRef<HTMLTextAreaElement>(null);

    useEffect(() => {
        loadAgentSessions();
    }, [loadAgentSessions]);

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
        const textarea = textareaRef.current;
        if (textarea) {
            textarea.style.height = 'auto';
            textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`;
        }
    };

    const handleNewSession = async () => {
        try {
            const session = await createChatSession('agent', 'Neuer Agent-Chat');
            const detail = await getChatSession(session.id);
            setActiveAgentSession(detail);
            await loadAgentSessions();
        } catch (e) {
            console.error(e);
        }
    };

    const handleSelectSession = async (sessionId: string) => {
        try {
            const detail = await getChatSession(sessionId);
            setActiveAgentSession(detail);
        } catch (e) {
            console.error(e);
        }
    };

    const handleDeleteSession = async (e: React.MouseEvent, sessionId: string) => {
        e.stopPropagation();
        try {
            await deleteChatSession(sessionId);
            if (activeAgentSession?.id === sessionId) {
                setActiveAgentSession(null);
            }
            await loadAgentSessions();
        } catch (e) {
            console.error(e);
        }
    };

    const handleRenameSession = async (sessionId: string) => {
        if (!renameValue.trim()) { setRenamingSession(null); return; }
        try {
            await updateChatSession(sessionId, renameValue.trim());
            setRenamingSession(null);
            setRenameValue('');
            await loadAgentSessions();
        } catch (e) {
            console.error(e);
        }
    };

    const handleSend = async () => {
        if (!input.trim() || loading) return;

        let session = activeAgentSession;

        // Auto-create session if none active
        if (!session) {
            try {
                const newSession = await createChatSession('agent', input.slice(0, 50));
                session = await getChatSession(newSession.id);
                setActiveAgentSession(session);
                await loadAgentSessions();
            } catch (e) {
                console.error(e);
                return;
            }
        }

        const currentInput = input;
        setInput('');
        setLoading(true);
        if (textareaRef.current) textareaRef.current.style.height = 'auto';

        // Optimistically add user message
        const tempUserMsg: ParsedAgentMessage = {
            id: `temp-${Date.now()}`,
            role: 'user',
            content: currentInput,
            created_at: new Date().toISOString(),
        };
        setParsedMessages((prev) => [...prev, tempUserMsg]);

        try {
            const result = await runAgent(session.id, currentInput, autoAccept);

            // Add assistant message
            const assistantMsg: ParsedAgentMessage = {
                id: result.message.id,
                role: 'assistant',
                content: result.message.content,
                steps: result.steps,
                proposals: result.proposals,
                created_at: result.message.created_at,
            };
            setParsedMessages((prev) => [...prev, assistantMsg]);

            // If auto-accept applied proposals
            if (autoAccept && result.proposals?.length > 0) {
                const keys = result.proposals.map((_, i) => `${result.message.id}-${i}`);
                setAppliedProposals((prev) => {
                    const next = new Set(prev);
                    keys.forEach((k) => next.add(k));
                    return next;
                });
                loadFolderTree();
            }

            // Refresh session list (title may have been generated)
            await loadAgentSessions();
        } catch (e) {
            console.error(e);
            setParsedMessages((prev) => [
                ...prev,
                {
                    id: `error-${Date.now()}`,
                    role: 'assistant',
                    content: 'Fehler bei der Verarbeitung. Bitte versuche es erneut.',
                    created_at: new Date().toISOString(),
                },
            ]);
        } finally {
            setLoading(false);
        }
    };

    const handleAcceptProposal = async (msgId: string, proposalIndex: number, proposal: AgentProposal) => {
        const key = `${msgId}-${proposalIndex}`;
        try {
            await applyAgentProposals([proposal]);
            setAppliedProposals((prev) => { const n = new Set(prev); n.add(key); return n; });
            loadFolderTree();
        } catch (e) {
            console.error(e);
        }
    };

    const handleRejectProposal = (msgId: string, proposalIndex: number) => {
        const key = `${msgId}-${proposalIndex}`;
        setRejectedProposals((prev) => { const n = new Set(prev); n.add(key); return n; });
    };

    const handleAcceptAll = async (msgId: string, proposals: AgentProposal[]) => {
        const pending = proposals.filter((_, i) => {
            const key = `${msgId}-${i}`;
            return !appliedProposals.has(key) && !rejectedProposals.has(key);
        });
        if (pending.length === 0) return;

        try {
            await applyAgentProposals(pending);
            const keys = proposals.map((_, i) => `${msgId}-${i}`).filter(
                (k) => !appliedProposals.has(k) && !rejectedProposals.has(k)
            );
            setAppliedProposals((prev) => { const n = new Set(prev); keys.forEach((k) => n.add(k)); return n; });
            loadFolderTree();
        } catch (e) {
            console.error(e);
        }
    };

    return (
        <div className="h-full flex flex-col">
            {/* Header */}
            <div className="flex items-center justify-between px-4 sm:px-6 py-4 border-b border-dark-800 bg-dark-900/50">
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
                    <button
                        onClick={handleNewSession}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-dark-800 text-dark-400 border border-dark-700 hover:text-white transition-colors"
                    >
                        <FiPlus className="w-3.5 h-3.5" />
                        Neuer Chat
                    </button>
                    <button
                        onClick={() => setAutoAccept(!autoAccept)}
                        className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${autoAccept
                            ? 'bg-green-600/20 text-green-400 border border-green-600/30'
                            : 'bg-dark-800 text-dark-400 border border-dark-700 hover:text-white'
                            }`}
                    >
                        {autoAccept ? <FiToggleRight className="w-4 h-4" /> : <FiToggleLeft className="w-4 h-4" />}
                        Auto
                    </button>
                </div>
            </div>

            <div className="flex-1 flex overflow-hidden">
                {/* Session list sidebar */}
                <div className="w-56 border-r border-dark-800 overflow-y-auto flex-shrink-0 hidden sm:block">
                    <div className="p-2 space-y-0.5">
                        {agentSessions.map((s) => (
                            <div
                                key={s.id}
                                onClick={() => handleSelectSession(s.id)}
                                className={`group flex items-center gap-2 px-3 py-2 rounded-lg text-sm cursor-pointer transition-colors ${activeAgentSession?.id === s.id
                                    ? 'bg-rose-600/10 text-rose-400 border border-rose-600/20'
                                    : 'text-dark-400 hover:text-white hover:bg-dark-800'
                                    }`}
                            >
                                <FiMessageSquare className="w-3.5 h-3.5 flex-shrink-0" />
                                {renamingSession === s.id ? (
                                    <input
                                        type="text"
                                        value={renameValue}
                                        onChange={(e) => setRenameValue(e.target.value)}
                                        onKeyDown={(e) => {
                                            if (e.key === 'Enter') handleRenameSession(s.id);
                                            if (e.key === 'Escape') { setRenamingSession(null); setRenameValue(''); }
                                        }}
                                        onBlur={() => handleRenameSession(s.id)}
                                        onClick={(e) => e.stopPropagation()}
                                        className="flex-1 px-1 py-0 text-sm bg-dark-950 border border-rose-500 rounded text-white focus:outline-none min-w-0"
                                        autoFocus
                                    />
                                ) : (
                                    <span className="truncate flex-1">{s.title}</span>
                                )}
                                <div className="opacity-0 group-hover:opacity-100 flex gap-0.5">
                                    <button
                                        onClick={(e) => { e.stopPropagation(); setRenamingSession(s.id); setRenameValue(s.title); }}
                                        className="p-1 hover:bg-dark-700 rounded"
                                    >
                                        <FiEdit2 className="w-3 h-3 text-dark-500 hover:text-blue-400" />
                                    </button>
                                    <button
                                        onClick={(e) => handleDeleteSession(e, s.id)}
                                        className="p-1 hover:bg-dark-700 rounded"
                                    >
                                        <FiTrash2 className="w-3 h-3 text-dark-500 hover:text-red-400" />
                                    </button>
                                </div>
                            </div>
                        ))}
                        {agentSessions.length === 0 && (
                            <p className="text-xs text-dark-600 px-3 py-4 text-center">Noch keine Chats</p>
                        )}
                    </div>
                </div>

                {/* Chat area */}
                <div className="flex-1 flex flex-col overflow-hidden">
                    <div className="flex-1 overflow-y-auto p-4 space-y-4">
                        {parsedMessages.length === 0 && !loading && (
                            <div className="h-full flex items-center justify-center">
                                <div className="text-center max-w-md">
                                    <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-dark-800 mb-4">
                                        <FiCpu className="w-8 h-8 text-rose-400/60" />
                                    </div>
                                    <h3 className="text-lg font-semibold text-white mb-2">Agentic Workspace</h3>
                                    <p className="text-sm text-dark-500 mb-4">
                                        Ich kenne alle deine Notizen. Lass uns gemeinsam planen, brainstormen
                                        und bei Bedarf neue Notizen erstellen oder bestehende bearbeiten.
                                    </p>
                                    <div className="grid grid-cols-1 gap-2 text-left">
                                        {[
                                            'Lass uns eine Wohnungsplanung machen',
                                            'Was habe ich zum Thema Produktivität notiert?',
                                            'Hilf mir ein Projekt zu strukturieren',
                                            'Finde Duplikate in meinen Notizen',
                                        ].map((text) => (
                                            <button
                                                key={text}
                                                onClick={() => setInput(text)}
                                                className="text-xs text-left px-3 py-2 bg-dark-800/50 border border-dark-700 rounded-lg text-dark-400 hover:text-white hover:border-rose-600/30 transition-colors"
                                            >
                                                💡 {text}
                                            </button>
                                        ))}
                                    </div>
                                </div>
                            </div>
                        )}

                        {parsedMessages.map((msg) => (
                            <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                                <div className={`max-w-[85%] ${msg.role === 'user'
                                    ? 'bg-rose-900/30 border border-rose-800/30 rounded-2xl px-4 py-3'
                                    : 'space-y-2 w-full max-w-[85%]'
                                    }`}>
                                    {msg.role === 'user' ? (
                                        <p className="text-sm text-white">{msg.content}</p>
                                    ) : (
                                        <>
                                            {/* Steps */}
                                            {msg.steps && msg.steps.length > 0 && (
                                                <div className="bg-dark-800/30 border border-dark-700/50 rounded-xl overflow-hidden">
                                                    <button
                                                        onClick={() => setExpandedSteps((p) => { const n = new Set(p); n.has(msg.id) ? n.delete(msg.id) : n.add(msg.id); return n; })}
                                                        className="flex items-center gap-2 w-full px-3 py-2 text-xs text-dark-400 hover:text-white"
                                                    >
                                                        {expandedSteps.has(msg.id) ? <FiChevronDown className="w-3 h-3" /> : <FiChevronRight className="w-3 h-3" />}
                                                        <FiZap className="w-3 h-3 text-amber-400" />
                                                        {msg.steps.length} Schritte
                                                    </button>
                                                    {expandedSteps.has(msg.id) && (
                                                        <div className="px-3 pb-2 space-y-1">
                                                            {msg.steps.map((step, i) => (
                                                                <div key={i} className="flex items-start gap-2 text-xs text-dark-400">
                                                                    <span>{step.type === 'tool_call' ? '🔧' : step.type === 'tool_result' ? '✅' : '🧠'}</span>
                                                                    <span>{step.content}</span>
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
                                                <div className="space-y-2">
                                                    <div className="flex items-center justify-between px-1">
                                                        <span className="text-xs font-medium text-dark-400">{msg.proposals.length} Vorschläge</span>
                                                        <button
                                                            onClick={() => handleAcceptAll(msg.id, msg.proposals!)}
                                                            className="flex items-center gap-1 px-2.5 py-1 text-xs font-medium bg-green-600 hover:bg-green-500 text-white rounded-lg"
                                                        >
                                                            <FiCheckCircle className="w-3 h-3" /> Alle annehmen
                                                        </button>
                                                    </div>
                                                    {msg.proposals.map((p, i) => (
                                                        <ProposalCard
                                                            key={i}
                                                            proposal={p}
                                                            isApplied={appliedProposals.has(`${msg.id}-${i}`)}
                                                            isRejected={rejectedProposals.has(`${msg.id}-${i}`)}
                                                            onAccept={() => handleAcceptProposal(msg.id, i, p)}
                                                            onReject={() => handleRejectProposal(msg.id, i)}
                                                        />
                                                    ))}
                                                </div>
                                            )}
                                        </>
                                    )}
                                </div>
                            </div>
                        ))}

                        {loading && (
                            <div className="flex justify-start">
                                <div className="bg-dark-800/50 border border-dark-700 rounded-2xl px-4 py-3">
                                    <div className="flex items-center gap-3 text-sm text-dark-400">
                                        <FiLoader className="w-4 h-4 animate-spin text-rose-400" />
                                        Agent denkt nach...
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
                                value={input}
                                onChange={(e) => { setInput(e.target.value); adjustTextarea(); }}
                                onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
                                placeholder="Schreib dem Agent..."
                                className="flex-1 px-4 py-3 bg-dark-800 border border-dark-700 rounded-xl text-white text-sm placeholder-dark-600 focus:outline-none focus:border-rose-500 resize-none min-h-[48px] max-h-[200px]"
                                rows={1}
                            />
                            <button
                                onClick={handleSend}
                                disabled={!input.trim() || loading}
                                className={`p-3 rounded-xl transition-colors ${input.trim() && !loading ? 'bg-rose-600 hover:bg-rose-500 text-white' : 'bg-dark-800 text-dark-600 cursor-not-allowed'}`}
                            >
                                <FiSend className="w-5 h-5" />
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}

function ProposalCard({ proposal, isApplied, isRejected, onAccept, onReject }: {
    proposal: AgentProposal; isApplied: boolean; isRejected: boolean; onAccept: () => void; onReject: () => void;
}) {
    const [expanded, setExpanded] = useState(false);
    const typeConfig = {
        create: { icon: FiFilePlus, label: 'Erstellen', color: 'text-green-400', bg: 'bg-green-600/10 border-green-600/20' },
        update: { icon: FiEdit3, label: 'Bearbeiten', color: 'text-blue-400', bg: 'bg-blue-600/10 border-blue-600/20' },
        delete: { icon: FiTrash2, label: 'Löschen', color: 'text-red-400', bg: 'bg-red-600/10 border-red-600/20' },
    };
    const config = typeConfig[proposal.type];
    const Icon = config.icon;

    return (
        <div className={`border rounded-xl overflow-hidden ${isApplied ? 'border-green-600/30 bg-green-900/10' : isRejected ? 'border-dark-700 opacity-50' : config.bg}`}>
            <div className="flex items-center gap-3 px-4 py-2.5">
                <Icon className={`w-4 h-4 flex-shrink-0 ${config.color}`} />
                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                        <span className={`text-xs font-medium ${config.color}`}>{config.label}</span>
                        <span className="text-sm font-medium text-white truncate">{proposal.title || proposal.new_title || ''}</span>
                    </div>
                    {proposal.folder_path && <p className="text-xs text-dark-500">📁 {proposal.folder_path}</p>}
                    {proposal.reason && <p className="text-xs text-dark-500 italic">{proposal.reason}</p>}
                </div>
                <div className="flex items-center gap-1.5 flex-shrink-0">
                    {(proposal.content || proposal.new_content) && (
                        <button onClick={() => setExpanded(!expanded)} className="p-1.5 hover:bg-dark-700 rounded-lg text-dark-400 hover:text-white">
                            {expanded ? <FiChevronDown className="w-3.5 h-3.5" /> : <FiChevronRight className="w-3.5 h-3.5" />}
                        </button>
                    )}
                    {isApplied ? (
                        <span className="flex items-center gap-1 text-xs text-green-400"><FiCheckCircle className="w-3.5 h-3.5" /> ✓</span>
                    ) : isRejected ? (
                        <span className="text-xs text-dark-500">—</span>
                    ) : (
                        <>
                            <button onClick={onAccept} className="p-1.5 bg-green-600 hover:bg-green-500 text-white rounded-lg"><FiCheck className="w-3.5 h-3.5" /></button>
                            <button onClick={onReject} className="p-1.5 bg-red-600/20 hover:bg-red-600/40 text-red-400 rounded-lg"><FiX className="w-3.5 h-3.5" /></button>
                        </>
                    )}
                </div>
            </div>
            {expanded && (proposal.content || proposal.new_content) && (
                <div className="border-t border-dark-700 px-4 py-3 max-h-60 overflow-y-auto">
                    <div className="markdown-content text-xs text-dark-300">
                        <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins} components={markdownComponents}>
                            {proposal.content || proposal.new_content || ''}
                        </ReactMarkdown>
                    </div>
                    {proposal.tags && proposal.tags.length > 0 && (
                        <div className="flex gap-1.5 mt-2 flex-wrap">
                            {proposal.tags.map((tag) => (<span key={tag} className="px-2 py-0.5 text-xs bg-dark-700 text-dark-300 rounded-full">{tag}</span>))}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
