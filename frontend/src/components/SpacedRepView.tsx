'use client';

import { useState, useEffect, useCallback } from 'react';
import {
    FiPlay, FiSettings, FiRotateCw, FiCheck, FiX, FiTrash2,
    FiChevronRight, FiBookOpen, FiClock, FiAward,
} from 'react-icons/fi';
import { LuBrain } from 'react-icons/lu';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
    getReviewSession, submitReview, getSRSettings, updateSRSettings,
    getAllFlashcards, deleteFlashcard,
} from '@/lib/api';
import type { FlashCard, SRSettings, ReviewSession } from '@/lib/types';

type View = 'home' | 'review' | 'settings' | 'cards';

const QUALITY_LABELS = [
    { q: 0, label: 'Vergessen', color: 'bg-red-600 hover:bg-red-500', desc: 'Keine Ahnung' },
    { q: 1, label: 'Falsch', color: 'bg-red-500 hover:bg-red-400', desc: 'Falsch, aber erkannt' },
    { q: 2, label: 'Schwer', color: 'bg-orange-600 hover:bg-orange-500', desc: 'Mit Mühe erinnert' },
    { q: 3, label: 'OK', color: 'bg-yellow-600 hover:bg-yellow-500', desc: 'Richtig, aber unsicher' },
    { q: 4, label: 'Gut', color: 'bg-green-600 hover:bg-green-500', desc: 'Leicht erinnert' },
    { q: 5, label: 'Perfekt', color: 'bg-emerald-600 hover:bg-emerald-500', desc: 'Sofort gewusst' },
];

export default function SpacedRepView() {
    const [view, setView] = useState<View>('home');
    const [session, setSession] = useState<ReviewSession | null>(null);
    const [currentIdx, setCurrentIdx] = useState(0);
    const [flipped, setFlipped] = useState(false);
    const [settings, setSettings] = useState<SRSettings | null>(null);
    const [allCards, setAllCards] = useState<FlashCard[]>([]);
    const [loading, setLoading] = useState(false);
    const [reviewed, setReviewed] = useState(0);

    const loadSession = useCallback(async () => {
        setLoading(true);
        try {
            const s = await getReviewSession();
            setSession(s);
            setCurrentIdx(0);
            setFlipped(false);
            setReviewed(0);
        } catch (e) {
            console.error(e);
        } finally {
            setLoading(false);
        }
    }, []);

    const loadSettings = useCallback(async () => {
        try {
            const s = await getSRSettings();
            setSettings(s);
        } catch (e) {
            console.error(e);
        }
    }, []);

    const loadAllCards = useCallback(async () => {
        try {
            const cards = await getAllFlashcards();
            setAllCards(cards);
        } catch (e) {
            console.error(e);
        }
    }, []);

    useEffect(() => {
        loadSession();
        loadSettings();
    }, [loadSession, loadSettings]);

    const handleReview = async (quality: number) => {
        if (!session || currentIdx >= session.cards.length) return;
        const card = session.cards[currentIdx];
        try {
            await submitReview(card.id, quality);
            setReviewed((r) => r + 1);
            if (currentIdx + 1 < session.cards.length) {
                setCurrentIdx((i) => i + 1);
                setFlipped(false);
            } else {
                setView('home');
                loadSession();
            }
        } catch (e) {
            console.error(e);
        }
    };

    const handleSaveSettings = async () => {
        if (!settings) return;
        try {
            const updated = await updateSRSettings(settings);
            setSettings(updated);
            setView('home');
        } catch (e) {
            console.error(e);
        }
    };

    const handleDeleteCard = async (cardId: string) => {
        try {
            await deleteFlashcard(cardId);
            setAllCards((prev) => prev.filter((c) => c.id !== cardId));
        } catch (e) {
            console.error(e);
        }
    };

    const currentCard = session?.cards[currentIdx];

    // Home view
    if (view === 'home') {
        return (
            <div className="h-full flex flex-col">
                <div className="flex items-center justify-between px-4 sm:px-6 py-4 border-b border-dark-800 bg-dark-900/50">
                    <div className="flex items-center gap-3">
                        <div className="p-2 bg-green-600/20 rounded-xl">
                            <FiBookOpen className="w-5 h-5 text-green-400" />
                        </div>
                        <div>
                            <h1 className="text-base sm:text-lg font-semibold text-white">Spaced Repetition</h1>
                            <p className="text-xs text-dark-500">Lerne mit dem SM-2 Algorithmus</p>
                        </div>
                    </div>
                    <div className="flex gap-2">
                        <button
                            onClick={() => { loadAllCards(); setView('cards'); }}
                            className="px-2 sm:px-3 py-2 text-xs sm:text-sm bg-dark-800 hover:bg-dark-700 text-white rounded-lg transition-colors"
                        >
                            <span className="hidden sm:inline">Alle Karten</span>
                            <span className="sm:hidden">Karten</span>
                        </button>
                        <button
                            onClick={() => setView('settings')}
                            className="p-2 hover:bg-dark-800 rounded-lg transition-colors text-dark-400 hover:text-white"
                        >
                            <FiSettings className="w-4 h-4" />
                        </button>
                    </div>
                </div>

                <div className="flex-1 flex items-center justify-center p-6">
                    <div className="text-center max-w-md">
                        {loading ? (
                            <div className="animate-spin w-8 h-8 border-2 border-green-500 border-t-transparent rounded-full mx-auto" />
                        ) : (
                            <>
                <div className="grid grid-cols-3 gap-4 mb-8">
                                    <div className="bg-dark-800 rounded-xl p-4 border border-dark-700">
                                        <FiClock className="w-6 h-6 text-orange-400 mx-auto mb-2" />
                                        <p className="text-2xl font-bold text-white">{session?.total_due || 0}</p>
                                        <p className="text-xs text-dark-500">Fällig</p>
                                    </div>
                                    <div className="bg-dark-800 rounded-xl p-4 border border-dark-700">
                                        <FiBookOpen className="w-6 h-6 text-blue-400 mx-auto mb-2" />
                                        <p className="text-2xl font-bold text-white">{session?.cards.length || 0}</p>
                                        <p className="text-xs text-dark-500">Diese Sitzung</p>
                                    </div>
                                    <div className="bg-dark-800 rounded-xl p-4 border border-dark-700">
                                        <FiAward className="w-6 h-6 text-green-400 mx-auto mb-2" />
                                        <p className="text-2xl font-bold text-white">{session?.new_today || 0}</p>
                                        <p className="text-xs text-dark-500">Neu heute</p>
                                    </div>
                                </div>

                                {session && session.cards.length > 0 ? (
                                    <button
                                        onClick={() => { setCurrentIdx(0); setFlipped(false); setView('review'); }}
                                        className="inline-flex items-center gap-2 px-8 py-4 text-lg font-semibold bg-green-600 hover:bg-green-500 text-white rounded-2xl transition-colors shadow-lg shadow-green-600/20"
                                    >
                                        <FiPlay className="w-5 h-5" />
                                        Lernen starten
                                    </button>
                                ) : (
                                    <div>
                                        <FiCheck className="w-12 h-12 text-green-400 mx-auto mb-3" />
                                        <p className="text-white font-medium">Alles erledigt!</p>
                                        <p className="text-sm text-dark-500 mt-1">Keine fälligen Karten. Komm später wieder.</p>
                                        <button
                                            onClick={loadSession}
                                            className="mt-4 inline-flex items-center gap-2 px-4 py-2 text-sm bg-dark-800 hover:bg-dark-700 text-white rounded-lg transition-colors"
                                        >
                                            <FiRotateCw className="w-4 h-4" />
                                            Aktualisieren
                                        </button>
                                    </div>
                                )}
                            </>
                        )}
                    </div>
                </div>
            </div>
        );
    }

    // Review view
    if (view === 'review' && currentCard) {
        const progress = session ? (currentIdx + 1) / session.cards.length : 0;
        return (
            <div className="h-full flex flex-col">
                <div className="flex items-center justify-between px-4 sm:px-6 py-3 border-b border-dark-800 bg-dark-900/50">
                    <button
                        onClick={() => setView('home')}
                        className="text-sm text-dark-400 hover:text-white transition-colors"
                    >
                        ← Zurück
                    </button>
                    <div className="flex items-center gap-3">
                        <span className="text-xs text-dark-500">
                            {currentIdx + 1} / {session?.cards.length}
                        </span>
                        <div className="w-32 h-1.5 bg-dark-800 rounded-full overflow-hidden">
                            <div
                                className="h-full bg-green-500 rounded-full transition-all duration-300"
                                style={{ width: `${progress * 100}%` }}
                            />
                        </div>
                    </div>
                    <span className="text-xs text-dark-500">{reviewed} gelernt</span>
                </div>

                <div className="flex-1 flex items-center justify-center p-3 sm:p-6">
                    <div className="w-full max-w-2xl">
                        {/* Card */}
                        <div
                            onClick={() => !flipped && setFlipped(true)}
                            className={`min-h-[300px] bg-dark-800 border rounded-2xl p-8 transition-all cursor-pointer ${flipped ? 'border-green-500/30' : 'border-dark-700 hover:border-brain-500/30'
                                }`}
                        >
                            {currentCard.note_title && (
                                <p className="text-xs text-dark-500 mb-3 flex items-center gap-1">
                                    <FiBookOpen className="w-3 h-3" />
                                    {currentCard.note_title}
                                </p>
                            )}
                            <div className="mb-4">
                                <p className="text-xs uppercase tracking-wider text-dark-500 font-semibold mb-2">Frage</p>
                                <div className="text-white text-lg markdown-content">
                                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                        {currentCard.question}
                                    </ReactMarkdown>
                                </div>
                            </div>

                            {flipped ? (
                                <div className="pt-4 border-t border-dark-700">
                                    <p className="text-xs uppercase tracking-wider text-green-400 font-semibold mb-2">Antwort</p>
                                    <div className="text-dark-300 text-base markdown-content">
                                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                            {currentCard.answer}
                                        </ReactMarkdown>
                                    </div>
                                </div>
                            ) : (
                                <div className="pt-4 border-t border-dark-700 text-center">
                                    <p className="text-dark-500 text-sm flex items-center justify-center gap-2">
                                        <FiChevronRight className="w-4 h-4" />
                                        Klicken zum Aufdecken
                                    </p>
                                </div>
                            )}
                        </div>

                        {/* Quality buttons */}
                        {flipped && (
                            <div className="mt-6">
                                <p className="text-xs text-dark-500 text-center mb-3">Wie gut hast du die Antwort gewusst?</p>
                                <div className="grid grid-cols-3 sm:grid-cols-6 gap-2">
                                    {QUALITY_LABELS.map(({ q, label, color, desc }) => (
                                        <button
                                            key={q}
                                            onClick={() => handleReview(q)}
                                            className={`py-3 px-2 rounded-xl text-white text-xs font-medium ${color} transition-colors`}
                                            title={desc}
                                        >
                                            <span className="block text-lg font-bold">{q}</span>
                                            {label}
                                        </button>
                                    ))}
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            </div>
        );
    }

    // Settings view
    if (view === 'settings' && settings) {
        return (
            <div className="h-full flex flex-col">
                <div className="flex items-center justify-between px-6 py-4 border-b border-dark-800 bg-dark-900/50">
                    <button onClick={() => setView('home')} className="text-sm text-dark-400 hover:text-white transition-colors">
                        ← Zurück
                    </button>
                    <h1 className="text-lg font-semibold text-white">Lerneinstellungen</h1>
                    <button
                        onClick={handleSaveSettings}
                        className="px-4 py-2 text-sm bg-brain-600 hover:bg-brain-500 text-white rounded-lg transition-colors"
                    >
                        Speichern
                    </button>
                </div>
                <div className="flex-1 overflow-y-auto p-6">
                    <div className="max-w-md mx-auto space-y-6">
                        <div>
                            <label className="block text-sm font-medium text-white mb-2">Karten pro Sitzung</label>
                            <input
                                type="number"
                                value={settings.cards_per_session}
                                onChange={(e) => setSettings({ ...settings, cards_per_session: parseInt(e.target.value) || 20 })}
                                className="w-full px-4 py-3 bg-dark-800 border border-dark-700 rounded-xl text-white focus:outline-none focus:border-brain-500"
                                min={1}
                                max={100}
                            />
                            <p className="text-xs text-dark-500 mt-1">Maximale Anzahl Karten pro Lernsitzung</p>
                        </div>
                        <div>
                            <label className="block text-sm font-medium text-white mb-2">Neue Karten pro Tag</label>
                            <input
                                type="number"
                                value={settings.max_new_cards_per_day}
                                onChange={(e) => setSettings({ ...settings, max_new_cards_per_day: parseInt(e.target.value) || 10 })}
                                className="w-full px-4 py-3 bg-dark-800 border border-dark-700 rounded-xl text-white focus:outline-none focus:border-brain-500"
                                min={0}
                                max={50}
                            />
                            <p className="text-xs text-dark-500 mt-1">Maximale Anzahl neuer Karten pro Tag</p>
                        </div>
                        <div>
                            <label className="block text-sm font-medium text-white mb-2">Minimaler Einfachheitsfaktor</label>
                            <input
                                type="number"
                                step="0.1"
                                value={settings.min_easiness}
                                onChange={(e) => setSettings({ ...settings, min_easiness: parseFloat(e.target.value) || 1.3 })}
                                className="w-full px-4 py-3 bg-dark-800 border border-dark-700 rounded-xl text-white focus:outline-none focus:border-brain-500"
                                min={1.0}
                                max={3.0}
                            />
                            <p className="text-xs text-dark-500 mt-1">SM-2 Einfachheitsfaktor (Standard: 1.3)</p>
                        </div>
                    </div>
                </div>
            </div>
        );
    }

    // All cards view
    if (view === 'cards') {
        return (
            <div className="h-full flex flex-col">
                <div className="flex items-center justify-between px-6 py-4 border-b border-dark-800 bg-dark-900/50">
                    <button onClick={() => setView('home')} className="text-sm text-dark-400 hover:text-white transition-colors">
                        ← Zurück
                    </button>
                    <h1 className="text-lg font-semibold text-white">Alle Karten ({allCards.length})</h1>
                    <div />
                </div>
                <div className="flex-1 overflow-y-auto p-4">
                    <div className="max-w-3xl mx-auto space-y-2">
                        {allCards.length === 0 ? (
                            <div className="text-center py-12">
                                <FiBookOpen className="w-12 h-12 text-dark-700 mx-auto mb-4" />
                                <p className="text-dark-500">Noch keine Karteikarten erstellt</p>
                                <p className="text-xs text-dark-600 mt-1">Öffne eine Notiz und generiere Karteikarten</p>
                            </div>
                        ) : (
                            allCards.map((card) => (
                                <div key={card.id} className="bg-dark-800 border border-dark-700 rounded-xl p-4">
                                    <div className="flex items-start justify-between gap-3">
                                        <div className="flex-1 min-w-0">
                                            {card.note_title && (
                                                <p className="text-[10px] uppercase text-dark-500 tracking-wider mb-1">{card.note_title}</p>
                                            )}
                                            <p className="text-sm text-white font-medium">{card.question}</p>
                                            <p className="text-xs text-dark-400 mt-1 line-clamp-2">{card.answer}</p>
                                            <div className="flex items-center gap-3 mt-2 text-[10px] text-dark-500">
                                                <span>EF: {card.easiness.toFixed(1)}</span>
                                                <span>Intervall: {card.interval}d</span>
                                                <span>Wdh: {card.repetitions}</span>
                                            </div>
                                        </div>
                                        <button
                                            onClick={() => handleDeleteCard(card.id)}
                                            className="p-1.5 hover:bg-dark-700 rounded-lg transition-colors text-dark-500 hover:text-red-400"
                                        >
                                            <FiTrash2 className="w-3.5 h-3.5" />
                                        </button>
                                    </div>
                                </div>
                            ))
                        )}
                    </div>
                </div>
            </div>
        );
    }

    return null;
}
