'use client';

import { useState, useRef, useEffect } from 'react';
import {
    FiSend, FiCheck, FiX, FiCheckCircle, FiCpu,
    FiChevronDown, FiChevronRight, FiZap, FiLoader,
    FiFilePlus, FiEdit3, FiTrash2, FiToggleLeft, FiToggleRight,
} from 'react-icons/fi';
import ReactMarkdown from 'react-markdown';
import { markdownComponents, remarkPlugins, rehypePlugins } from '@/lib/markdownComponents';
import { runAgent, applyAgentProposals } from '@/lib/api';
import { useStore } from '@/lib/store';
import type { AgentStep, AgentProposal } from '@/lib/types';

interface ChatMessage {
    id: string;
    role: 'user' | 'assistant';
    content: string;
    steps?: AgentStep[];
    proposals?: AgentProposal[];
    appliedProposals: Set<number>;
    rejectedProposals: Set<number>;
}

export default function AgentView() {
    const { loadFolderTree } = useStore();
    const [input, setInput] = useState('');
    const [loading, setLoading] = useState(false);
    const [autoAccept, setAutoAccept] = useState(false);
    const [messages, setMessages] = useState<ChatMessage[]>([]);
    const [expandedSteps, setExpandedSteps] = useState<Set<string>>(new Set());
    const messagesEndRef = useRef<HTMLDivElement>(null);
    const textareaRef = useRef<HTMLTextAreaElement>(null);

    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [messages, loading]);

    const adjustTextarea = () => {
        const textarea = textareaRef.current;
        if (textarea) {
            textarea.style.height = 'auto';
            textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`;
        }
    };

    const handleSend = async () => {
        if (!input.trim() || loading) return;

        const userMessage: ChatMessage = {
            id: `msg-${Date.now()}`,
            role: 'user',
            content: input.trim(),
            appliedProposals: new Set(),
            rejectedProposals: new Set(),
        };

        const currentInput = input;
        setMessages((prev) => [...prev, userMessage]);
        setInput('');
        setLoading(true);
        if (textareaRef.current) textareaRef.current.style.height = 'auto';

        try {
            // Build chat history from messages
            const history = messages.map((m) => ({
                role: m.role,
                content: m.content,
            }));

            const result = await runAgent(currentInput, history, autoAccept);

            const assistantMessage: ChatMessage = {
                id: `msg-${Date.now()}-reply`,
                role: 'assistant',
                content: result.response || '',
                steps: result.steps,
                proposals: result.proposals,
                appliedProposals: autoAccept ? new Set(result.proposals?.map((_, i) => i) || []) : new Set(),
                rejectedProposals: new Set(),
            };

            setMessages((prev) => [...prev, assistantMessage]);

            if (autoAccept && result.apply_result && result.apply_result.applied > 0) {
                loadFolderTree();
            }
        } catch (e) {
            console.error(e);
            const errorMessage: ChatMessage = {
                id: `msg-${Date.now()}-error`,
                role: 'assistant',
                content: 'Es gab einen Fehler bei der Verarbeitung. Bitte versuche es erneut.',
                appliedProposals: new Set(),
                rejectedProposals: new Set(),
            };
            setMessages((prev) => [...prev, errorMessage]);
        } finally {
            setLoading(false);
        }
    };

    const handleAcceptProposal = async (msgId: string, proposalIndex: number) => {
        const msg = messages.find((m) => m.id === msgId);
        if (!msg || !msg.proposals) return;

        const proposal = msg.proposals[proposalIndex];
        try {
            await applyAgentProposals([proposal]);
            setMessages((prev) =>
                prev.map((m) => {
                    if (m.id === msgId) {
                        const newApplied = new Set(m.appliedProposals);
                        newApplied.add(proposalIndex);
                        return { ...m, appliedProposals: newApplied };
                    }
                    return m;
                })
            );
            loadFolderTree();
        } catch (e) {
            console.error(e);
        }
    };

    const handleRejectProposal = (msgId: string, proposalIndex: number) => {
        setMessages((prev) =>
            prev.map((m) => {
                if (m.id === msgId) {
                    const newRejected = new Set(m.rejectedProposals);
                    newRejected.add(proposalIndex);
                    return { ...m, rejectedProposals: newRejected };
                }
                return m;
            })
        );
    };

    const handleAcceptAll = async (msgId: string) => {
        const msg = messages.find((m) => m.id === msgId);
        if (!msg || !msg.proposals) return;

        const pending = msg.proposals.filter(
            (_, i) => !msg.appliedProposals.has(i) && !msg.rejectedProposals.has(i)
        );
        const pendingIndices = msg.proposals
            .map((_, i) => i)
            .filter((i) => !msg.appliedProposals.has(i) && !msg.rejectedProposals.has(i));

        if (pending.length === 0) return;

        try {
            await applyAgentProposals(pending);
            setMessages((prev) =>
                prev.map((m) => {
                    if (m.id === msgId) {
                        const newApplied = new Set(m.appliedProposals);
                        pendingIndices.forEach((i) => newApplied.add(i));
                        return { ...m, appliedProposals: newApplied };
                    }
                    return m;
                })
            );
            loadFolderTree();
        } catch (e) {
            console.error(e);
        }
    };

    const toggleSteps = (msgId: string) => {
        setExpandedSteps((prev) => {
            const next = new Set(prev);
            if (next.has(msgId)) next.delete(msgId);
            else next.add(msgId);
            return next;
        });
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
                <button
                    onClick={() => setAutoAccept(!autoAccept)}
                    className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${autoAccept
                        ? 'bg-green-600/20 text-green-400 border border-green-600/30'
                        : 'bg-dark-800 text-dark-400 border border-dark-700 hover:text-white'
                        }`}
                    title={autoAccept ? 'Auto-Accept AN: Änderungen werden sofort angewendet' : 'Auto-Accept AUS: Du bestätigst jede Änderung'}
                >
                    {autoAccept ? <FiToggleRight className="w-4 h-4" /> : <FiToggleLeft className="w-4 h-4" />}
                    Auto-Accept
                </button>
            </div>

            {/* Messages */}
            <div className="flex-1 overflow-y-auto p-4 space-y-4">
                {messages.length === 0 && !loading && (
                    <div className="h-full flex items-center justify-center">
                        <div className="text-center max-w-md">
                            <div className="inline-flex items-center justify-center w-20 h-20 rounded-2xl bg-dark-800 mb-6">
                                <FiCpu className="w-10 h-10 text-rose-400/60" />
                            </div>
                            <h3 className="text-xl font-semibold text-white mb-2">Agentic Workspace</h3>
                            <p className="text-sm text-dark-500 mb-6">
                                Ich bin dein Agent — ich kenne alle deine Notizen und kann mit dir brainstormen,
                                planen, recherchieren und bei Bedarf Notizen erstellen oder bearbeiten.
                            </p>
                            <div className="grid grid-cols-1 gap-2 text-left">
                                {[
                                    'Lass uns eine Wohnungsplanung machen — was brauche ich alles?',
                                    'Was habe ich bisher über Produktivität notiert?',
                                    'Hilf mir ein Projekt zu planen basierend auf meinen Notizen',
                                    'Gibt es Duplikate oder ähnliche Notizen die ich zusammenführen könnte?',
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

                {messages.map((msg) => (
                    <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                        <div className={`max-w-[85%] ${msg.role === 'user'
                            ? 'bg-rose-900/30 border border-rose-800/30 rounded-2xl px-4 py-3'
                            : 'space-y-3 w-full'
                            }`}>
                            {msg.role === 'user' ? (
                                <p className="text-sm text-white">{msg.content}</p>
                            ) : (
                                <>
                                    {/* Steps indicator */}
                                    {msg.steps && msg.steps.length > 0 && (
                                        <div className="bg-dark-800/30 border border-dark-700/50 rounded-xl overflow-hidden">
                                            <button
                                                onClick={() => toggleSteps(msg.id)}
                                                className="flex items-center gap-2 w-full px-3 py-2 text-xs font-medium text-dark-400 hover:text-white transition-colors"
                                            >
                                                {expandedSteps.has(msg.id) ? <FiChevronDown className="w-3 h-3" /> : <FiChevronRight className="w-3 h-3" />}
                                                <FiZap className="w-3 h-3 text-amber-400" />
                                                {msg.steps.length} Schritte ausgeführt
                                            </button>
                                            {expandedSteps.has(msg.id) && (
                                                <div className="px-3 pb-2 space-y-1">
                                                    {msg.steps.map((step, i) => (
                                                        <div key={i} className="flex items-start gap-2 text-xs text-dark-400">
                                                            <span className="flex-shrink-0">
                                                                {step.type === 'tool_call' ? '🔧' : step.type === 'tool_result' ? '✅' : '🧠'}
                                                            </span>
                                                            <span>{step.content}</span>
                                                        </div>
                                                    ))}
                                                </div>
                                            )}
                                        </div>
                                    )}

                                    {/* Response text */}
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
                                                <span className="text-xs font-medium text-dark-400">
                                                    {msg.proposals.length} Vorschläge
                                                </span>
                                                {!autoAccept && (
                                                    <button
                                                        onClick={() => handleAcceptAll(msg.id)}
                                                        className="flex items-center gap-1 px-2.5 py-1 text-xs font-medium bg-green-600 hover:bg-green-500 text-white rounded-lg transition-colors"
                                                    >
                                                        <FiCheckCircle className="w-3 h-3" />
                                                        Alle annehmen
                                                    </button>
                                                )}
                                            </div>
                                            {msg.proposals.map((proposal, i) => (
                                                <ProposalCard
                                                    key={i}
                                                    proposal={proposal}
                                                    isApplied={msg.appliedProposals.has(i)}
                                                    isRejected={msg.rejectedProposals.has(i)}
                                                    isAutoAccepted={autoAccept && msg.appliedProposals.has(i)}
                                                    onAccept={() => handleAcceptProposal(msg.id, i)}
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
                        onKeyDown={(e) => {
                            if (e.key === 'Enter' && !e.shiftKey) {
                                e.preventDefault();
                                handleSend();
                            }
                        }}
                        placeholder="Schreib dem Agent... (z.B. 'Lass uns eine Umzugsplanung machen')"
                        className="flex-1 px-4 py-3 bg-dark-800 border border-dark-700 rounded-xl text-white text-sm placeholder-dark-600 focus:outline-none focus:border-rose-500 resize-none min-h-[48px] max-h-[200px]"
                        rows={1}
                    />
                    <button
                        onClick={handleSend}
                        disabled={!input.trim() || loading}
                        className={`p-3 rounded-xl transition-colors ${input.trim() && !loading
                            ? 'bg-rose-600 hover:bg-rose-500 text-white'
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

// ── Proposal Card ────────────────────────────────────────────────────

function ProposalCard({
    proposal,
    isApplied,
    isRejected,
    isAutoAccepted,
    onAccept,
    onReject,
}: {
    proposal: AgentProposal;
    isApplied: boolean;
    isRejected: boolean;
    isAutoAccepted: boolean;
    onAccept: () => void;
    onReject: () => void;
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
        <div className={`border rounded-xl overflow-hidden transition-colors ${isApplied || isAutoAccepted ? 'border-green-600/30 bg-green-900/10' : isRejected ? 'border-dark-700 opacity-50' : config.bg}`}>
            <div className="flex items-center gap-3 px-4 py-2.5">
                <Icon className={`w-4 h-4 flex-shrink-0 ${config.color}`} />
                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                        <span className={`text-xs font-medium ${config.color}`}>{config.label}</span>
                        <span className="text-sm font-medium text-white truncate">
                            {proposal.title || proposal.new_title || ''}
                        </span>
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
                    {isApplied || isAutoAccepted ? (
                        <span className="flex items-center gap-1 text-xs text-green-400"><FiCheckCircle className="w-3.5 h-3.5" /> Angewendet</span>
                    ) : isRejected ? (
                        <span className="text-xs text-dark-500">Abgelehnt</span>
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
                            {proposal.tags.map((tag) => (
                                <span key={tag} className="px-2 py-0.5 text-xs bg-dark-700 text-dark-300 rounded-full">{tag}</span>
                            ))}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
