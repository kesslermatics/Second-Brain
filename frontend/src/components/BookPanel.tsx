'use client';

import { useState, useRef, useEffect } from 'react';
import { FiSearch, FiCheck, FiX, FiBook, FiChevronRight, FiLoader } from 'react-icons/fi';
import { LuBrain } from 'react-icons/lu';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { markdownComponents } from '@/lib/markdownComponents';
import { useStore } from '@/lib/store';
import { searchBook, getBookToc, generateChapterNote, ensureFolderPath, createNote } from '@/lib/api';
import type { BookSearchResult, BookChapter, BookChapterNoteResult } from '@/lib/types';

type Step = 'search' | 'confirm-book' | 'confirm-toc' | 'generating' | 'done';

export default function BookPanel() {
    const [step, setStep] = useState<Step>('search');
    const [query, setQuery] = useState('');
    const [searching, setSearching] = useState(false);
    const [bookInfo, setBookInfo] = useState<BookSearchResult | null>(null);
    const [chapters, setChapters] = useState<BookChapter[]>([]);
    const [loadingToc, setLoadingToc] = useState(false);
    const [currentChapterIdx, setCurrentChapterIdx] = useState(0);
    const [currentNote, setCurrentNote] = useState<BookChapterNoteResult | null>(null);
    const [generatingNote, setGeneratingNote] = useState(false);
    const [completedCount, setCompletedCount] = useState(0);
    const [skippedCount, setSkippedCount] = useState(0);
    const [error, setError] = useState<string | null>(null);
    const [savingNote, setSavingNote] = useState(false);
    const scrollRef = useRef<HTMLDivElement>(null);
    const { loadFolderTree } = useStore();

    useEffect(() => {
        scrollRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [step, currentChapterIdx, currentNote]);

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
        } catch (e) {
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
            setStep('confirm-toc');
        } catch (e) {
            setError('Fehler beim Laden des Inhaltsverzeichnisses.');
        } finally {
            setLoadingToc(false);
        }
    };

    const handleStartGeneration = async () => {
        setStep('generating');
        setCurrentChapterIdx(0);
        setCompletedCount(0);
        setSkippedCount(0);
        await generateNextNote(0);
    };

    const generateNextNote = async (idx: number) => {
        if (idx >= chapters.length) {
            setStep('done');
            return;
        }
        setCurrentChapterIdx(idx);
        setGeneratingNote(true);
        setCurrentNote(null);
        setError(null);
        try {
            const result = await generateChapterNote(
                bookInfo!.title!,
                bookInfo!.authors || [],
                chapters[idx]
            );
            setCurrentNote(result);
        } catch (e) {
            setError(`Fehler bei Kapitel ${chapters[idx].chapter_number}. Du kannst überspringen oder erneut versuchen.`);
        } finally {
            setGeneratingNote(false);
        }
    };

    const handleAcceptNote = async () => {
        if (!currentNote || savingNote) return;
        setSavingNote(true);
        try {
            const folder = await ensureFolderPath(currentNote.folder);
            await createNote(currentNote.title, currentNote.content, folder.id, currentNote.tag_ids);
            await loadFolderTree();
            setCompletedCount((prev) => prev + 1);
            const nextIdx = currentChapterIdx + 1;
            if (nextIdx >= chapters.length) {
                setStep('done');
            } else {
                await generateNextNote(nextIdx);
            }
        } catch (e) {
            setError('Fehler beim Speichern. Bitte versuche es erneut.');
        } finally {
            setSavingNote(false);
        }
    };

    const handleSkipNote = async () => {
        setSkippedCount((prev) => prev + 1);
        const nextIdx = currentChapterIdx + 1;
        if (nextIdx >= chapters.length) {
            setStep('done');
        } else {
            await generateNextNote(nextIdx);
        }
    };

    const handleRetry = async () => {
        await generateNextNote(currentChapterIdx);
    };

    const handleReset = () => {
        setStep('search');
        setQuery('');
        setBookInfo(null);
        setChapters([]);
        setCurrentChapterIdx(0);
        setCurrentNote(null);
        setCompletedCount(0);
        setSkippedCount(0);
        setError(null);
    };

    const totalChapters = chapters.length;
    const processedCount = completedCount + skippedCount;
    const progressPercent = totalChapters > 0 ? Math.round((processedCount / totalChapters) * 100) : 0;

    return (
        <div className="h-full flex flex-col">
            {/* Header */}
            <div className="flex items-center gap-2 px-4 py-3 border-b border-dark-800 bg-dark-900/50">
                <FiBook className="w-4 h-4 text-amber-400" />
                <h2 className="text-sm font-semibold text-white">Buch verarbeiten</h2>
                <span className="text-xs text-dark-500 ml-2">
                    Gib einen Buchtitel ein — die KI erstellt Notizen für jedes Kapitel
                </span>
                {step !== 'search' && step !== 'done' && (
                    <button
                        onClick={handleReset}
                        className="ml-auto text-xs text-dark-500 hover:text-white transition-colors"
                    >
                        Zurücksetzen
                    </button>
                )}
            </div>

            {/* Progress bar during generation */}
            {step === 'generating' && totalChapters > 0 && (
                <div className="px-4 py-2 border-b border-dark-800 bg-dark-900/30">
                    <div className="flex items-center justify-between text-xs text-dark-400 mb-1">
                        <span>
                            Kapitel {currentChapterIdx + 1} von {totalChapters}
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

            {/* Content */}
            <div className="flex-1 overflow-y-auto p-4 space-y-4">
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

                {/* Step: Confirm TOC */}
                {step === 'confirm-toc' && (
                    <div className="max-w-lg mx-auto">
                        <div className="bg-dark-800 border border-dark-700 rounded-2xl p-6">
                            <h3 className="text-lg font-bold text-white mb-1">Inhaltsverzeichnis</h3>
                            <p className="text-xs text-dark-500 mb-4">
                                {chapters.length} Kapitel gefunden — es werden {chapters.length} Notizen erstellt
                            </p>

                            <div className="max-h-[400px] overflow-y-auto space-y-0.5 mb-6 pr-2">
                                {chapters.map((ch, i) => (
                                    <div
                                        key={i}
                                        className="flex items-center gap-2 py-1.5 text-sm"
                                        style={{ paddingLeft: `${(ch.level - 1) * 20}px` }}
                                    >
                                        <FiChevronRight className={`w-3 h-3 flex-shrink-0 ${
                                            ch.level === 1 ? 'text-amber-400' :
                                            ch.level === 2 ? 'text-amber-600' : 'text-dark-600'
                                        }`} />
                                        <span className="text-dark-500 font-mono text-xs w-10 flex-shrink-0">
                                            {ch.chapter_number}
                                        </span>
                                        <span className={
                                            ch.level === 1 ? 'text-white font-medium' :
                                            ch.level === 2 ? 'text-dark-300' : 'text-dark-500'
                                        }>
                                            {ch.title}
                                        </span>
                                    </div>
                                ))}
                            </div>

                            <div className="flex gap-2">
                                <button
                                    onClick={handleStartGeneration}
                                    className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 bg-amber-600 hover:bg-amber-500 text-white text-sm font-medium rounded-xl transition-colors"
                                >
                                    <LuBrain className="w-4 h-4" />
                                    Alle {chapters.length} Notizen generieren
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
                {step === 'generating' && (
                    <div>
                        {/* Current chapter info */}
                        <div className="mb-4 flex items-center gap-3 text-sm">
                            <span className="px-2 py-1 bg-amber-900/30 text-amber-400 rounded-lg font-mono text-xs">
                                {chapters[currentChapterIdx]?.chapter_number}
                            </span>
                            <span className="text-white font-medium">
                                {chapters[currentChapterIdx]?.title}
                            </span>
                        </div>

                        {/* Loading state */}
                        {generatingNote && (
                            <div className="bg-dark-800 border border-dark-700 rounded-2xl p-8 text-center">
                                <div className="w-10 h-10 border-2 border-amber-500 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
                                <p className="text-sm text-dark-400">
                                    Generiere Notiz für Kapitel {chapters[currentChapterIdx]?.chapter_number}...
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

                                {/* Actions */}
                                <div className="px-4 py-3 border-t border-dark-700 flex gap-2">
                                    <button
                                        onClick={handleAcceptNote}
                                        disabled={savingNote}
                                        className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-green-600 hover:bg-green-500 text-white text-sm font-medium rounded-xl transition-colors disabled:opacity-50"
                                    >
                                        <FiCheck className="w-4 h-4" />
                                        {savingNote ? 'Speichert...' : 'Akzeptieren'}
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
        </div>
    );
}
