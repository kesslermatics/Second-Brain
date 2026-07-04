'use client';

import { useEffect, useMemo, useState } from 'react';
import {
    FiCheck, FiX, FiChevronRight, FiTarget, FiMap, FiArrowRight,
} from 'react-icons/fi';
import { LuListChecks, LuPartyPopper } from 'react-icons/lu';
import ReactMarkdown from 'react-markdown';
import { markdownComponents, remarkPlugins, rehypePlugins } from '@/lib/markdownComponents';
import type { CourseUnit, QuizQuestion, LessonRecap } from '@/lib/types';

// ── Accent color theming ─────────────────────────────────────────────
// Teacher panel uses teal, Book panel uses amber. We pass an accent key
// and map it to concrete Tailwind classes (Tailwind can't build dynamic
// class names, so we keep an explicit map).
export type Accent = 'teal' | 'amber';

// Control messages drive the lesson flow but are not real student input.
// They must be hidden from the chat transcript and ignored when detecting
// whether the student has actually written something.
export const CONTROL_MESSAGES = ['[START]', '[NOTIZEN_ERSTELLT]', '[ABSCHNITT_WEITER]'];

export function isControlMessage(content: string): boolean {
    return CONTROL_MESSAGES.includes(content);
}

interface AccentClasses {
    text: string;
    textSoft: string;
    bg: string;
    bgHover: string;
    bgSoft: string;
    bgSoftHover: string;
    border: string;
    ring: string;
    dot: string;
    gradient: string;
}

export const ACCENTS: Record<Accent, AccentClasses> = {
    teal: {
        text: 'text-teal-400',
        textSoft: 'text-teal-300',
        bg: 'bg-teal-600',
        bgHover: 'hover:bg-teal-500',
        bgSoft: 'bg-teal-600/20',
        bgSoftHover: 'hover:bg-teal-600/30',
        border: 'border-teal-500',
        ring: 'ring-teal-500',
        dot: 'bg-teal-500',
        gradient: 'from-teal-500/20',
    },
    amber: {
        text: 'text-amber-400',
        textSoft: 'text-amber-300',
        bg: 'bg-amber-600',
        bgHover: 'hover:bg-amber-500',
        bgSoft: 'bg-amber-600/20',
        bgSoftHover: 'hover:bg-amber-600/30',
        border: 'border-amber-500',
        ring: 'ring-amber-500',
        dot: 'bg-amber-500',
        gradient: 'from-amber-500/20',
    },
};

// ── Lesson objectives card ───────────────────────────────────────────
// Shown at the top of the lesson chat so the student sees at a glance what
// this unit is about — without having to read the intro prose.
export function LessonObjectivesCard({
    unit,
    accent,
    label = 'In dieser Lektion',
}: {
    unit: CourseUnit;
    accent: Accent;
    label?: string;
}) {
    const a = ACCENTS[accent];
    const objectives = unit.learning_objectives || [];
    const hasContent = objectives.length > 0 || !!unit.description;
    if (!hasContent) return null;

    return (
        <div className={`rounded-2xl border border-dark-700 bg-gradient-to-br ${a.gradient} to-dark-800/40 p-4`}>
            <div className="flex items-center gap-2 mb-2">
                <FiTarget className={`w-4 h-4 ${a.text}`} />
                <span className={`text-xs font-semibold uppercase tracking-wider ${a.text}`}>{label}</span>
            </div>
            {unit.description && (
                <p className="text-sm text-dark-300 mb-2 leading-relaxed">{unit.description}</p>
            )}
            {objectives.length > 0 && (
                <ul className="space-y-1.5">
                    {objectives.map((o, i) => (
                        <li key={i} className="flex items-start gap-2 text-sm text-dark-200">
                            <FiCheck className={`w-3.5 h-3.5 mt-0.5 flex-shrink-0 ${a.text}`} />
                            <span>{o}</span>
                        </li>
                    ))}
                </ul>
            )}
        </div>
    );
}

// ── Learning path overlay ────────────────────────────────────────────
// A visible map of all units with their status, so progress is tangible
// and the end is in sight.
export function LearningPathButton({
    accent,
    onClick,
}: {
    accent: Accent;
    onClick: () => void;
}) {
    const a = ACCENTS[accent];
    return (
        <button
            onClick={onClick}
            title="Lernpfad anzeigen"
            className={`flex items-center gap-1.5 px-2.5 py-1.5 text-[10px] ${a.bgSoft} ${a.text} ${a.bgSoftHover} rounded-lg transition-colors`}
        >
            <FiMap className="w-3.5 h-3.5" />
            Lernpfad
        </button>
    );
}

export function LearningPathOverlay({
    units,
    currentUnitId,
    accent,
    title,
    onClose,
    onSelectUnit,
}: {
    units: CourseUnit[];
    currentUnitId: string;
    accent: Accent;
    title: string;
    onClose: () => void;
    onSelectUnit?: (unit: CourseUnit) => void;
}) {
    const a = ACCENTS[accent];
    const enabled = useMemo(
        () => [...units].filter((u) => u.enabled).sort((x, y) => x.order_index - y.order_index),
        [units],
    );
    const lessons = enabled.filter((u) => u.level === 2);
    const doneCount = lessons.filter((u) => u.status === 'completed').length;
    const total = lessons.length || enabled.length;
    const pct = total > 0 ? Math.round((doneCount / total) * 100) : 0;

    return (
        <div className="absolute inset-0 z-20 flex flex-col bg-dark-950/95 backdrop-blur-sm animate-[fadeIn_0.15s_ease-out]">
            <div className="px-4 py-3 border-b border-dark-800 flex items-center justify-between">
                <div className="flex items-center gap-2 min-w-0">
                    <FiMap className={`w-4 h-4 ${a.text}`} />
                    <h3 className="text-sm font-semibold text-white truncate">Lernpfad — {title}</h3>
                </div>
                <button onClick={onClose} className="p-1.5 hover:bg-dark-800 rounded-lg text-dark-500 hover:text-white transition-colors">
                    <FiX className="w-4 h-4" />
                </button>
            </div>

            {/* Overall progress */}
            <div className="px-4 py-3 border-b border-dark-800">
                <div className="flex items-center justify-between mb-1.5">
                    <span className="text-xs text-dark-400">{doneCount} von {total} abgeschlossen</span>
                    <span className={`text-xs font-semibold ${a.text}`}>{pct}%</span>
                </div>
                <div className="h-1.5 bg-dark-800 rounded-full overflow-hidden">
                    <div className={`h-full ${a.dot} rounded-full transition-all`} style={{ width: `${pct}%` }} />
                </div>
            </div>

            {/* Path */}
            <div className="flex-1 overflow-y-auto p-4">
                <div className="max-w-xl mx-auto space-y-1">
                    {enabled.map((u, idx) => {
                        const isModule = u.level === 1;
                        const isCurrent = u.id === currentUnitId;
                        const done = u.status === 'completed';
                        const skipped = u.status === 'skipped';
                        const clickable = !!onSelectUnit && u.level === 2 && !isCurrent;

                        if (isModule) {
                            return (
                                <div key={u.id} className="pt-3 pb-1 first:pt-0">
                                    <p className="text-[10px] font-semibold uppercase tracking-wider text-dark-500">
                                        {u.title}
                                    </p>
                                </div>
                            );
                        }

                        return (
                            <div key={u.id} className="flex items-stretch gap-3">
                                {/* Connector + node */}
                                <div className="flex flex-col items-center">
                                    <div
                                        className={`w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 text-[10px] font-bold border-2 transition-colors ${done
                                            ? `${a.dot} border-transparent text-white`
                                            : isCurrent
                                                ? `border-2 ${a.border} ${a.text} bg-dark-900`
                                                : 'border-dark-700 text-dark-500 bg-dark-900'
                                            }`}
                                    >
                                        {done ? <FiCheck className="w-3.5 h-3.5" /> : idx + 1}
                                    </div>
                                    {idx < enabled.length - 1 && (
                                        <div className={`w-0.5 flex-1 min-h-[8px] ${done ? a.dot : 'bg-dark-700'}`} />
                                    )}
                                </div>

                                {/* Label */}
                                <button
                                    disabled={!clickable}
                                    onClick={() => clickable && onSelectUnit!(u)}
                                    className={`flex-1 text-left py-1.5 mb-1 min-w-0 ${clickable ? 'cursor-pointer hover:text-white' : 'cursor-default'}`}
                                >
                                    <p className={`text-sm truncate ${isCurrent ? `${a.text} font-semibold` : done ? 'text-dark-300' : 'text-dark-400'}`}>
                                        {u.title}
                                    </p>
                                    <p className="text-[10px] text-dark-600">
                                        {isCurrent ? 'Aktuell' : done ? 'Abgeschlossen' : skipped ? 'Übersprungen' : 'Ausstehend'}
                                    </p>
                                </button>
                            </div>
                        );
                    })}
                </div>
            </div>
        </div>
    );
}

// ── Lesson-complete celebration ──────────────────────────────────────
export function LessonCompleteCelebration({
    unitTitle,
    recap,
    accent,
    isLastUnit,
    nextLabel,
    onContinue,
    loadingRecap,
}: {
    unitTitle: string;
    recap: LessonRecap | null;
    accent: Accent;
    isLastUnit: boolean;
    nextLabel: string;
    onContinue: () => void;
    loadingRecap: boolean;
}) {
    const a = ACCENTS[accent];

    return (
        <div className="h-full flex flex-col items-center justify-center p-4 relative overflow-hidden">
            <Confetti accent={accent} />
            <div className="text-center max-w-md relative z-10">
                <div className={`inline-flex items-center justify-center w-20 h-20 rounded-3xl ${a.bgSoft} mb-4 animate-[popIn_0.4s_ease-out]`}>
                    <LuPartyPopper className={`w-10 h-10 ${a.text}`} />
                </div>
                <h3 className="text-xl font-bold text-white mb-1">Geschafft!</h3>
                <p className="text-sm text-dark-400 mb-5">
                    Du hast <span className={`${a.text} font-medium`}>{unitTitle}</span> abgeschlossen
                </p>

                {/* Recap */}
                <div className="bg-dark-800/70 border border-dark-700 rounded-2xl p-4 mb-3 text-left">
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-dark-500 mb-2">
                        Das hast du gelernt
                    </p>
                    {loadingRecap ? (
                        <div className="space-y-2 py-1">
                            <div className="h-3 bg-dark-700 rounded animate-pulse w-full" />
                            <div className="h-3 bg-dark-700 rounded animate-pulse w-4/5" />
                            <div className="h-3 bg-dark-700 rounded animate-pulse w-3/5" />
                        </div>
                    ) : recap && recap.summary_points.length > 0 ? (
                        <ul className="space-y-2">
                            {recap.summary_points.map((p, i) => (
                                <li key={i} className="flex items-start gap-2 text-sm text-dark-200">
                                    <FiCheck className={`w-3.5 h-3.5 mt-0.5 flex-shrink-0 ${a.text}`} />
                                    <span>{p}</span>
                                </li>
                            ))}
                        </ul>
                    ) : (
                        <p className="text-sm text-dark-400">Gut gemacht — weiter so!</p>
                    )}
                </div>

                {/* Next preview */}
                {!isLastUnit && !loadingRecap && recap?.next_preview && (
                    <div className={`rounded-2xl border border-dark-700 bg-gradient-to-br ${a.gradient} to-dark-800/40 p-4 mb-4 text-left`}>
                        <div className="flex items-center gap-2 mb-1.5">
                            <FiArrowRight className={`w-3.5 h-3.5 ${a.text}`} />
                            <span className={`text-[10px] font-semibold uppercase tracking-wider ${a.text}`}>Als Nächstes</span>
                        </div>
                        <p className="text-sm text-dark-200 leading-relaxed">{recap.next_preview}</p>
                    </div>
                )}

                <button
                    onClick={onContinue}
                    className={`w-full flex items-center justify-center gap-2 px-4 py-3 ${a.bg} ${a.bgHover} text-white text-sm font-semibold rounded-xl transition-colors`}
                >
                    {isLastUnit ? 'Abschließen' : nextLabel}
                    <FiChevronRight className="w-4 h-4" />
                </button>
            </div>
        </div>
    );
}

// ── Confetti (dependency-free) ───────────────────────────────────────
function Confetti({ accent }: { accent: Accent }) {
    const pieces = useMemo(() => {
        const colors = accent === 'teal'
            ? ['#2dd4bf', '#14b8a6', '#5eead4', '#0d9488', '#99f6e4']
            : ['#fbbf24', '#f59e0b', '#fcd34d', '#d97706', '#fde68a'];
        return Array.from({ length: 70 }, (_, i) => ({
            id: i,
            left: Math.random() * 100,
            delay: Math.random() * 0.6,
            duration: 2.2 + Math.random() * 1.6,
            color: colors[i % colors.length],
            size: 6 + Math.random() * 6,
            rotate: Math.random() * 360,
        }));
    }, [accent]);

    const [show, setShow] = useState(true);
    useEffect(() => {
        const t = setTimeout(() => setShow(false), 4200);
        return () => clearTimeout(t);
    }, []);
    if (!show) return null;

    return (
        <div className="pointer-events-none absolute inset-0 overflow-hidden">
            {pieces.map((p) => (
                <span
                    key={p.id}
                    className="absolute top-[-20px] rounded-sm"
                    style={{
                        left: `${p.left}%`,
                        width: `${p.size}px`,
                        height: `${p.size * 0.6}px`,
                        backgroundColor: p.color,
                        transform: `rotate(${p.rotate}deg)`,
                        animation: `confettiFall ${p.duration}s linear ${p.delay}s forwards`,
                    }}
                />
            ))}
        </div>
    );
}


// ── "Thinking" status line ───────────────────────────────────────────
// A single, gently cross-fading line that shows what the tutor is doing right
// now (German, warm, generated by the Flash model on the backend). Replaces the
// old growing chip-list of raw tool names.
export function ThinkingStatus({ status, accent }: { status: string; accent: Accent }) {
    const a = ACCENTS[accent];
    return (
        <div className="flex items-center gap-2.5 text-xs text-dark-400">
            <div className="flex gap-0.5">
                <div className={`w-1.5 h-1.5 ${a.dot} rounded-full animate-pulse`} />
                <div className={`w-1.5 h-1.5 ${a.dot} rounded-full animate-pulse`} style={{ animationDelay: '0.15s' }} />
                <div className={`w-1.5 h-1.5 ${a.dot} rounded-full animate-pulse`} style={{ animationDelay: '0.3s' }} />
            </div>
            <span key={status} className="status-line italic">
                {status || 'Ich denke kurz nach …'}
            </span>
        </div>
    );
}

// ── Silent note-saved toast ──────────────────────────────────────────
// The tutor saves notes on its own. We surface that with a small, self-dismissing
// toast so the student notices without any interaction being required.
export interface SavedNoteToast {
    id: string;
    title: string;
    action: 'created' | 'updated';
}

export function NoteToastHost({
    toasts,
    accent,
    onDismiss,
}: {
    toasts: SavedNoteToast[];
    accent: Accent;
    onDismiss: (id: string) => void;
}) {
    const a = ACCENTS[accent];
    return (
        <div className="pointer-events-none absolute bottom-24 right-4 z-30 flex flex-col gap-2 items-end">
            {toasts.map((t) => (
                <NoteToast key={t.id} toast={t} accent={a} onDismiss={() => onDismiss(t.id)} />
            ))}
        </div>
    );
}

function NoteToast({
    toast,
    accent,
    onDismiss,
}: {
    toast: SavedNoteToast;
    accent: AccentClasses;
    onDismiss: () => void;
}) {
    const [leaving, setLeaving] = useState(false);
    useEffect(() => {
        const t1 = setTimeout(() => setLeaving(true), 3200);
        const t2 = setTimeout(onDismiss, 3600);
        return () => { clearTimeout(t1); clearTimeout(t2); };
    }, [onDismiss]);

    return (
        <div
            className={`pointer-events-auto flex items-center gap-2.5 pl-2.5 pr-3 py-2 rounded-xl bg-dark-800/95 backdrop-blur border border-dark-700 shadow-lg shadow-black/30 max-w-xs ${leaving ? 'toast-leave' : 'toast-enter'}`}
        >
            <div className={`flex items-center justify-center w-6 h-6 rounded-lg ${accent.bgSoft} flex-shrink-0`}>
                <FiCheck className={`w-3.5 h-3.5 ${accent.text} check-pop`} />
            </div>
            <div className="min-w-0">
                <p className="text-[10px] uppercase tracking-wider text-dark-500 leading-none mb-0.5">
                    {toast.action === 'updated' ? 'Notiz ergänzt' : 'Notiz gespeichert'}
                </p>
                <p className="text-xs text-dark-100 truncate">{toast.title}</p>
            </div>
        </div>
    );
}

// ── Inline quiz card (lives inside the chat, not a full screen) ───────
export function InlineQuiz({
    questions,
    accent,
    onFinished,
}: {
    questions: QuizQuestion[];
    accent: Accent;
    onFinished?: (score: number, total: number) => void;
}) {
    const a = ACCENTS[accent];
    const [idx, setIdx] = useState(0);
    const [selected, setSelected] = useState<number | null>(null);
    const [revealed, setRevealed] = useState(false);
    const [score, setScore] = useState(0);
    const [done, setDone] = useState(false);

    const q = questions[idx];
    const total = questions.length;
    const isLast = idx === total - 1;

    if (!q) return null;

    const choose = (i: number) => {
        if (revealed) return;
        setSelected(i);
        setRevealed(true);
        if (i === q.correct_index) setScore((s) => s + 1);
    };

    const next = () => {
        if (isLast) {
            setDone(true);
            onFinished?.(score, total);
            return;
        }
        setIdx((v) => v + 1);
        setSelected(null);
        setRevealed(false);
    };

    if (done) {
        const pct = total > 0 ? Math.round((score / total) * 100) : 0;
        return (
            <div className={`slide-up rounded-2xl border border-dark-700 bg-gradient-to-br ${a.gradient} to-dark-800/40 p-4 text-center`}>
                <div className={`inline-flex items-center justify-center w-11 h-11 rounded-xl ${a.bgSoft} mb-2`}>
                    <LuListChecks className={`w-6 h-6 ${a.text}`} />
                </div>
                <p className="text-sm font-semibold text-white">
                    {score} von {total} richtig
                </p>
                <p className="text-xs text-dark-400 mt-0.5">
                    {pct >= 70 ? 'Stark — das sitzt!' : 'Schau dir die kniffligen Punkte gern nochmal an.'}
                </p>
            </div>
        );
    }

    return (
        <div className={`slide-up rounded-2xl border border-dark-700 bg-dark-900/70 overflow-hidden`}>
            <div className="px-4 py-2.5 border-b border-dark-800 flex items-center gap-2">
                <LuListChecks className={`w-4 h-4 ${a.text}`} />
                <span className="text-xs font-semibold text-white">Kurzer Check</span>
                <span className="text-[10px] text-dark-500 ml-auto">Frage {idx + 1}/{total}</span>
            </div>
            <div className="h-0.5 bg-dark-800">
                <div className={`h-full ${a.dot} transition-all`} style={{ width: `${((idx + (revealed ? 1 : 0)) / total) * 100}%` }} />
            </div>
            <div className="p-4">
                <p className="text-sm font-medium text-white mb-3 leading-relaxed">{q.question}</p>
                <div className="space-y-1.5">
                    {q.options.map((opt, i) => {
                        const isCorrect = i === q.correct_index;
                        const isChosen = i === selected;
                        let cls = 'border-dark-700 bg-dark-800 hover:border-dark-600 text-dark-200';
                        if (revealed) {
                            if (isCorrect) cls = 'border-green-500 bg-green-900/20 text-green-300';
                            else if (isChosen) cls = 'border-red-500 bg-red-900/20 text-red-300';
                            else cls = 'border-dark-700 bg-dark-800 text-dark-500 opacity-60';
                        }
                        return (
                            <button
                                key={i}
                                onClick={() => choose(i)}
                                disabled={revealed}
                                className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg border text-left text-sm transition-colors ${cls} disabled:cursor-default`}
                            >
                                <span className={`w-5 h-5 rounded-full border flex items-center justify-center text-[11px] flex-shrink-0 ${revealed && isCorrect ? 'border-green-500 text-green-400' : revealed && isChosen ? 'border-red-500 text-red-400' : 'border-dark-600 text-dark-500'}`}>
                                    {revealed && isCorrect ? <FiCheck className="w-3 h-3" /> : revealed && isChosen ? <FiX className="w-3 h-3" /> : String.fromCharCode(65 + i)}
                                </span>
                                <span className="flex-1">{opt}</span>
                            </button>
                        );
                    })}
                </div>
                {revealed && q.explanation && (
                    <div className="mt-3 p-2.5 rounded-lg bg-dark-800 border border-dark-700">
                        <p className="text-xs text-dark-300 leading-relaxed">
                            <span className={`font-semibold ${selected === q.correct_index ? 'text-green-400' : a.text}`}>
                                {selected === q.correct_index ? 'Richtig! ' : 'Erklärung: '}
                            </span>
                            {q.explanation}
                        </p>
                    </div>
                )}
                {revealed && (
                    <button
                        onClick={next}
                        className={`mt-3 w-full flex items-center justify-center gap-2 px-4 py-2 ${a.bg} ${a.bgHover} text-white text-sm font-medium rounded-lg transition-colors`}
                    >
                        {isLast ? 'Fertig' : 'Nächste Frage'}
                        <FiChevronRight className="w-4 h-4" />
                    </button>
                )}
            </div>
        </div>
    );
}
