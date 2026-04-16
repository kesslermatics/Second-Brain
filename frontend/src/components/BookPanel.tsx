'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import {
    FiSearch, FiCheck, FiX, FiBook, FiChevronRight, FiLoader,
    FiSquare, FiCheckSquare, FiPlus, FiTrash2, FiSend, FiZap,
    FiArrowUp, FiList,
} from 'react-icons/fi';
import { LuBrain } from 'react-icons/lu';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { markdownComponents } from '@/lib/markdownComponents';
import { useStore } from '@/lib/store';
import {
    searchBook, getBookToc, generateChapterNote, generateTopicNote,
    aiEditBookContent, ensureFolderPath, createNote,
    getUserState, putUserState, deleteUserState,
} from '@/lib/api';
import type { BookSearchResult, BookChapter, BookChapterNoteResult } from '@/lib/types';

type Step = 'search' | 'confirm-book' | 'confirm-toc' | 'generating' | 'done';

const STATE_KEY = 'book-generation-state';

// ── Persisted state type ─────────────────────────────────────────────
interface PersistedState {
    step: Step;
    query: string;
    bookInfo: BookSearchResult | null;
    chapters: BookChapter[];
    enabledChapters: Record<string, boolean>;
    currentEnabledIdx: number;
    completedCount: number;
    skippedCount: number;
    topicQueue: string[];
}

function saveState(state: PersistedState) {
    putUserState(STATE_KEY, JSON.stringify(state)).catch(() => {});
}

async function loadPersistedState(): Promise<PersistedState | null> {
    try {
        const raw = await getUserState(STATE_KEY);
        if (!raw) return null;
        return JSON.parse(raw) as PersistedState;
    } catch {
        return null;
    }
}

function clearState() {
    deleteUserState(STATE_KEY).catch(() => {});
}

// ── What is currently being generated ────────────────────────────────
type GeneratingSource =
    | { kind: 'chapter'; idx: number }
    | { kind: 'topic'; topic: string };

export default function BookPanel() {
    // ── State ────────────────────────────────────────────────────────
    const [step, setStep] = useState<Step>('search');
    const [query, setQuery] = useState('');
    const [searching, setSearching] = useState(false);
    const [bookInfo, setBookInfo] = useState<BookSearchResult | null>(null);
    const [chapters, setChapters] = useState<BookChapter[]>([]);
    const [enabledChapters, setEnabledChapters] = useState<Record<string, boolean>>({});
    const [loadingToc, setLoadingToc] = useState(false);
    const [currentEnabledIdx, setCurrentEnabledIdx] = useState(0);
    const [currentNote, setCurrentNote] = useState<BookChapterNoteResult | null>(null);
    const [generatingSource, setGeneratingSource] = useState<GeneratingSource | null>(null);
    const [generatingNote, setGeneratingNote] = useState(false);
    const [completedCount, setCompletedCount] = useState(0);
    const [skippedCount, setSkippedCount] = useState(0);
    const [error, setError] = useState<string | null>(null);
    const [savingNote, setSavingNote] = useState(false);
    const [restored, setRestored] = useState(false);

    // Topic queue
    const [topicQueue, setTopicQueue] = useState<string[]>([]);
    const [topicInput, setTopicInput] = useState('');

    // AI edit
    const [aiEditMode, setAiEditMode] = useState(false);
    const [aiEditInstruction, setAiEditInstruction] = useState('');
    const [aiEditing, setAiEditing] = useState(false);

    // Mobile: toggle queue panel visibility
    const [showQueueMobile, setShowQueueMobile] = useState(false);

    const scrollRef = useRef<HTMLDivElement>(null);
    const topicInputRef = useRef<HTMLInputElement>(null);
    const { loadFolderTree } = useStore();

    // Derived
    const enabledChapterList = chapters.filter(
        (ch) => enabledChapters[ch.chapter_number] !== false
    );
    const totalEnabled = enabledChapterList.length;

    // ── Persist state on every meaningful change ─────────────────────
    const persist = useCallback(() => {
        if (step === 'search' || step === 'done') {
            clearState();
            return;
        }
        saveState({
            step,
            query,
            bookInfo,
            chapters,
            enabledChapters,
            currentEnabledIdx,
            completedCount,
            skippedCount,
            topicQueue,
        });
    }, [step, query, bookInfo, chapters, enabledChapters, currentEnabledIdx, completedCount, skippedCount, topicQueue]);

    useEffect(() => {
        if (restored) persist();
    }, [persist, restored]);

    // ── Restore state on mount ───────────────────────────────────────
    useEffect(() => {
        const restore = async () => {
            const saved = await loadPersistedState();
            if (saved) {
                setStep(saved.step);
                setQuery(saved.query);
                setBookInfo(saved.bookInfo);
                setChapters(saved.chapters);
                setEnabledChapters(saved.enabledChapters);
                setCurrentEnabledIdx(saved.currentEnabledIdx);
                setCompletedCount(saved.completedCount);
                setSkippedCount(saved.skippedCount);
                if (saved.topicQueue) setTopicQueue(saved.topicQueue);
            }
            setRestored(true);
        };
        restore();
    }, []);

    useEffect(() => {
        scrollRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [step, currentEnabledIdx, currentNote]);

    // ── Auto-resume generation after restore ─────────────────────────
    useEffect(() => {
        if (restored && step === 'generating' && !generatingNote && !currentNote && !error) {
            advanceGeneration(currentEnabledIdx, topicQueue);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [restored]);

    // ── Chapter checkbox helpers ─────────────────────────────────────
    const toggleChapter = (chapterNumber: string) => {
        setEnabledChapters((prev) => ({
            ...prev,
            [chapterNumber]: prev[chapterNumber] === false ? true : false,
        }));
    };
    const selectAll = () => {
        const next: Record<string, boolean> = {};
        chapters.forEach((ch) => { next[ch.chapter_number] = true; });
        setEnabledChapters(next);
    };
    const deselectAll = () => {
        const next: Record<string, boolean> = {};
        chapters.forEach((ch) => { next[ch.chapter_number] = false; });
        setEnabledChapters(next);
    };

    // ── Topic queue helpers ──────────────────────────────────────────
    const addTopic = () => {
        const t = topicInput.trim();
        if (!t) return;
        if (topicQueue.includes(t)) { setTopicInput(''); return; }
        setTopicQueue((prev) => [...prev, t]);
        setTopicInput('');
        topicInputRef.current?.focus();
    };
    const removeTopic = (idx: number) => {
        setTopicQueue((prev) => prev.filter((_, i) => i !== idx));
    };
    const moveTopic = (idx: number, direction: 'up') => {
        if (idx <= 0) return;
        setTopicQueue((prev) => {
            const next = [...prev];
            [next[idx - 1], next[idx]] = [next[idx], next[idx - 1]];
            return next;
        });
    };

    // ── Core generation logic ────────────────────────────────────────
    // Decide what to generate next: topic from queue has priority, else next chapter
    const advanceGeneration = async (chapterIdx: number, queue: string[]) => {
        if (queue.length > 0) {
            // Generate from topic queue first
            const topic = queue[0];
            setGeneratingSource({ kind: 'topic', topic });
            await doGenerateTopicNote(topic);
        } else if (chapterIdx < enabledChapterList.length) {
            // Next chapter
            setGeneratingSource({ kind: 'chapter', idx: chapterIdx });
            await doGenerateChapterNote(chapterIdx);
        } else {
            // All done
            setStep('done');
            clearState();
        }
    };

    const doGenerateChapterNote = async (idx: number) => {
        const enabled = chapters.filter((ch) => enabledChapters[ch.chapter_number] !== false);
        if (idx >= enabled.length) {
            setStep('done');
            clearState();
            return;
        }
        setCurrentEnabledIdx(idx);
        setGeneratingNote(true);
        setCurrentNote(null);
        setError(null);
        try {
            const chapter = enabled[idx];
            const result = await generateChapterNote(
                bookInfo!.title!,
                bookInfo!.authors || [],
                chapter
            );
            setCurrentNote(result);
        } catch {
            const enabled2 = chapters.filter((ch) => enabledChapters[ch.chapter_number] !== false);
            setError(`Fehler bei Kapitel ${enabled2[idx]?.chapter_number ?? '?'}. Du kannst überspringen oder erneut versuchen.`);
        } finally {
            setGeneratingNote(false);
        }
    };

    const doGenerateTopicNote = async (topic: string) => {
        setGeneratingNote(true);
        setCurrentNote(null);
        setError(null);
        try {
            const result = await generateTopicNote(
                bookInfo!.title!,
                bookInfo!.authors || [],
                topic
            );
            setCurrentNote(result);
        } catch {
            setError(`Fehler beim Thema "${topic}". Du kannst überspringen oder erneut versuchen.`);
        } finally {
            setGeneratingNote(false);
        }
    };

    // ── Search & book confirmation ───────────────────────────────────
    const handleSearch = async () => {
        if (!query.trim() || searching) return;
        setSearching(true);
        setError(null);
        try {
            const result = await searchBook(query.trim());
            setBookInfo(result);
            if (result.found) {
                setStep('confirm-book');
            } else {
                setError(result.suggestion || 'Kein passendes Buch gefunden.');
            }
        } catch {
            setError('Fehler bei der Buchsuche. Bitte versuche es erneut.');
        } finally {
            setSearching(false);
        }
    };

    const handleConfirmBook = async () => {
        if (!bookInfo?.title) return;
        setLoadingToc(true);
        setError(null);
        try {
            const toc = await getBookToc(bookInfo.title, bookInfo.authors || []);
            if (toc.chapters.length === 0) {
                setError('Konnte kein Inhaltsverzeichnis finden.');
                setLoadingToc(false);
                return;
            }
            setChapters(toc.chapters);
            const defaults: Record<string, boolean> = {};
            toc.chapters.forEach((ch) => { defaults[ch.chapter_number] = true; });
            setEnabledChapters(defaults);
            setStep('confirm-toc');
        } catch {
            setError('Fehler beim Laden des Inhaltsverzeichnisses.');
        } finally {
            setLoadingToc(false);
        }
    };

    const handleStartGeneration = async () => {
        setStep('generating');
        setCurrentEnabledIdx(0);
        setCompletedCount(0);
        setSkippedCount(0);
        setTopicQueue([]);
        await advanceGeneration(0, []);
    };

    // ── After accept/skip — advance with queue priority ──────────────
    const afterNoteHandled = async (newCompleted: number, newSkipped: number, newQueue: string[]) => {
        const wasTopicNote = generatingSource?.kind === 'topic';
        const chapterIdx = wasTopicNote ? currentEnabledIdx : currentEnabledIdx + 1;

        if (wasTopicNote) {
            // Remove the first topic from queue (it was just processed)
            const remaining = newQueue.slice(1);
            setTopicQueue(remaining);
            await advanceGeneration(chapterIdx, remaining);
        } else {
            // Was a chapter note — move to next chapter (but check queue first)
            setCurrentEnabledIdx(chapterIdx);
            await advanceGeneration(chapterIdx, newQueue);
        }
    };

    const handleAcceptNote = async () => {
        if (!currentNote || savingNote) return;
        setSavingNote(true);
        try {
            const folder = await ensureFolderPath(currentNote.folder);
            await createNote(currentNote.title, currentNote.content, folder.id, currentNote.tag_ids);
            await loadFolderTree();
            const nc = completedCount + 1;
            setCompletedCount(nc);
            setAiEditMode(false);
            setAiEditInstruction('');
            await afterNoteHandled(nc, skippedCount, topicQueue);
        } catch {
            setError('Fehler beim Speichern. Bitte versuche es erneut.');
        } finally {
            setSavingNote(false);
        }
    };

    const handleSkipNote = async () => {
        const ns = skippedCount + 1;
        setSkippedCount(ns);
        setAiEditMode(false);
        setAiEditInstruction('');
        await afterNoteHandled(completedCount, ns, topicQueue);
    };

    const handleRetry = async () => {
        if (generatingSource?.kind === 'topic') {
            await doGenerateTopicNote(generatingSource.topic);
        } else {
            await doGenerateChapterNote(currentEnabledIdx);
        }
    };

    // ── AI Edit ──────────────────────────────────────────────────────
    const handleAiEdit = async () => {
        if (!currentNote || !aiEditInstruction.trim() || aiEditing) return;
        setAiEditing(true);
        try {
            const result = await aiEditBookContent(currentNote.content, aiEditInstruction.trim());
            setCurrentNote({ ...currentNote, content: result.suggested_content });
            setAiEditInstruction('');
            setAiEditMode(false);
        } catch {
            setError('Fehler bei der KI-Bearbeitung.');
        } finally {
            setAiEditing(false);
        }
    };

    // ── Reset ────────────────────────────────────────────────────────
    const handleReset = () => {
        setStep('search');
        setQuery('');
        setBookInfo(null);
        setChapters([]);
        setEnabledChapters({});
        setCurrentEnabledIdx(0);
        setCurrentNote(null);
        setGeneratingSource(null);
        setCompletedCount(0);
        setSkippedCount(0);
        setTopicQueue([]);
        setTopicInput('');
        setAiEditMode(false);
        setAiEditInstruction('');
        setError(null);
        clearState();
    };

    // ── Derived values ───────────────────────────────────────────────
    const processedCount = completedCount + skippedCount;
    const progressPercent = totalEnabled > 0 ? Math.round((processedCount / totalEnabled) * 100) : 0;
    const currentChapter = enabledChapterList[currentEnabledIdx];
    const isGenerating = step === 'generating';

    // ── Render: Topic Queue Panel ────────────────────────────────────
    const renderTopicQueue = () => (
        <div className="flex flex-col h-full">
            <div className="px-3 py-2.5 border-b border-dark-800 bg-dark-900/50">
                <div className="flex items-center justify-between">
                    <h3 className="text-xs font-semibold text-dark-400 uppercase tracking-wider">
                        Themen-Warteschlange
                    </h3>
                    {topicQueue.length > 0 && (
                        <span className="text-[10px] bg-amber-600/20 text-amber-400 px-1.5 py-0.5 rounded-full font-medium">
                            {topicQueue.length}
                        </span>
                    )}
                </div>
                <p className="text-[10px] text-dark-600 mt-0.5">
                    Themen werden vor dem nächsten Kapitel verarbeitet
                </p>
            </div>

            {/* Topic input */}
            <div className="p-2 border-b border-dark-800">
                <div className="flex gap-1.5">
                    <input
                        ref={topicInputRef}
                        type="text"
                        value={topicInput}
                        onChange={(e) => setTopicInput(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && addTopic()}
                        placeholder="z.B. Dopamin, Habit Loop..."
                        className="flex-1 px-2.5 py-1.5 bg-dark-800 border border-dark-700 rounded-lg text-white text-xs placeholder-dark-600 focus:outline-none focus:border-amber-500 min-w-0"
                    />
                    <button
                        onClick={addTopic}
                        disabled={!topicInput.trim()}
                        className="p-1.5 bg-amber-600 hover:bg-amber-500 text-white rounded-lg transition-colors disabled:opacity-30 disabled:cursor-not-allowed flex-shrink-0"
                    >
                        <FiPlus className="w-3.5 h-3.5" />
                    </button>
                </div>
            </div>

            {/* Queue list */}
            <div className="flex-1 overflow-y-auto p-2 space-y-1">
                {topicQueue.length === 0 ? (
                    <div className="text-center py-6">
                        <FiList className="w-6 h-6 text-dark-700 mx-auto mb-2" />
                        <p className="text-[10px] text-dark-600">
                            Begriffe hier hinzufügen, die dir in den Kapiteln begegnen
                        </p>
                    </div>
                ) : (
                    topicQueue.map((topic, i) => (
                        <div
                            key={`${topic}-${i}`}
                            className="flex items-center gap-1.5 px-2 py-1.5 bg-dark-800/50 border border-dark-700/50 rounded-lg group"
                        >
                            <span className="text-[10px] text-dark-600 font-mono w-4 flex-shrink-0">
                                {i + 1}
                            </span>
                            <span className="text-xs text-white flex-1 truncate">{topic}</span>
                            <div className="flex gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                                {i > 0 && (
                                    <button
                                        onClick={() => moveTopic(i, 'up')}
                                        className="p-0.5 hover:bg-dark-700 rounded text-dark-500 hover:text-white"
                                    >
                                        <FiArrowUp className="w-3 h-3" />
                                    </button>
                                )}
                                <button
                                    onClick={() => removeTopic(i)}
                                    className="p-0.5 hover:bg-dark-700 rounded text-dark-500 hover:text-red-400"
                                >
                                    <FiTrash2 className="w-3 h-3" />
                                </button>
                            </div>
                        </div>
                    ))
                )}
            </div>

            {/* Processing indicator when generating a topic note */}
            {generatingSource?.kind === 'topic' && generatingNote && (
                <div className="px-2 py-2 border-t border-dark-800 bg-amber-900/10">
                    <div className="flex items-center gap-2 text-xs text-amber-400">
                        <div className="w-3 h-3 border-2 border-amber-400 border-t-transparent rounded-full animate-spin" />
                        <span className="truncate">Generiere: {generatingSource.topic}</span>
                    </div>
                </div>
            )}
        </div>
    );

    // ── Main layout ──────────────────────────────────────────────────
    return (
        <div className="h-full flex flex-col">
            {/* Header */}
            <div className="flex items-center gap-2 px-3 sm:px-4 py-3 border-b border-dark-800 bg-dark-900/50">
                <FiBook className="w-4 h-4 text-amber-400 flex-shrink-0" />
                <h2 className="text-sm font-semibold text-white flex-shrink-0">Buch verarbeiten</h2>
                <span className="text-xs text-dark-500 ml-2 hidden sm:inline">
                    Gib einen Buchtitel ein — die KI erstellt Notizen für jedes Kapitel
                </span>
                <div className="ml-auto flex items-center gap-2">
                    {/* Mobile queue toggle */}
                    {isGenerating && (
                        <button
                            onClick={() => setShowQueueMobile(!showQueueMobile)}
                            className="lg:hidden relative p-1.5 hover:bg-dark-800 rounded-lg text-dark-400 hover:text-white transition-colors"
                        >
                            <FiList className="w-4 h-4" />
                            {topicQueue.length > 0 && (
                                <span className="absolute -top-0.5 -right-0.5 w-3.5 h-3.5 bg-amber-500 rounded-full text-[8px] text-white flex items-center justify-center font-bold">
                                    {topicQueue.length}
                                </span>
                            )}
                        </button>
                    )}
                    {step !== 'search' && step !== 'done' && (
                        <button
                            onClick={handleReset}
                            className="text-xs text-dark-500 hover:text-white transition-colors"
                        >
                            Zurücksetzen
                        </button>
                    )}
                </div>
            </div>

            {/* Progress bar during generation */}
            {isGenerating && totalEnabled > 0 && (
                <div className="px-4 py-2 border-b border-dark-800 bg-dark-900/30">
                    <div className="flex items-center justify-between text-xs text-dark-400 mb-1">
                        <span>
                            {generatingSource?.kind === 'topic'
                                ? `Thema: ${generatingSource.topic}`
                                : `Kapitel ${currentEnabledIdx + 1} von ${totalEnabled}`
                            }
                            {topicQueue.length > 0 && generatingSource?.kind !== 'topic' && (
                                <span className="text-amber-400 ml-2">+{topicQueue.length} Themen in Warteschlange</span>
                            )}
                        </span>
                        <span>
                            {completedCount} gespeichert · {skippedCount} übersprungen · {progressPercent}%
                        </span>
                    </div>
                    <div className="w-full h-2 bg-dark-800 rounded-full overflow-hidden">
                        <div
                            className="h-full bg-amber-500 rounded-full transition-all duration-500"
                            style={{ width: `${progressPercent}%` }}
                        />
                    </div>
                </div>
            )}

            {/* Body: two-panel layout during generation */}
            <div className="flex-1 flex overflow-hidden">
                {/* Left: main content */}
                <div className="flex-1 overflow-y-auto p-3 sm:p-4 space-y-4">
                    {/* Step: Search */}
                    {step === 'search' && (
                        <div className="h-full flex items-center justify-center">
                            <div className="text-center max-w-md w-full">
                                <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-amber-900/30 mb-4">
                                    <FiBook className="w-8 h-8 text-amber-400" />
                                </div>
                                <h3 className="text-lg font-semibold text-white mb-2">Buch verarbeiten</h3>
                                <p className="text-sm text-dark-500 mb-6">
                                    Gib den Titel eines Buches ein. Die KI sucht nach dem Buch,
                                    zeigt dir das Inhaltsverzeichnis und erstellt für jedes Kapitel eine Notiz.
                                </p>
                                <div className="flex gap-2">
                                    <input
                                        type="text"
                                        value={query}
                                        onChange={(e) => setQuery(e.target.value)}
                                        onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                                        placeholder='z.B. "Atomic Habits" oder "Clean Code Robert Martin"'
                                        className="flex-1 px-4 py-3 bg-dark-800 border border-dark-700 rounded-xl text-white text-sm placeholder-dark-600 focus:outline-none focus:border-amber-500"
                                        autoFocus
                                    />
                                    <button
                                        onClick={handleSearch}
                                        disabled={!query.trim() || searching}
                                        className="px-4 py-3 bg-amber-600 hover:bg-amber-500 text-white rounded-xl transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                                    >
                                        {searching ? (
                                            <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                                        ) : (
                                            <FiSearch className="w-5 h-5" />
                                        )}
                                    </button>
                                </div>
                                {error && (
                                    <p className="mt-3 text-sm text-red-400">{error}</p>
                                )}
                            </div>
                        </div>
                    )}

                    {/* Step: Confirm book */}
                    {step === 'confirm-book' && bookInfo && (
                        <div className="max-w-lg mx-auto">
                            <div className="bg-dark-800 border border-dark-700 rounded-2xl p-6">
                                <div className="flex items-start gap-4 mb-4">
                                    <div className="p-3 bg-amber-900/30 rounded-xl flex-shrink-0">
                                        <FiBook className="w-6 h-6 text-amber-400" />
                                    </div>
                                    <div>
                                        <h3 className="text-lg font-bold text-white">{bookInfo.title}</h3>
                                        <p className="text-sm text-dark-400 mt-1">
                                            {bookInfo.authors?.join(', ')}
                                        </p>
                                    </div>
                                </div>

                                <div className="space-y-2 text-sm mb-6">
                                    {bookInfo.year && (
                                        <div className="flex justify-between text-dark-400">
                                            <span>Jahr</span>
                                            <span className="text-white">{bookInfo.year}</span>
                                        </div>
                                    )}
                                    {bookInfo.publisher && (
                                        <div className="flex justify-between text-dark-400">
                                            <span>Verlag</span>
                                            <span className="text-white">{bookInfo.publisher}</span>
                                        </div>
                                    )}
                                    {bookInfo.language && (
                                        <div className="flex justify-between text-dark-400">
                                            <span>Sprache</span>
                                            <span className="text-white">{bookInfo.language}</span>
                                        </div>
                                    )}
                                    {bookInfo.pages && (
                                        <div className="flex justify-between text-dark-400">
                                            <span>Seiten</span>
                                            <span className="text-white">{bookInfo.pages}</span>
                                        </div>
                                    )}
                                    {bookInfo.isbn && (
                                        <div className="flex justify-between text-dark-400">
                                            <span>ISBN</span>
                                            <span className="text-white font-mono text-xs">{bookInfo.isbn}</span>
                                        </div>
                                    )}
                                </div>

                                {bookInfo.description && (
                                    <p className="text-sm text-dark-400 mb-6 leading-relaxed">
                                        {bookInfo.description}
                                    </p>
                                )}

                                <div className="flex gap-2">
                                    <button
                                        onClick={handleConfirmBook}
                                        disabled={loadingToc}
                                        className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 bg-amber-600 hover:bg-amber-500 text-white text-sm font-medium rounded-xl transition-colors disabled:opacity-50"
                                    >
                                        {loadingToc ? (
                                            <>
                                                <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                                                Lade Inhaltsverzeichnis...
                                            </>
                                        ) : (
                                            <>
                                                <FiCheck className="w-4 h-4" />
                                                Richtig — Inhaltsverzeichnis laden
                                            </>
                                        )}
                                    </button>
                                    <button
                                        onClick={handleReset}
                                        className="px-4 py-2.5 bg-dark-700 hover:bg-dark-600 text-dark-300 text-sm rounded-xl transition-colors"
                                    >
                                        <FiX className="w-4 h-4" />
                                    </button>
                                </div>

                                {error && (
                                    <p className="mt-3 text-sm text-red-400">{error}</p>
                                )}
                            </div>
                        </div>
                    )}

                    {/* Step: Confirm TOC with checkboxes */}
                    {step === 'confirm-toc' && (
                        <div className="max-w-lg mx-auto">
                            <div className="bg-dark-800 border border-dark-700 rounded-2xl p-6">
                                <h3 className="text-lg font-bold text-white mb-1">Inhaltsverzeichnis</h3>
                                <p className="text-xs text-dark-500 mb-3">
                                    {chapters.length} Kapitel gefunden — <span className="text-amber-400">{totalEnabled} ausgewählt</span>
                                </p>

                                {/* Select / Deselect all */}
                                <div className="flex gap-3 mb-3 text-xs">
                                    <button onClick={selectAll} className="text-dark-400 hover:text-white transition-colors">
                                        Alle auswählen
                                    </button>
                                    <span className="text-dark-700">|</span>
                                    <button onClick={deselectAll} className="text-dark-400 hover:text-white transition-colors">
                                        Alle abwählen
                                    </button>
                                </div>

                                <div className="max-h-[400px] overflow-y-auto space-y-0.5 mb-6 pr-2">
                                    {chapters.map((ch, i) => {
                                        const enabled = enabledChapters[ch.chapter_number] !== false;
                                        return (
                                            <button
                                                key={i}
                                                onClick={() => toggleChapter(ch.chapter_number)}
                                                className={`w-full flex items-center gap-2 py-1.5 text-sm rounded-lg px-1 transition-colors hover:bg-dark-700/50 ${
                                                    !enabled ? 'opacity-40' : ''
                                                }`}
                                                style={{ paddingLeft: `${(ch.level - 1) * 20 + 4}px` }}
                                            >
                                                {enabled ? (
                                                    <FiCheckSquare className="w-3.5 h-3.5 flex-shrink-0 text-amber-400" />
                                                ) : (
                                                    <FiSquare className="w-3.5 h-3.5 flex-shrink-0 text-dark-600" />
                                                )}
                                                <span className="text-dark-500 font-mono text-xs w-10 flex-shrink-0 text-left">
                                                    {ch.chapter_number}
                                                </span>
                                                <span className={`text-left ${
                                                    ch.level === 1 ? 'text-white font-medium' :
                                                    ch.level === 2 ? 'text-dark-300' : 'text-dark-500'
                                                }`}>
                                                    {ch.title}
                                                </span>
                                            </button>
                                        );
                                    })}
                                </div>

                                <div className="flex gap-2">
                                    <button
                                        onClick={handleStartGeneration}
                                        disabled={totalEnabled === 0}
                                        className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 bg-amber-600 hover:bg-amber-500 text-white text-sm font-medium rounded-xl transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                                    >
                                        <LuBrain className="w-4 h-4" />
                                        {totalEnabled} Notizen generieren
                                    </button>
                                    <button
                                        onClick={handleReset}
                                        className="px-4 py-2.5 bg-dark-700 hover:bg-dark-600 text-dark-300 text-sm rounded-xl transition-colors"
                                    >
                                        <FiX className="w-4 h-4" />
                                    </button>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* Step: Generating notes one by one */}
                    {isGenerating && (
                        <div>
                            {/* Current item info */}
                            {generatingSource && (
                                <div className="mb-4 flex items-center gap-3 text-sm">
                                    {generatingSource.kind === 'topic' ? (
                                        <>
                                            <span className="px-2 py-1 bg-purple-900/30 text-purple-400 rounded-lg text-xs font-medium">
                                                Thema
                                            </span>
                                            <span className="text-white font-medium">
                                                {generatingSource.topic}
                                            </span>
                                        </>
                                    ) : (
                                        <>
                                            <span className="px-2 py-1 bg-amber-900/30 text-amber-400 rounded-lg font-mono text-xs">
                                                {currentChapter?.chapter_number}
                                            </span>
                                            <span className="text-white font-medium">
                                                {currentChapter?.title}
                                            </span>
                                        </>
                                    )}
                                </div>
                            )}

                            {/* Loading state */}
                            {generatingNote && (
                                <div className="bg-dark-800 border border-dark-700 rounded-2xl p-8 text-center">
                                    <div className="w-10 h-10 border-2 border-amber-500 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
                                    <p className="text-sm text-dark-400">
                                        {generatingSource?.kind === 'topic'
                                            ? `Generiere Notiz für "${generatingSource.topic}"...`
                                            : `Generiere Notiz für Kapitel ${currentChapter?.chapter_number}...`
                                        }
                                    </p>
                                    <p className="text-xs text-dark-600 mt-1">
                                        Dies kann einige Sekunden dauern
                                    </p>
                                </div>
                            )}

                            {/* Generated note preview */}
                            {currentNote && !generatingNote && (
                                <div className="bg-dark-800 border border-dark-700 rounded-2xl overflow-hidden">
                                    {/* Note header */}
                                    <div className="px-4 py-3 border-b border-dark-700 bg-dark-800/50">
                                        <div className="flex items-center justify-between">
                                            <div>
                                                <p className="text-xs text-dark-500">
                                                    Ordner: <span className="text-amber-400">{currentNote.folder}</span>
                                                </p>
                                                <h4 className="text-sm font-semibold text-white mt-0.5">
                                                    {currentNote.title}
                                                </h4>
                                            </div>
                                            {currentNote.tag_names.length > 0 && (
                                                <div className="flex gap-1 flex-wrap">
                                                    {currentNote.tag_names.map((tag, i) => (
                                                        <span key={i} className="px-2 py-0.5 text-[10px] bg-dark-700 text-dark-400 rounded-full">
                                                            {tag}
                                                        </span>
                                                    ))}
                                                </div>
                                            )}
                                        </div>
                                    </div>

                                    {/* Note content preview */}
                                    <div className="px-6 py-5 overflow-y-auto">
                                        <div className="markdown-content text-sm">
                                            <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                                                {currentNote.content}
                                            </ReactMarkdown>
                                        </div>
                                    </div>

                                    {/* AI Edit bar */}
                                    {aiEditMode && (
                                        <div className="px-4 py-3 border-t border-dark-700 bg-purple-900/5">
                                            <p className="text-xs text-purple-400 mb-2 font-medium">KI-Bearbeitung</p>
                                            <div className="flex gap-2">
                                                <input
                                                    type="text"
                                                    value={aiEditInstruction}
                                                    onChange={(e) => setAiEditInstruction(e.target.value)}
                                                    onKeyDown={(e) => e.key === 'Enter' && handleAiEdit()}
                                                    placeholder="z.B. 'Füge mehr Details hinzu' oder 'Kürze die Notiz'"
                                                    className="flex-1 px-3 py-2 bg-dark-900 border border-dark-700 rounded-lg text-white text-xs placeholder-dark-600 focus:outline-none focus:border-purple-500"
                                                    autoFocus
                                                />
                                                <button
                                                    onClick={handleAiEdit}
                                                    disabled={!aiEditInstruction.trim() || aiEditing}
                                                    className="px-3 py-2 bg-purple-600 hover:bg-purple-500 text-white text-xs rounded-lg transition-colors disabled:opacity-50 flex items-center gap-1.5"
                                                >
                                                    {aiEditing ? (
                                                        <div className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                                                    ) : (
                                                        <FiSend className="w-3.5 h-3.5" />
                                                    )}
                                                    Anwenden
                                                </button>
                                                <button
                                                    onClick={() => { setAiEditMode(false); setAiEditInstruction(''); }}
                                                    className="p-2 hover:bg-dark-700 rounded-lg text-dark-500 transition-colors"
                                                >
                                                    <FiX className="w-3.5 h-3.5" />
                                                </button>
                                            </div>
                                        </div>
                                    )}

                                    {/* Actions */}
                                    <div className="px-4 py-3 border-t border-dark-700 flex gap-2">
                                        <button
                                            onClick={handleAcceptNote}
                                            disabled={savingNote || aiEditing}
                                            className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-green-600 hover:bg-green-500 text-white text-sm font-medium rounded-xl transition-colors disabled:opacity-50"
                                        >
                                            <FiCheck className="w-4 h-4" />
                                            {savingNote ? 'Speichert...' : 'Akzeptieren'}
                                        </button>
                                        <button
                                            onClick={() => setAiEditMode(!aiEditMode)}
                                            className={`flex items-center gap-1.5 px-3 py-2 text-sm rounded-xl transition-colors ${
                                                aiEditMode
                                                    ? 'bg-purple-600 text-white'
                                                    : 'bg-purple-600/20 text-purple-400 hover:bg-purple-600/30'
                                            }`}
                                        >
                                            <FiZap className="w-4 h-4" />
                                            <span className="hidden sm:inline">KI-Bearbeitung</span>
                                        </button>
                                        <button
                                            onClick={handleSkipNote}
                                            className="px-4 py-2 bg-dark-700 hover:bg-dark-600 text-dark-300 text-sm rounded-xl transition-colors"
                                        >
                                            Überspringen
                                        </button>
                                    </div>
                                </div>
                            )}

                            {/* Error state */}
                            {error && !generatingNote && !currentNote && (
                                <div className="bg-dark-800 border border-red-900/50 rounded-2xl p-6 text-center">
                                    <p className="text-sm text-red-400 mb-4">{error}</p>
                                    <div className="flex gap-2 justify-center">
                                        <button
                                            onClick={handleRetry}
                                            className="px-4 py-2 bg-amber-600 hover:bg-amber-500 text-white text-sm rounded-xl transition-colors"
                                        >
                                            Erneut versuchen
                                        </button>
                                        <button
                                            onClick={handleSkipNote}
                                            className="px-4 py-2 bg-dark-700 hover:bg-dark-600 text-dark-300 text-sm rounded-xl transition-colors"
                                        >
                                            Überspringen
                                        </button>
                                    </div>
                                </div>
                            )}
                        </div>
                    )}

                    {/* Step: Done */}
                    {step === 'done' && (
                        <div className="h-full flex items-center justify-center">
                            <div className="text-center max-w-md">
                                <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-green-900/30 mb-4">
                                    <FiCheck className="w-8 h-8 text-green-400" />
                                </div>
                                <h3 className="text-lg font-semibold text-white mb-2">Fertig!</h3>
                                <p className="text-sm text-dark-400 mb-2">
                                    <span className="text-green-400 font-medium">{completedCount} Notizen</span> erstellt
                                    {skippedCount > 0 && (
                                        <span> · <span className="text-dark-500">{skippedCount} übersprungen</span></span>
                                    )}
                                </p>
                                {bookInfo && (
                                    <p className="text-xs text-dark-500 mb-6">
                                        Die Notizen findest du im Ordner <span className="text-amber-400">Bücher/{bookInfo.title}</span>
                                    </p>
                                )}
                                <button
                                    onClick={handleReset}
                                    className="px-6 py-2.5 bg-amber-600 hover:bg-amber-500 text-white text-sm font-medium rounded-xl transition-colors"
                                >
                                    Neues Buch verarbeiten
                                </button>
                            </div>
                        </div>
                    )}

                    <div ref={scrollRef} />
                </div>

                {/* Right: topic queue panel — visible during generation */}
                {isGenerating && (
                    <>
                        {/* Desktop: always visible */}
                        <div className="hidden lg:flex w-64 border-l border-dark-800 bg-dark-900/30 flex-shrink-0">
                            {renderTopicQueue()}
                        </div>

                        {/* Mobile: overlay when toggled */}
                        {showQueueMobile && (
                            <>
                                <div
                                    className="lg:hidden fixed inset-0 bg-black/50 z-40"
                                    onClick={() => setShowQueueMobile(false)}
                                />
                                <div className="lg:hidden fixed right-0 top-0 bottom-0 w-72 bg-dark-900 border-l border-dark-800 z-50 flex flex-col">
                                    <div className="flex items-center justify-between p-3 border-b border-dark-800">
                                        <span className="text-sm font-semibold text-white">Themen-Queue</span>
                                        <button
                                            onClick={() => setShowQueueMobile(false)}
                                            className="p-1.5 hover:bg-dark-800 rounded-lg text-dark-400"
                                        >
                                            <FiX className="w-4 h-4" />
                                        </button>
                                    </div>
                                    <div className="flex-1 overflow-hidden">
                                        {renderTopicQueue()}
                                    </div>
                                </div>
                            </>
                        )}
                    </>
                )}
            </div>
        </div>
    );
}
