'use client';

import { useState, useRef, useEffect } from 'react';
import {
    FiSend, FiCheck, FiX, FiCheckCircle, FiCpu,
    FiChevronDown, FiChevronRight, FiZap, FiLoader,
    FiFile, FiFilePlus, FiEdit3, FiTrash2, FiToggleLeft, FiToggleRight,
} from 'react-icons/fi';
import ReactMarkdown from 'react-markdown';
import { markdownComponents, remarkPlugins, rehypePlugins } from '@/lib/markdownComponents';
import { runAgent, applyAgentProposals } from '@/lib/api';
import { useStore } from '@/lib/store';
import type { AgentStep, AgentProposal, AgentRunResult } from '@/lib/types';

interface HistoryEntry {
    id: string;
    instruction: string;
    result: AgentRunResult;
    appliedProposals: Set<number>;
    rejectedProposals: Set<number>;
    timestamp: Date;
}

export default function AgentView() {
    const { loadFolderTree } = useStore();
    const [instruction, setInstruction] = useState('');
    const [loading, setLoading] = useState(false);
    const [autoAccept, setAutoAccept] = useState(false);
    const [history, setHistory] = useState<HistoryEntry[]>([]);
    const [expandedSteps, setExpandedSteps] = useState<Set<string>>(new Set());
    const [applyingAll, setApplyingAll] = useState(false);
    const messagesEndRef = useRef<HTMLDivElement>(null);
    const textareaRef = useRef<HTMLTextAreaElement>(null);

    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [history, loading]);

    const adjustTextarea = () => {
        const textarea = textareaRef.current;
        if (textarea) {
            textarea.style.height = 'auto';
            textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`;
        }
    };

    const handleRun = async () => {
        if (!instruction.trim() || loading) return;

        const currentInstruction = instruction;
        setInstruction('');
        setLoading(true);
        if (textareaRef.current) textareaRef.current.style.height = 'auto';

        try {
            const result = await runAgent(currentInstruction, autoAccept);
            const entry: HistoryEntry = {
                id: `entry-${Date.now()}`,
                instruction: currentInstruction,
                result,
                appliedProposals: autoAccept ? new Set(result.proposals.map((_, i) => i)) : new Set(),
                rejectedProposals: new Set(),
                timestamp: new Date(),
            };
            setHistory((prev) => [...prev, entry]);

            // If auto-accept was used and proposals were applied, refresh folder tree
            if (autoAccept && result.apply_result && result.apply_result.applied > 0) {
                loadFolderTree();
            }
        } catch (e) {
            console.error(e);
            const errorEntry: HistoryEntry = {
                id: `entry-${Date.now()}`,
                instruction: currentInstruction,
                result: {
                    steps: [{ type: 'error', content: 'Fehler bei der Agent-Ausführung. Bitte versuche es erneut.' }],
                    proposals: [],
                    summary: '',
                    auto_accept: false,
                },
                appliedProposals: new Set(),
                rejectedProposals: new Set(),
                timestamp: new Date(),
            };
            setHistory((prev) => [...prev, errorEntry]);
        } finally {
            setLoading(false);
        }
    };

    const handleAcceptProposal = async (entryId: string, proposalIndex: number) => {
        const entry = history.find((h) => h.id === entryId);
        if (!entry) return;

        const proposal = entry.result.proposals[proposalIndex];
        try {
            await applyAgentProposals([proposal]);
            setHistory((prev) =>
                prev.map((h) => {
                    if (h.id === entryId) {
                        const newApplied = new Set(h.appliedProposals);
                        newApplied.add(proposalIndex);
                        return { ...h, appliedProposals: newApplied };
                    }
                    return h;
                })
            );
            loadFolderTree();
        } catch (e) {
            console.error(e);
        }
    };

    const handleRejectProposal = (entryId: string, proposalIndex: number) => {
        setHistory((prev) =>
            prev.map((h) => {
                if (h.id === entryId) {
                    const newRejected = new Set(h.rejectedProposals);
                    newRejected.add(proposalIndex);
                    return { ...h, rejectedProposals: newRejected };
                }
                return h;
            })
        );
    };

    const handleAcceptAll = async (entryId: string) => {
        const entry = history.find((h) => h.id === entryId);
        if (!entry) return;

        const pendingProposals = entry.result.proposals.filter(
            (_, i) => !entry.appliedProposals.has(i) && !entry.rejectedProposals.has(i)
        );
        const pendingIndices = entry.result.proposals
            .map((_, i) => i)
            .filter((i) => !entry.appliedProposals.has(i) && !entry.rejectedProposals.has(i));

        if (pendingProposals.length === 0) return;

        setApplyingAll(true);
        try {
            await applyAgentProposals(pendingProposals);
            setHistory((prev) =>
                prev.map((h) => {
                    if (h.id === entryId) {
                        const newApplied = new Set(h.appliedProposals);
                        pendingIndices.forEach((i) => newApplied.add(i));
                        return { ...h, appliedProposals: newApplied };
                    }
                    return h;
                })
            );
            loadFolderTree();
        } catch (e) {
            console.error(e);
        } finally {
            setApplyingAll(false);
        }
    };

    const toggleSteps = (entryId: string) => {
        setExpandedSteps((prev) => {
            const next = new Set(prev);
            if (next.has(entryId)) next.delete(entryId);
            else next.add(entryId);
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
                        <p className="text-xs text-dark-500">Agentic Workspace — plane, suche, erstelle & bearbeite Notizen</p>
                    </div>
                </div>
                <button
                    onClick={() => setAutoAccept(!autoAccept)}
                    className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${autoAccept
                        ? 'bg-green-600/20 text-green-400 border border-green-600/30'
                        : 'bg-dark-800 text-dark-400 border border-dark-700 hover:text-white'
                        }`}
                    title={autoAccept ? 'Auto-Accept AN: Änderungen werden sofort angewendet' : 'Auto-Accept AUS: Änderungen müssen manuell bestätigt werden'}
                >
                    {autoAccept ? <FiToggleRight className="w-4 h-4" /> : <FiToggleLeft className="w-4 h-4" />}
                    Auto-Accept
                </button>
            </div>

            {/* Content / History */}
            <div className="flex-1 overflow-y-auto p-4 space-y-6">
                {history.length === 0 && !loading && (
                    <div className="h-full flex items-center justify-center">
                        <div className="text-center max-w-md">
                            <div className="inline-flex items-center justify-center w-20 h-20 rounded-2xl bg-dark-800 mb-6">
                                <FiCpu className="w-10 h-10 text-rose-400/60" />
                            </div>
                            <h3 className="text-xl font-semibold text-white mb-2">Agentic Workspace</h3>
                            <p className="text-sm text-dark-500 mb-4">
                                Beschreibe was du planst oder tun möchtest. Der Agent durchsucht deine Notizen,
                                liest relevante Inhalte, und erstellt Vorschläge zum Erstellen, Bearbeiten oder Löschen von Notizen.
                            </p>
                            <div className="grid grid-cols-1 gap-2 text-left">
                                <ExamplePrompt text="Erstelle eine Wohnungsplanung mit Checkliste und Budgetübersicht" onClick={setInstruction} />
                                <ExamplePrompt text="Fasse alle meine Notizen zum Thema Produktivität zusammen und erstelle eine Meta-Notiz" onClick={setInstruction} />
                                <ExamplePrompt text="Räume meine Notizen auf — finde Duplikate und schlage Zusammenführungen vor" onClick={setInstruction} />
                                <ExamplePrompt text="Erstelle eine Projektplanung basierend auf meinen bestehenden Projektnotizen" onClick={setInstruction} />
                            </div>
                        </div>
                    </div>
                )}

                {history.map((entry) => (
                    <div key={entry.id} className="space-y-3">
                        {/* User instruction */}
                        <div className="flex justify-end">
                            <div className="max-w-[80%] bg-rose-900/30 border border-rose-800/30 rounded-2xl px-4 py-3">
                                <p className="text-sm text-white">{entry.instruction}</p>
                            </div>
                        </div>

                        {/* Agent response */}
                        <div className="bg-dark-800/50 border border-dark-700 rounded-2xl overflow-hidden">
                            {/* Steps / Thinking toggle */}
                            {entry.result.steps.length > 0 && (
                                <div className="border-b border-dark-700">
                                    <button
                                        onClick={() => toggleSteps(entry.id)}
                                        className="flex items-center gap-2 w-full px-4 py-2.5 text-xs font-medium text-dark-400 hover:text-white transition-colors"
                                    >
                                        {expandedSteps.has(entry.id) ? (
                                            <FiChevronDown className="w-3.5 h-3.5" />
                                        ) : (
                                            <FiChevronRight className="w-3.5 h-3.5" />
                                        )}
                                        <FiZap className="w-3.5 h-3.5 text-amber-400" />
                                        {entry.result.steps.length} Schritte ausgeführt
                                    </button>

                                    {expandedSteps.has(entry.id) && (
                                        <div className="px-4 pb-3 space-y-1.5">
                                            {entry.result.steps.map((step, i) => (
                                                <StepDisplay key={i} step={step} />
                                            ))}
                                        </div>
                                    )}
                                </div>
                            )}

                            {/* Summary */}
                            {entry.result.summary && (
                                <div className="px-4 py-3 border-b border-dark-700">
                                    <p className="text-sm text-dark-300">{entry.result.summary}</p>
                                </div>
                            )}

                            {/* Proposals */}
                            {entry.result.proposals.length > 0 && (
                                <div className="p-4 space-y-3">
                                    <div className="flex items-center justify-between">
                                        <h4 className="text-xs font-semibold text-dark-400 uppercase tracking-wider">
                                            {entry.result.proposals.length} Vorschläge
                                        </h4>
                                        {!entry.result.auto_accept && (
                                            <button
                                                onClick={() => handleAcceptAll(entry.id)}
                                                disabled={applyingAll}
                                                className="flex items-center gap-1.5 px-3 py-1 text-xs font-medium bg-green-600 hover:bg-green-500 text-white rounded-lg transition-colors disabled:opacity-50"
                                            >
                                                <FiCheckCircle className="w-3.5 h-3.5" />
                                                Alle annehmen
                                            </button>
                                        )}
                                    </div>

                                    {entry.result.proposals.map((proposal, i) => (
                                        <ProposalCard
                                            key={i}
                                            proposal={proposal}
                                            index={i}
                                            entryId={entry.id}
                                            isApplied={entry.appliedProposals.has(i)}
                                            isRejected={entry.rejectedProposals.has(i)}
                                            isAutoAccepted={entry.result.auto_accept}
                                            onAccept={() => handleAcceptProposal(entry.id, i)}
                                            onReject={() => handleRejectProposal(entry.id, i)}
                                        />
                                    ))}
                                </div>
                            )}

                            {entry.result.proposals.length === 0 && !entry.result.summary && (
                                <div className="px-4 py-3">
                                    <p className="text-sm text-dark-500 italic">Keine Vorschläge generiert.</p>
                                </div>
                            )}
                        </div>
                    </div>
                ))}

                {/* Loading state */}
                {loading && (
                    <div className="flex justify-start">
                        <div className="bg-dark-800/50 border border-dark-700 rounded-2xl px-4 py-3">
                            <div className="flex items-center gap-3 text-sm text-dark-400">
                                <FiLoader className="w-4 h-4 animate-spin text-rose-400" />
                                <span>Agent arbeitet...</span>
                            </div>
                            <div className="mt-2 flex gap-1">
                                <div className="w-2 h-2 bg-rose-500 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                                <div className="w-2 h-2 bg-rose-500 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                                <div className="w-2 h-2 bg-rose-500 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
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
                        value={instruction}
                        onChange={(e) => {
                            setInstruction(e.target.value);
                            adjustTextarea();
                        }}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter' && !e.shiftKey) {
                                e.preventDefault();
                                handleRun();
                            }
                        }}
                        placeholder="Was soll der Agent tun? z.B. 'Erstelle eine Projektplanung für meinen Umzug basierend auf meinen bestehenden Notizen'"
                        className="flex-1 px-4 py-3 bg-dark-800 border border-dark-700 rounded-xl text-white text-sm placeholder-dark-600 focus:outline-none focus:border-rose-500 resize-none min-h-[80px] max-h-[200px]"
                        rows={3}
                    />
                    <button
                        onClick={handleRun}
                        disabled={!instruction.trim() || loading}
                        className={`p-3 rounded-xl transition-colors ${instruction.trim() && !loading
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

// ── Sub-components ───────────────────────────────────────────────────

function ExamplePrompt({ text, onClick }: { text: string; onClick: (t: string) => void }) {
    return (
        <button
            onClick={() => onClick(text)}
            className="text-xs text-left px-3 py-2 bg-dark-800/50 border border-dark-700 rounded-lg text-dark-400 hover:text-white hover:border-rose-600/30 transition-colors"
        >
            💡 {text}
        </button>
    );
}

function StepDisplay({ step }: { step: AgentStep }) {
    const icons = {
        thinking: '🧠',
        tool_call: '🔧',
        tool_result: '✅',
        done: '🏁',
        error: '❌',
    };
    const colors = {
        thinking: 'text-purple-400',
        tool_call: 'text-blue-400',
        tool_result: 'text-green-400',
        done: 'text-white',
        error: 'text-red-400',
    };

    return (
        <div className={`flex items-start gap-2 text-xs ${colors[step.type]}`}>
            <span className="flex-shrink-0">{icons[step.type]}</span>
            <span className="opacity-80">{step.content}</span>
        </div>
    );
}

function ProposalCard({
    proposal,
    index,
    entryId,
    isApplied,
    isRejected,
    isAutoAccepted,
    onAccept,
    onReject,
}: {
    proposal: AgentProposal;
    index: number;
    entryId: string;
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
        <div className={`border rounded-xl overflow-hidden transition-colors ${isApplied ? 'border-green-600/30 bg-green-900/10' : isRejected ? 'border-dark-700 bg-dark-900/50 opacity-50' : config.bg
            }`}>
            {/* Header */}
            <div className="flex items-center gap-3 px-4 py-3">
                <Icon className={`w-4 h-4 flex-shrink-0 ${config.color}`} />
                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                        <span className={`text-xs font-medium ${config.color}`}>{config.label}</span>
                        <span className="text-sm font-medium text-white truncate">
                            {proposal.title || proposal.new_title || proposal.note_id?.slice(0, 8) || ''}
                        </span>
                    </div>
                    {proposal.folder_path && (
                        <p className="text-xs text-dark-500 mt-0.5">📁 {proposal.folder_path}</p>
                    )}
                    {proposal.reason && (
                        <p className="text-xs text-dark-500 mt-0.5 italic">{proposal.reason}</p>
                    )}
                </div>

                <div className="flex items-center gap-2 flex-shrink-0">
                    {/* Toggle content preview */}
                    {(proposal.content || proposal.new_content) && (
                        <button
                            onClick={() => setExpanded(!expanded)}
                            className="p-1.5 hover:bg-dark-700 rounded-lg transition-colors text-dark-400 hover:text-white"
                        >
                            {expanded ? <FiChevronDown className="w-3.5 h-3.5" /> : <FiChevronRight className="w-3.5 h-3.5" />}
                        </button>
                    )}

                    {/* Status / Actions */}
                    {isApplied || isAutoAccepted ? (
                        <span className="flex items-center gap-1 text-xs text-green-400">
                            <FiCheckCircle className="w-3.5 h-3.5" />
                            Angewendet
                        </span>
                    ) : isRejected ? (
                        <span className="text-xs text-dark-500 italic">Abgelehnt</span>
                    ) : (
                        <>
                            <button
                                onClick={onAccept}
                                className="p-1.5 bg-green-600 hover:bg-green-500 text-white rounded-lg transition-colors"
                                title="Annehmen"
                            >
                                <FiCheck className="w-3.5 h-3.5" />
                            </button>
                            <button
                                onClick={onReject}
                                className="p-1.5 bg-red-600/20 hover:bg-red-600/40 text-red-400 rounded-lg transition-colors"
                                title="Ablehnen"
                            >
                                <FiX className="w-3.5 h-3.5" />
                            </button>
                        </>
                    )}
                </div>
            </div>

            {/* Expanded content preview */}
            {expanded && (proposal.content || proposal.new_content) && (
                <div className="border-t border-dark-700 px-4 py-3 max-h-80 overflow-y-auto">
                    <div className="markdown-content text-xs text-dark-300">
                        <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins} components={markdownComponents}>
                            {proposal.content || proposal.new_content || ''}
                        </ReactMarkdown>
                    </div>
                    {proposal.tags && proposal.tags.length > 0 && (
                        <div className="flex gap-1.5 mt-3 flex-wrap">
                            {proposal.tags.map((tag) => (
                                <span key={tag} className="px-2 py-0.5 text-xs bg-dark-700 text-dark-300 rounded-full">
                                    {tag}
                                </span>
                            ))}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
