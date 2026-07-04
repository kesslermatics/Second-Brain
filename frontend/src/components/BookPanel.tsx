'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import {
    FiCheck, FiX, FiChevronRight, FiSearch, FiSquare, FiCheckSquare,
    FiSend, FiTrash2, FiArrowLeft, FiBook,
    FiChevronDown, FiFileText, FiRefreshCw, FiMessageCircle,
} from 'react-icons/fi';
import ReactMarkdown from 'react-markdown';
import { markdownComponents, remarkPlugins, rehypePlugins } from '@/lib/markdownComponents';
import { useStore } from '@/lib/store';
import {
    searchBook, getBookToc,
    getBookCourses, getTeacherCourse, deleteTeacherCourse,
    createBookCourse, updateCourseStatus, updateCourseUnit,
    getUnitMessages, sendTeacherChat, sendTeacherChatStream,
    generateUnitQuiz, generateUnitRecap,
    getBookSummaries, generateChapterSummary,
    type TeacherSavedNote,
} from '@/lib/api';
import type {
    BookSearchResult, BookChapter,
    CourseListItem, CourseDetail, CourseUnit, CourseMessage,
    BookSummaryChapter, QuizQuestion, LessonRecap, LessonDiagram,
} from '@/lib/types';
import {
    LessonObjectivesCard, LearningPathButton, LearningPathOverlay,
    LessonCompleteCelebration, isControlMessage,
    ThinkingStatus, NoteToastHost, InlineQuiz, type SavedNoteToast,
} from './TeachingComponents';
import MermaidDiagram from './MermaidDiagram';
import { CategoryBadge, CategoryFilter } from './CategoryUI';
import { CATEGORY_ORDER } from '@/lib/categories';

type View =
    | { kind: 'books' }
    | { kind: 'confirm-book'; bookInfo: BookSearchResult }
    | { kind: 'loading-toc'; bookInfo: BookSearchResult }
    | { kind: 'confirm-toc'; bookInfo: BookSearchResult; chapters: BookChapter[] }
    | { kind: 'lesson-chat'; course: CourseDetail; unit: CourseUnit }
    | { kind: 'lesson-complete'; course: CourseDetail; unit: CourseUnit }
    | { kind: 'book-completed'; course: CourseDetail }
    | { kind: 'book-summaries'; courseId: string; title: string; authors: string[] };

// ── URL state (book course/unit) — survives reload, doesn't touch nav ─
const URL_COURSE = 'bcourse';
const URL_UNIT = 'bunit';

function readUrlState(): { courseId: string | null; unitId: string | null } {
    if (typeof window === 'undefined') return { courseId: null, unitId: null };
    const p = new URLSearchParams(window.location.search);
    return { courseId: p.get(URL_COURSE), unitId: p.get(URL_UNIT) };
}

function writeUrlState(courseId: string | null, unitId: string | null) {
    if (typeof window === 'undefined') return;
    const p = new URLSearchParams(window.location.search);
    if (courseId) p.set(URL_COURSE, courseId); else p.delete(URL_COURSE);
    if (unitId) p.set(URL_UNIT, unitId); else p.delete(URL_UNIT);
    const qs = p.toString();
    const url = qs ? `${window.location.pathname}?${qs}` : window.location.pathname;
    window.history.replaceState(window.history.state, '', url);
}

function messageExtras(msg: CourseMessage): { diagrams: LessonDiagram[]; checkpoints: string[] } {
    const md = (msg.metadata || {}) as Record<string, unknown>;
    const diagrams = Array.isArray(md.diagrams) ? (md.diagrams as LessonDiagram[]) : [];
    const checkpoints = Array.isArray(md.checkpoints) ? (md.checkpoints as string[]) : [];
    return { diagrams, checkpoints };
}

// ── Book cover with a graceful fallback ──────────────────────────────
// Renders the real cover when available; otherwise a stylised spine-like
// placeholder so the shelf stays visually consistent.
function BookCover({
    url,
    title,
    className = '',
}: {
    url?: string | null;
    title?: string;
    className?: string;
}) {
    const [failed, setFailed] = useState(false);
    const showImage = url && !failed;
    return (
        <div className={`relative overflow-hidden rounded-md bg-gradient-to-br from-amber-900/40 to-dark-800 ring-1 ring-black/30 ${className}`}>
            {showImage ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                    src={url!}
                    alt={`Cover von ${title || 'Buch'}`}
                    className="w-full h-full object-cover"
                    onError={() => setFailed(true)}
                />
            ) : (
                <div className="w-full h-full flex flex-col items-center justify-center p-2 text-center">
                    <FiBook className="w-5 h-5 text-amber-400/70 mb-1" />
                    <span className="text-[8px] leading-tight text-amber-100/60 line-clamp-3">{title}</span>
                </div>
            )}
        </div>
    );
}

export default function BookPanel() {
    // ── State ────────────────────────────────────────────────────────
    const [view, setView] = useState<View>({ kind: 'books' });
    const [courses, setCourses] = useState<CourseListItem[]>([]);
    const [loadingCourses, setLoadingCourses] = useState(true);
    const [error, setError] = useState<string | null>(null);

    // Search
    const [searchQuery, setSearchQuery] = useState('');
    const [searching, setSearching] = useState(false);

    // TOC confirmation
    const [enabledChapters, setEnabledChapters] = useState<Record<string, boolean>>({});

    // Category filter for the shelf
    const [categoryFilter, setCategoryFilter] = useState<string | null>(null);

    // Chat
    const [messages, setMessages] = useState<CourseMessage[]>([]);
    const [chatInput, setChatInput] = useState('');
    const [sendingChat, setSendingChat] = useState(false);
    const [statusLine, setStatusLine] = useState('');

    // Silent-save toasts + tutor-driven inline quiz
    const [toasts, setToasts] = useState<SavedNoteToast[]>([]);
    const [inlineQuiz, setInlineQuiz] = useState<QuizQuestion[] | null>(null);

    // Recap / learning path
    const [recap, setRecap] = useState<LessonRecap | null>(null);
    const [loadingRecap, setLoadingRecap] = useState(false);
    const [showPath, setShowPath] = useState(false);

    // Section walk-through state for the current chapter
    const [section, setSection] = useState<{ current: number; total: number }>({ current: 0, total: 0 });

    // Prefetched caches
    const prefetchedMessagesRef = useRef<Map<string, CourseMessage[]>>(new Map());
    const prefetchedSectionRef = useRef<Map<string, { current: number; total: number }>>(new Map());

    // Summaries
    const [summaryChapters, setSummaryChapters] = useState<BookSummaryChapter[]>([]);
    const [loadingSummaries, setLoadingSummaries] = useState(false);
    const [expandedChapters, setExpandedChapters] = useState<Record<string, boolean>>({});
    const [generatingSummaryFor, setGeneratingSummaryFor] = useState<string | null>(null);

    const chatEndRef = useRef<HTMLDivElement>(null);
    const lastAssistantRef = useRef<HTMLDivElement>(null);
    const chatInputRef = useRef<HTMLTextAreaElement>(null);
    const restoredRef = useRef(false);
    const { loadFolderTree } = useStore();

    // ── Toast helpers ────────────────────────────────────────────────
    const pushToast = useCallback((note: TeacherSavedNote) => {
        const id = `${note.note_id}-${Date.now()}`;
        setToasts((prev) => [...prev, { id, title: note.title, action: note.action }]);
    }, []);
    const dismissToast = useCallback((id: string) => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
    }, []);

    // ── Load book courses ────────────────────────────────────────────
    const loadCourses = useCallback(async () => {
        setLoadingCourses(true);
        try {
            const data = await getBookCourses();
            setCourses(data);
        } catch {
            setError('Fehler beim Laden der Bücher');
        } finally {
            setLoadingCourses(false);
        }
    }, []);

    useEffect(() => {
        loadCourses();
    }, [loadCourses]);

    useEffect(() => {
        if (view.kind === 'lesson-chat' && messages.length > 0) {
            const lastMsg = messages[messages.length - 1];
            if (lastMsg.role === 'assistant' && lastAssistantRef.current) {
                lastAssistantRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
            } else {
                chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
            }
        }
    }, [messages, view]);

    // Keep URL in sync with the current chapter
    useEffect(() => {
        if (view.kind === 'lesson-chat') {
            writeUrlState(view.course.id, view.unit.id);
        } else if (view.kind === 'books') {
            writeUrlState(null, null);
        }
    }, [view]);

    // Restore from URL on first mount
    useEffect(() => {
        if (restoredRef.current) return;
        restoredRef.current = true;
        const { courseId, unitId } = readUrlState();
        if (!courseId) return;
        (async () => {
            try {
                const course = await getTeacherCourse(courseId);
                if ((course.kind || 'teacher') !== 'book') return;
                const unit = unitId
                    ? course.units.find((u) => u.id === unitId)
                    : course.units.find((u) => u.enabled && (u.status === 'active' || u.status === 'pending'));
                if (unit) await openUnitChat(course, unit);
            } catch { /* stale link */ }
        })();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const resetLessonEphemeral = () => {
        setStatusLine('');
        setInlineQuiz(null);
    };

    // ── Search book ──────────────────────────────────────────────────
    const handleSearch = async () => {
        if (!searchQuery.trim() || searching) return;
        setSearching(true);
        setError(null);
        try {
            const result = await searchBook(searchQuery.trim());
            if (result.found) {
                setView({ kind: 'confirm-book', bookInfo: result });
            } else {
                setError(result.suggestion || 'Kein passendes Buch gefunden.');
            }
        } catch {
            setError('Fehler bei der Buchsuche.');
        } finally {
            setSearching(false);
        }
    };

    const handleConfirmBook = async (bookInfo: BookSearchResult) => {
        setView({ kind: 'loading-toc', bookInfo });
        setError(null);
        try {
            const toc = await getBookToc(bookInfo.title!, bookInfo.authors || []);
            if (toc.chapters.length === 0) {
                setError('Konnte kein Inhaltsverzeichnis finden.');
                setView({ kind: 'confirm-book', bookInfo });
                return;
            }
            const defaults: Record<string, boolean> = {};
            toc.chapters.forEach((ch) => { defaults[ch.chapter_number] = true; });
            setEnabledChapters(defaults);
            setView({ kind: 'confirm-toc', bookInfo, chapters: toc.chapters });
        } catch {
            setError('Fehler beim Laden des Inhaltsverzeichnisses.');
            setView({ kind: 'confirm-book', bookInfo });
        }
    };

    const handleStartBookCourse = async (bookInfo: BookSearchResult, chapters: BookChapter[]) => {
        setError(null);
        try {
            const selectedChapters = chapters.map(ch => ({
                chapter_number: ch.chapter_number,
                title: ch.title,
                level: ch.level,
                enabled: enabledChapters[ch.chapter_number] !== false,
            }));
            const course = await createBookCourse(
                {
                    title: bookInfo.title!,
                    authors: bookInfo.authors || [],
                    description: bookInfo.description || '',
                    year: bookInfo.year,
                    isbn: bookInfo.isbn,
                    publisher: bookInfo.publisher,
                    cover_url: bookInfo.cover_url,
                },
                selectedChapters,
            );
            const firstUnit = course.units.find((u) => u.enabled && u.status === 'pending');
            if (firstUnit) await openUnitChat(course, firstUnit);
        } catch {
            setError('Fehler beim Erstellen des Buchkurses.');
        }
    };

    const handleResumeCourse = async (courseId: string) => {
        setError(null);
        try {
            const course = await getTeacherCourse(courseId);
            const currentUnit = course.units.find(
                (u) => u.enabled && (u.status === 'active' || u.status === 'pending')
            );
            if (currentUnit) {
                await openUnitChat(course, currentUnit);
            } else {
                setView({ kind: 'book-completed', course });
            }
        } catch {
            setError('Fehler beim Laden des Buches.');
        }
    };

    // ── Open unit chat ───────────────────────────────────────────────
    const openUnitChat = async (course: CourseDetail, unit: CourseUnit) => {
        setView({ kind: 'lesson-chat', course, unit });
        resetLessonEphemeral();

        const cached = prefetchedMessagesRef.current.get(unit.id);
        prefetchedMessagesRef.current.delete(unit.id);

        if (cached && cached.length > 0) {
            setMessages(cached);
            const cachedSection = prefetchedSectionRef.current.get(unit.id);
            prefetchedSectionRef.current.delete(unit.id);
            setSection(cachedSection || {
                current: unit.current_section || 0,
                total: unit.sections?.length || 0,
            });
            prefetchNextUnit(course, unit);
            return;
        }

        setMessages([]);
        setSection({ current: unit.current_section || 0, total: unit.sections?.length || 0 });
        try {
            const msgs = await getUnitMessages(course.id, unit.id);
            setMessages(msgs);
            if (msgs.length === 0) {
                setSendingChat(true);
                setStatusLine('');
                const response = await streamTurn(course.id, unit.id, '[START]');
                setMessages([
                    { id: 'start', role: 'user', content: '[START]', metadata: null, created_at: null },
                    response.message,
                ]);
                setSection({ current: response.current_section, total: response.total_sections });
                await afterTurn(course.id, unit.id, response);
                setSendingChat(false);
            }
            prefetchNextUnit(course, unit);
        } catch {
            setError('Fehler beim Laden des Chats.');
        } finally {
            setSendingChat(false);
        }
    };

    const prefetchNextUnit = (course: CourseDetail, currentUnit: CourseUnit) => {
        const sorted = [...course.units].sort((a, b) => a.order_index - b.order_index);
        const curIdx = sorted.findIndex(u => u.id === currentUnit.id);
        const nextUnit = sorted.slice(curIdx + 1).find(
            u => u.enabled && (u.status === 'pending' || u.status === 'active')
        );
        if (!nextUnit) return;
        if (prefetchedMessagesRef.current.has(nextUnit.id)) return;
        getUnitMessages(course.id, nextUnit.id).then(msgs => {
            if (msgs.length > 0) {
                prefetchedMessagesRef.current.set(nextUnit.id, msgs);
            } else {
                sendTeacherChat(course.id, nextUnit.id, '[START]').then(response => {
                    prefetchedMessagesRef.current.set(nextUnit.id, [
                        { id: 'start', role: 'user', content: '[START]', metadata: null, created_at: null },
                        response.message,
                    ]);
                    prefetchedSectionRef.current.set(nextUnit.id, {
                        current: response.current_section,
                        total: response.total_sections,
                    });
                }).catch(() => { });
            }
        }).catch(() => { });
    };

    // ── Shared stream handler ────────────────────────────────────────
    const streamTurn = async (courseId: string, unitId: string, message: string) => {
        setStatusLine('');
        return sendTeacherChatStream(courseId, unitId, message, (event) => {
            if (event.type === 'status') {
                setStatusLine(event.content);
            } else if (event.type === 'note_saved') {
                pushToast(event.note);
            }
        });
    };

    const afterTurn = async (
        courseId: string,
        unitId: string,
        response: Awaited<ReturnType<typeof sendTeacherChatStream>>,
    ) => {
        setStatusLine('');
        if (response.quiz_suggested) {
            try {
                const questions = await generateUnitQuiz(courseId, unitId);
                if (questions.length > 0) setInlineQuiz(questions);
            } catch { /* non-fatal */ }
        }
    };

    // ── Send chat message ────────────────────────────────────────────
    const handleSendMessage = async () => {
        if (!chatInput.trim() || sendingChat || view.kind !== 'lesson-chat') return;
        const msg = chatInput.trim();
        setChatInput('');
        setSendingChat(true);
        setInlineQuiz(null);

        const tempId = `temp-${Date.now()}`;
        setMessages((prev) => [
            ...prev,
            { id: tempId, role: 'user', content: msg, metadata: null, created_at: new Date().toISOString() },
        ]);

        try {
            const response = await streamTurn(view.course.id, view.unit.id, msg);
            setMessages((prev) => [
                ...prev.filter((m) => m.id !== tempId),
                { id: tempId, role: 'user', content: msg, metadata: null, created_at: new Date().toISOString() },
                response.message,
            ]);
            setSection({ current: response.current_section, total: response.total_sections });
            await afterTurn(view.course.id, view.unit.id, response);
        } catch {
            setError('Fehler beim Senden der Nachricht.');
            setMessages((prev) => prev.filter((m) => m.id !== tempId));
        } finally {
            setStatusLine('');
            setSendingChat(false);
            chatInputRef.current?.focus();
        }
    };

    const handleNextSection = async () => {
        if (view.kind !== 'lesson-chat' || sendingChat) return;
        setSendingChat(true);
        setInlineQuiz(null);
        try {
            const response = await streamTurn(view.course.id, view.unit.id, '[ABSCHNITT_WEITER]');
            setMessages((prev) => [...prev, response.message]);
            setSection({ current: response.current_section, total: response.total_sections });
            await afterTurn(view.course.id, view.unit.id, response);
        } catch {
            setError('Fehler beim Laden des nächsten Abschnitts.');
        } finally {
            setStatusLine('');
            setSendingChat(false);
        }
    };

    const isLastEnabledUnit = (course: CourseDetail, currentUnit: CourseUnit) => {
        const sorted = [...course.units].sort((a, b) => a.order_index - b.order_index);
        const curIdx = sorted.findIndex(u => u.id === currentUnit.id);
        return !sorted.slice(curIdx + 1).some(
            u => u.enabled && (u.status === 'pending' || u.status === 'active')
        );
    };

    const handleCompleteUnit = async () => {
        if (view.kind !== 'lesson-chat') return;
        setError(null);
        const currentCourse = view.course;
        const currentUnit = view.unit;
        updateCourseUnit(currentCourse.id, currentUnit.id, { status: 'completed' }).catch(() => { });
        setRecap(null);
        setLoadingRecap(true);
        setView({ kind: 'lesson-complete', course: currentCourse, unit: currentUnit });
        generateUnitRecap(currentCourse.id, currentUnit.id)
            .then((r) => setRecap(r))
            .catch(() => setRecap(null))
            .finally(() => setLoadingRecap(false));
    };

    const handleAdvanceAfterCelebration = async () => {
        if (view.kind !== 'lesson-complete') return;
        const currentCourse = view.course;
        const currentUnit = view.unit;
        const sorted = [...currentCourse.units].sort((a, b) => a.order_index - b.order_index);
        const curIdx = sorted.findIndex(u => u.id === currentUnit.id);
        const nextUnit = sorted.slice(curIdx + 1).find(
            u => u.enabled && (u.status === 'pending' || u.status === 'active')
        );
        if (nextUnit) {
            await openUnitChat(currentCourse, nextUnit);
        } else {
            try {
                await updateCourseStatus(currentCourse.id, 'completed');
                const final = await getTeacherCourse(currentCourse.id);
                setView({ kind: 'book-completed', course: final });
            } catch {
                setError('Fehler beim Abschließen des Buches.');
            }
        }
    };

    const handleSkipUnit = async () => {
        if (view.kind !== 'lesson-chat') return;
        setError(null);
        const currentCourse = view.course;
        const currentUnit = view.unit;
        const sorted = [...currentCourse.units].sort((a, b) => a.order_index - b.order_index);
        const curIdx = sorted.findIndex(u => u.id === currentUnit.id);
        const nextUnit = sorted.slice(curIdx + 1).find(
            u => u.enabled && (u.status === 'pending' || u.status === 'active')
        );
        updateCourseUnit(currentCourse.id, currentUnit.id, { status: 'skipped' }).catch(() => { });
        if (nextUnit) {
            await openUnitChat(currentCourse, nextUnit);
        } else {
            try {
                await updateCourseStatus(currentCourse.id, 'completed');
                const final = await getTeacherCourse(currentCourse.id);
                setView({ kind: 'book-completed', course: final });
            } catch {
                setError('Fehler beim Überspringen.');
            }
        }
    };

    const handleDeleteCourse = async (courseId: string) => {
        try {
            await deleteTeacherCourse(courseId);
            await loadCourses();
        } catch {
            setError('Fehler beim Löschen.');
        }
    };

    // ── Summaries ────────────────────────────────────────────────────
    const handleOpenSummaries = async (course: CourseListItem) => {
        setView({
            kind: 'book-summaries',
            courseId: course.id,
            title: course.title,
            authors: course.book_authors || [],
        });
        setLoadingSummaries(true);
        setSummaryChapters([]);
        setExpandedChapters({});
        setError(null);
        try {
            const data = await getBookSummaries(course.id);
            setSummaryChapters(data.chapters);
            const firstWithSummary = data.chapters.find(ch => ch.summary);
            if (firstWithSummary) {
                setExpandedChapters({ [firstWithSummary.id]: true });
            }
        } catch {
            setError('Fehler beim Laden der Zusammenfassungen.');
        } finally {
            setLoadingSummaries(false);
        }
    };

    const handleGenerateSummary = async (courseId: string, unitId: string) => {
        setGeneratingSummaryFor(unitId);
        setError(null);
        try {
            const result = await generateChapterSummary(courseId, unitId);
            setSummaryChapters(prev =>
                prev.map(ch =>
                    ch.id === unitId
                        ? { ...ch, summary: result.summary, summary_generated_at: result.summary_generated_at }
                        : ch
                )
            );
            setExpandedChapters(prev => ({ ...prev, [unitId]: true }));
        } catch {
            setError('Fehler beim Generieren der Zusammenfassung.');
        } finally {
            setGeneratingSummaryFor(null);
        }
    };

    const handleGenerateAllSummaries = async (courseId: string) => {
        const missing = summaryChapters.filter(ch => !ch.summary && (ch.status === 'completed' || ch.status === 'active'));
        for (const ch of missing) {
            await handleGenerateSummary(courseId, ch.id);
        }
    };

    const toggleSummaryChapter = (unitId: string) => {
        setExpandedChapters(prev => ({ ...prev, [unitId]: !prev[unitId] }));
    };

    // ── Chapter checkbox helpers ─────────────────────────────────────
    const toggleChapter = (chapterNumber: string) => {
        setEnabledChapters((prev) => ({
            ...prev,
            [chapterNumber]: prev[chapterNumber] === false ? true : false,
        }));
    };
    const selectAllChapters = (chapters: BookChapter[]) => {
        const next: Record<string, boolean> = {};
        chapters.forEach((ch) => { next[ch.chapter_number] = true; });
        setEnabledChapters(next);
    };
    const deselectAllChapters = (chapters: BookChapter[]) => {
        const next: Record<string, boolean> = {};
        chapters.forEach((ch) => { next[ch.chapter_number] = false; });
        setEnabledChapters(next);
    };
    const enabledCount = (chapters: BookChapter[]) =>
        chapters.filter((ch) => enabledChapters[ch.chapter_number] !== false).length;

    const getUnitProgress = (course: CourseDetail, currentUnit: CourseUnit) => {
        const enabled = course.units.filter((u) => u.enabled);
        const currentIndex = enabled.findIndex((u) => u.id === currentUnit.id);
        return { current: currentIndex + 1, total: enabled.length };
    };

    // ── Render: one book on the shelf ────────────────────────────────
    const renderShelfBook = (course: CourseListItem, isCompleted: boolean) => {
        const pct = course.enabled_units > 0
            ? Math.round((course.completed_units / course.enabled_units) * 100)
            : 0;
        return (
            <div key={course.id} className="group flex flex-col slide-up">
                {/* Cover — click to resume/open */}
                <button
                    onClick={() => handleResumeCourse(course.id)}
                    className="relative block w-full aspect-[2/3] rounded-md overflow-hidden shadow-lg shadow-black/40 ring-1 ring-black/40 transition-transform duration-200 group-hover:-translate-y-1 group-hover:shadow-xl group-hover:shadow-black/50"
                    title={isCompleted ? 'Erneut öffnen' : 'Weiterlesen'}
                >
                    <BookCover url={course.book_cover_url} title={course.title} className="w-full h-full" />

                    {/* Completed check badge */}
                    {isCompleted && (
                        <div className="absolute top-1.5 right-1.5 w-5 h-5 rounded-full bg-green-600 flex items-center justify-center shadow">
                            <FiCheck className="w-3 h-3 text-white" />
                        </div>
                    )}

                    {/* Progress bar overlaid at the bottom for in-progress books */}
                    {!isCompleted && (
                        <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 to-transparent pt-6 pb-1.5 px-1.5">
                            <div className="flex items-center gap-1.5">
                                <div className="flex-1 h-1 bg-white/20 rounded-full overflow-hidden">
                                    <div className="h-full bg-amber-400 rounded-full transition-all" style={{ width: `${pct}%` }} />
                                </div>
                                <span className="text-[9px] text-white/90 font-medium">{pct}%</span>
                            </div>
                        </div>
                    )}

                    {/* Hover actions */}
                    <div className="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center gap-2">
                        <span
                            onClick={(e) => { e.stopPropagation(); handleOpenSummaries(course); }}
                            className="p-2 bg-dark-900/90 hover:bg-dark-800 rounded-lg text-dark-200 transition-colors"
                            title="Kapitel-Zusammenfassungen"
                        >
                            <FiFileText className="w-3.5 h-3.5" />
                        </span>
                        <span
                            onClick={(e) => { e.stopPropagation(); handleDeleteCourse(course.id); }}
                            className="p-2 bg-dark-900/90 hover:bg-dark-800 rounded-lg text-dark-400 hover:text-red-400 transition-colors"
                            title="Löschen"
                        >
                            <FiTrash2 className="w-3.5 h-3.5" />
                        </span>
                    </div>
                </button>

                {/* Shelf edge */}
                <div className="h-1.5 bg-gradient-to-b from-dark-700 to-dark-800 rounded-b-sm shadow-inner" />

                {/* Title + author */}
                <div className="mt-2 px-0.5 min-w-0">
                    <p className={`text-xs font-semibold truncate ${isCompleted ? 'text-dark-300' : 'text-white'}`} title={course.title}>
                        {course.title}
                    </p>
                    {course.book_authors && course.book_authors.length > 0 && (
                        <p className="text-[10px] text-dark-500 truncate">{course.book_authors.join(', ')}</p>
                    )}
                    {course.category && (
                        <div className="mt-1">
                            <CategoryBadge category={course.category} size="xs" />
                        </div>
                    )}
                    <p className="text-[10px] text-dark-600 mt-1">
                        {isCompleted
                            ? `${course.completed_units}/${course.enabled_units} Kapitel · fertig`
                            : `${course.completed_units}/${course.enabled_units} Kapitel`}
                    </p>
                </div>
            </div>
        );
    };

    // ── Render: Books list ───────────────────────────────────────────
    const renderBooksList = () => {
        const present = CATEGORY_ORDER.filter(cat => courses.some(c => c.category === cat));
        const matches = (c: CourseListItem) => !categoryFilter || c.category === categoryFilter;
        const activeDraft = courses.filter(c => c.status !== 'completed' && matches(c));
        const completed = courses.filter(c => c.status === 'completed' && matches(c));

        return (
            <div className="h-full flex flex-col">
                <div className="p-4 border-b border-dark-800">
                    <div className="max-w-lg mx-auto">
                        <div className="flex gap-2">
                            <input
                                type="text"
                                value={searchQuery}
                                onChange={(e) => setSearchQuery(e.target.value)}
                                onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                                placeholder='Buchtitel eingeben, z.B. "Atomic Habits" oder "Clean Code"'
                                className="flex-1 px-4 py-3 bg-dark-800 border border-dark-700 rounded-xl text-white text-sm placeholder-dark-600 focus:outline-none focus:border-amber-500"
                                autoFocus
                            />
                            <button
                                onClick={handleSearch}
                                disabled={!searchQuery.trim() || searching}
                                className="px-4 py-3 bg-amber-600 hover:bg-amber-500 text-white rounded-xl transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                                {searching ? (
                                    <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                                ) : (
                                    <FiSearch className="w-5 h-5" />
                                )}
                            </button>
                        </div>
                        {error && view.kind === 'books' && (
                            <p className="mt-2 text-sm text-red-400">{error}</p>
                        )}
                    </div>
                </div>

                <div className="flex-1 overflow-y-auto p-4">
                    {loadingCourses ? (
                        <div className="flex items-center justify-center py-12">
                            <div className="w-8 h-8 border-2 border-amber-500 border-t-transparent rounded-full animate-spin" />
                        </div>
                    ) : courses.length === 0 ? (
                        <div className="text-center py-12">
                            <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-amber-900/30 mb-4">
                                <FiBook className="w-8 h-8 text-amber-400" />
                            </div>
                            <h3 className="text-lg font-semibold text-white mb-2">Bücher interaktiv durcharbeiten</h3>
                            <p className="text-sm text-dark-500 max-w-md mx-auto">
                                Gib den Titel eines Buches ein. Die KI sucht das Buch, zeigt dir das
                                Inhaltsverzeichnis und erklärt dir jedes Kapitel interaktiv — Notizen
                                entstehen automatisch im Hintergrund.
                            </p>
                        </div>
                    ) : (
                        <div className="max-w-4xl mx-auto space-y-8">
                            {present.length > 1 && (
                                <CategoryFilter
                                    categories={present}
                                    active={categoryFilter}
                                    onSelect={setCategoryFilter}
                                    accentActive="bg-amber-600 text-white border-amber-500"
                                />
                            )}

                            {activeDraft.length > 0 && (
                                <div>
                                    <h3 className="text-[11px] font-semibold uppercase tracking-wider text-dark-500 mb-4 px-1">
                                        Aktuell im Regal
                                    </h3>
                                    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-x-4 gap-y-6">
                                        {activeDraft.map((course) => renderShelfBook(course, false))}
                                    </div>
                                </div>
                            )}

                            {completed.length > 0 && (
                                <div>
                                    <h3 className="text-[11px] font-semibold uppercase tracking-wider text-dark-500 mb-4 px-1">
                                        Durchgelesen
                                    </h3>
                                    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-x-4 gap-y-6">
                                        {completed.map((course) => renderShelfBook(course, true))}
                                    </div>
                                </div>
                            )}

                            {activeDraft.length === 0 && completed.length === 0 && (
                                <p className="text-center text-sm text-dark-500 py-8">
                                    Keine Bücher in dieser Kategorie.
                                </p>
                            )}
                        </div>
                    )}
                </div>
            </div>
        );
    };

    // ── Render: Confirm book ─────────────────────────────────────────
    const renderConfirmBook = () => {
        if (view.kind !== 'confirm-book') return null;
        const { bookInfo } = view;
        return (
            <div className="h-full overflow-y-auto p-4">
                <div className="max-w-lg mx-auto">
                    <button
                        onClick={() => { setView({ kind: 'books' }); setError(null); }}
                        className="flex items-center gap-1 text-xs text-dark-500 hover:text-white mb-4 transition-colors"
                    >
                        <FiArrowLeft className="w-3.5 h-3.5" />
                        Zurück
                    </button>

                    <div className="bg-dark-800 border border-dark-700 rounded-2xl p-6">
                        <div className="flex items-start gap-4 mb-4">
                            {bookInfo.cover_url ? (
                                // eslint-disable-next-line @next/next/no-img-element
                                <img
                                    src={bookInfo.cover_url}
                                    alt={`Cover von ${bookInfo.title || 'Buch'}`}
                                    className="w-20 h-auto max-h-32 object-contain rounded-lg shadow-lg shadow-black/40 flex-shrink-0 bg-dark-900 animate-[fadeIn_0.3s_ease-out]"
                                    onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none'; }}
                                />
                            ) : (
                                <div className="p-3 bg-amber-900/30 rounded-xl flex-shrink-0">
                                    <FiBook className="w-6 h-6 text-amber-400" />
                                </div>
                            )}
                            <div>
                                <h3 className="text-lg font-bold text-white">{bookInfo.title}</h3>
                                <p className="text-sm text-dark-400 mt-1">{bookInfo.authors?.join(', ')}</p>
                                {bookInfo.category && (
                                    <div className="mt-2">
                                        <CategoryBadge category={bookInfo.category} />
                                    </div>
                                )}
                            </div>
                        </div>

                        <div className="space-y-2 text-sm mb-6">
                            {bookInfo.year && (
                                <div className="flex justify-between text-dark-400"><span>Jahr</span><span className="text-white">{bookInfo.year}</span></div>
                            )}
                            {bookInfo.publisher && (
                                <div className="flex justify-between text-dark-400"><span>Verlag</span><span className="text-white">{bookInfo.publisher}</span></div>
                            )}
                            {bookInfo.language && (
                                <div className="flex justify-between text-dark-400"><span>Sprache</span><span className="text-white">{bookInfo.language}</span></div>
                            )}
                            {bookInfo.pages && (
                                <div className="flex justify-between text-dark-400"><span>Seiten</span><span className="text-white">{bookInfo.pages}</span></div>
                            )}
                            {bookInfo.isbn && (
                                <div className="flex justify-between text-dark-400"><span>ISBN</span><span className="text-white font-mono text-xs">{bookInfo.isbn}</span></div>
                            )}
                        </div>

                        {bookInfo.description && (
                            <p className="text-sm text-dark-400 mb-6 leading-relaxed">{bookInfo.description}</p>
                        )}

                        <div className="flex gap-2">
                            <button
                                onClick={() => handleConfirmBook(bookInfo)}
                                className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 bg-amber-600 hover:bg-amber-500 text-white text-sm font-medium rounded-xl transition-colors"
                            >
                                <FiCheck className="w-4 h-4" />
                                Richtig — Inhaltsverzeichnis laden
                            </button>
                            <button
                                onClick={() => { setView({ kind: 'books' }); setError(null); }}
                                className="px-4 py-2.5 bg-dark-700 hover:bg-dark-600 text-dark-300 text-sm rounded-xl transition-colors"
                            >
                                <FiX className="w-4 h-4" />
                            </button>
                        </div>
                        {error && <p className="mt-3 text-sm text-red-400">{error}</p>}
                    </div>
                </div>
            </div>
        );
    };

    // ── Render: Loading TOC ──────────────────────────────────────────
    const renderLoadingToc = () => {
        if (view.kind !== 'loading-toc') return null;
        return (
            <div className="h-full flex items-center justify-center">
                <div className="text-center">
                    <div className="w-12 h-12 border-2 border-amber-500 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
                    <h3 className="text-lg font-semibold text-white mb-2">Inhaltsverzeichnis wird geladen...</h3>
                    <p className="text-sm text-dark-500">
                        <span className="text-amber-400">{view.bookInfo.title}</span>
                    </p>
                </div>
            </div>
        );
    };

    // ── Render: Confirm TOC ──────────────────────────────────────────
    const renderConfirmToc = () => {
        if (view.kind !== 'confirm-toc') return null;
        const { bookInfo, chapters } = view;
        return (
            <div className="h-full overflow-y-auto p-4">
                <div className="max-w-2xl mx-auto">
                    <button
                        onClick={() => { setView({ kind: 'books' }); loadCourses(); setError(null); }}
                        className="flex items-center gap-1 text-xs text-dark-500 hover:text-white mb-4 transition-colors"
                    >
                        <FiArrowLeft className="w-3.5 h-3.5" />
                        Zurück
                    </button>

                    <div className="bg-dark-800 border border-dark-700 rounded-2xl p-6">
                        <div className="mb-4">
                            <h3 className="text-lg font-bold text-white">{bookInfo.title}</h3>
                            <p className="text-sm text-dark-400 mt-1">{bookInfo.authors?.join(', ')}</p>
                        </div>

                        <div className="flex items-center justify-between mb-3">
                            <p className="text-xs text-dark-500">
                                {chapters.length} Kapitel — <span className="text-amber-400">{enabledCount(chapters)} ausgewählt</span>
                            </p>
                            <div className="flex gap-3 text-xs">
                                <button onClick={() => selectAllChapters(chapters)} className="text-dark-400 hover:text-white transition-colors">
                                    Alle auswählen
                                </button>
                                <span className="text-dark-700">|</span>
                                <button onClick={() => deselectAllChapters(chapters)} className="text-dark-400 hover:text-white transition-colors">
                                    Alle abwählen
                                </button>
                            </div>
                        </div>

                        <div className="max-h-[500px] overflow-y-auto space-y-0.5 mb-6 pr-2">
                            {chapters.map((ch, i) => {
                                const enabled = enabledChapters[ch.chapter_number] !== false;
                                return (
                                    <button
                                        key={i}
                                        onClick={() => toggleChapter(ch.chapter_number)}
                                        className={`w-full flex items-center gap-2 py-2 text-sm rounded-lg px-2 transition-colors hover:bg-dark-700/50 ${!enabled ? 'opacity-40' : ''}`}
                                        style={{ paddingLeft: `${(ch.level - 1) * 20 + 8}px` }}
                                    >
                                        {enabled ? (
                                            <FiCheckSquare className="w-3.5 h-3.5 flex-shrink-0 text-amber-400" />
                                        ) : (
                                            <FiSquare className="w-3.5 h-3.5 flex-shrink-0 text-dark-600" />
                                        )}
                                        <span className="text-dark-500 font-mono text-xs w-10 flex-shrink-0 text-left">
                                            {ch.chapter_number}
                                        </span>
                                        <span className={`text-left ${ch.level === 1 ? 'text-white font-semibold' : ch.level === 2 ? 'text-dark-300' : 'text-dark-500'}`}>
                                            {ch.title}
                                        </span>
                                    </button>
                                );
                            })}
                        </div>

                        <div className="flex gap-2">
                            <button
                                onClick={() => handleStartBookCourse(bookInfo, chapters)}
                                disabled={enabledCount(chapters) === 0}
                                className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 bg-amber-600 hover:bg-amber-500 text-white text-sm font-medium rounded-xl transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                                <FiBook className="w-4 h-4" />
                                Buch starten ({enabledCount(chapters)} Kapitel)
                            </button>
                            <button
                                onClick={() => { setView({ kind: 'books' }); loadCourses(); setError(null); }}
                                className="px-4 py-2.5 bg-dark-700 hover:bg-dark-600 text-dark-300 text-sm rounded-xl transition-colors"
                            >
                                <FiX className="w-4 h-4" />
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        );
    };

    // ── Render: Lesson Chat ──────────────────────────────────────────
    const renderLessonChat = () => {
        if (view.kind !== 'lesson-chat') return null;
        const { course, unit } = view;
        const progress = getUnitProgress(course, unit);
        const hasSections = section.total > 0;
        const onLastSection = !hasSections || section.current >= section.total - 1;
        const currentSectionTitle =
            hasSections && unit.sections && unit.sections[section.current]
                ? unit.sections[section.current].title
                : null;

        const visibleMessages = messages.filter(m => m.role !== 'user' || !isControlMessage(m.content));

        return (
            <div className="h-full flex flex-col relative">
                <div className="px-4 py-3 border-b border-dark-800 bg-dark-900/50">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-3 min-w-0">
                            <button
                                onClick={() => { setView({ kind: 'books' }); loadCourses(); }}
                                className="p-1.5 hover:bg-dark-800 rounded-lg text-dark-500 hover:text-white transition-colors flex-shrink-0"
                            >
                                <FiArrowLeft className="w-4 h-4" />
                            </button>
                            {/* Book cover — flush to the left of the chapter title */}
                            <BookCover
                                url={course.book_cover_url}
                                title={course.title}
                                className="w-9 h-[54px] flex-shrink-0 hidden sm:block"
                            />
                            <div className="min-w-0">
                                <div className="flex items-center gap-2">
                                    <span className="text-[10px] text-amber-400 font-medium">
                                        Kapitel {progress.current}/{progress.total}
                                    </span>
                                    <span className="text-dark-500 font-mono text-[10px]">{unit.unit_number}</span>
                                    <h3 className="text-sm font-semibold text-white truncate">{unit.title}</h3>
                                </div>
                                {hasSections ? (
                                    <p className="text-[10px] text-dark-500 truncate">
                                        <span className="text-amber-500/80">Abschnitt {section.current + 1}/{section.total}</span>
                                        {currentSectionTitle ? ` · ${currentSectionTitle}` : ''}
                                    </p>
                                ) : (
                                    <p className="text-[10px] text-dark-500 truncate">
                                        {course.title}{course.book_authors && course.book_authors.length > 0 ? ` · ${course.book_authors.join(', ')}` : ''}
                                    </p>
                                )}
                            </div>
                        </div>
                        <div className="flex items-center gap-1.5 flex-shrink-0">
                            <LearningPathButton accent="amber" onClick={() => setShowPath(true)} />
                            <button
                                onClick={handleSkipUnit}
                                className="px-2.5 py-1.5 text-[10px] bg-dark-700 hover:bg-dark-600 text-dark-400 rounded-lg transition-colors"
                            >
                                Überspringen
                            </button>
                        </div>
                    </div>
                    {hasSections ? (
                        <div className="mt-2 flex items-center gap-1">
                            {Array.from({ length: section.total }).map((_, i) => (
                                <div
                                    key={i}
                                    className={`h-1.5 flex-1 rounded-full transition-colors ${i < section.current ? 'bg-amber-500' : i === section.current ? 'bg-amber-400' : 'bg-dark-800'}`}
                                />
                            ))}
                        </div>
                    ) : (
                        <div className="mt-2 h-1 bg-dark-800 rounded-full overflow-hidden">
                            <div
                                className="h-full bg-amber-500 rounded-full transition-all"
                                style={{ width: `${Math.round((progress.current / progress.total) * 100)}%` }}
                            />
                        </div>
                    )}
                </div>

                {showPath && (
                    <LearningPathOverlay
                        units={course.units}
                        currentUnitId={unit.id}
                        accent="amber"
                        title={course.title}
                        onClose={() => setShowPath(false)}
                        onSelectUnit={(u) => { setShowPath(false); openUnitChat(course, u); }}
                    />
                )}

                <div className="flex-1 overflow-y-auto p-4 space-y-4">
                    <LessonObjectivesCard unit={unit} accent="amber" label="In diesem Kapitel" />
                    {visibleMessages.map((msg, idx, arr) => {
                        const isLastAssistant = msg.role === 'assistant' && idx === arr.length - 1;
                        if (msg.role === 'note_generated') return null;
                        const { diagrams, checkpoints } = msg.role === 'assistant' ? messageExtras(msg) : { diagrams: [], checkpoints: [] };
                        return (
                            <div
                                key={msg.id}
                                ref={isLastAssistant ? lastAssistantRef : undefined}
                                className={`chat-message flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                            >
                                <div
                                    className={`max-w-[85%] sm:max-w-[78%] px-4 py-3 rounded-2xl text-sm ${msg.role === 'user'
                                        ? 'bg-amber-600 text-white rounded-br-md'
                                        : 'bg-dark-900 border border-dark-700 text-dark-100 rounded-bl-md'}`}
                                >
                                    {msg.role === 'assistant' ? (
                                        <>
                                            <div className="markdown-content lesson-prose">
                                                <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins} components={markdownComponents}>
                                                    {msg.content}
                                                </ReactMarkdown>
                                            </div>
                                            {diagrams.map((d, i) => (
                                                <MermaidDiagram key={i} code={d.code} caption={d.caption} />
                                            ))}
                                            {checkpoints.map((q, i) => (
                                                <div key={i} className="mt-3 flex items-start gap-2 px-3 py-2 rounded-xl bg-amber-600/10 border border-amber-500/20">
                                                    <FiMessageCircle className="w-3.5 h-3.5 text-amber-300 mt-0.5 flex-shrink-0" />
                                                    <p className="text-xs text-amber-100">{q}</p>
                                                </div>
                                            ))}
                                        </>
                                    ) : (
                                        <p className="whitespace-pre-wrap">{msg.content}</p>
                                    )}
                                </div>
                            </div>
                        );
                    })}

                    {inlineQuiz && !sendingChat && (
                        <div className="flex justify-start">
                            <div className="w-full max-w-[92%]">
                                <InlineQuiz questions={inlineQuiz} accent="amber" />
                            </div>
                        </div>
                    )}

                    {sendingChat && (
                        <div className="flex justify-start">
                            <div className="bg-dark-800 border border-dark-700 rounded-2xl rounded-bl-md px-4 py-3 max-w-[85%]">
                                <ThinkingStatus status={statusLine} accent="amber" />
                            </div>
                        </div>
                    )}

                    <div ref={chatEndRef} />
                </div>

                <div className="p-3 border-t border-dark-800 bg-dark-900/50">
                    <div className="flex gap-2 items-end">
                        <textarea
                            ref={chatInputRef}
                            value={chatInput}
                            onChange={(e) => setChatInput(e.target.value)}
                            onKeyDown={(e) => {
                                if (e.key === 'Enter' && !e.shiftKey) {
                                    e.preventDefault();
                                    handleSendMessage();
                                }
                            }}
                            placeholder="Frage stellen oder diskutieren..."
                            rows={1}
                            className="flex-1 px-3 py-2.5 bg-dark-800 border border-dark-700 rounded-xl text-white text-sm placeholder-dark-600 focus:outline-none focus:border-amber-500 resize-none min-h-[40px] max-h-[120px]"
                        />
                        <button
                            onClick={handleSendMessage}
                            disabled={!chatInput.trim() || sendingChat}
                            className="p-2.5 bg-dark-700 hover:bg-dark-600 text-white rounded-xl transition-colors disabled:opacity-40 disabled:cursor-not-allowed flex-shrink-0"
                            title="Nachricht senden"
                        >
                            <FiSend className="w-4 h-4" />
                        </button>
                        {!onLastSection ? (
                            <button
                                onClick={handleNextSection}
                                disabled={sendingChat || messages.length < 2}
                                title="Weiter zum nächsten Abschnitt"
                                className="flex items-center gap-1.5 px-4 py-2.5 bg-amber-600 hover:bg-amber-500 text-white text-sm font-semibold rounded-xl transition-colors disabled:opacity-40 disabled:cursor-not-allowed flex-shrink-0"
                            >
                                Weiter
                                <FiChevronRight className="w-4 h-4" />
                            </button>
                        ) : (
                            <button
                                onClick={handleCompleteUnit}
                                disabled={sendingChat || messages.length < 2}
                                title="Kapitel abschließen"
                                className="flex items-center gap-1.5 px-4 py-2.5 bg-amber-600 hover:bg-amber-500 text-white text-sm font-semibold rounded-xl transition-colors disabled:opacity-40 disabled:cursor-not-allowed flex-shrink-0"
                            >
                                <FiCheck className="w-4 h-4" />
                                Abschließen
                            </button>
                        )}
                    </div>
                </div>

                <NoteToastHost toasts={toasts} accent="amber" onDismiss={dismissToast} />
            </div>
        );
    };

    // ── Render: Book completed ───────────────────────────────────────
    const renderBookCompleted = () => {
        if (view.kind !== 'book-completed') return null;
        const course = view.course;
        const completedCount = course.units.filter((u) => u.status === 'completed').length;
        const totalUnits = course.units.filter((u) => u.enabled).length;

        return (
            <div className="h-full flex items-center justify-center p-4">
                <div className="text-center max-w-md">
                    <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-green-900/30 mb-4">
                        <FiCheck className="w-8 h-8 text-green-400" />
                    </div>
                    <h3 className="text-lg font-semibold text-white mb-2">Buch abgeschlossen!</h3>
                    <p className="text-sm text-dark-400 mb-1">
                        <span className="text-amber-400 font-medium">{course.title}</span>
                    </p>
                    {course.book_authors && course.book_authors.length > 0 && (
                        <p className="text-xs text-dark-500 mb-1">{course.book_authors.join(', ')}</p>
                    )}
                    <p className="text-xs text-dark-500 mb-6">
                        {completedCount} von {totalUnits} Kapiteln abgeschlossen
                    </p>

                    <div className="flex gap-2 justify-center">
                        <button
                            onClick={() => {
                                const listItem: CourseListItem = {
                                    id: course.id,
                                    topic: course.topic,
                                    title: course.title,
                                    description: course.description,
                                    status: course.status,
                                    kind: course.kind,
                                    parent_course_id: course.parent_course_id,
                                    book_authors: course.book_authors,
                                    book_year: course.book_year,
                                    book_isbn: course.book_isbn,
                                    book_publisher: course.book_publisher,
                                    total_units: course.units.length,
                                    completed_units: completedCount,
                                    enabled_units: totalUnits,
                                    created_at: course.created_at,
                                    updated_at: course.updated_at,
                                };
                                handleOpenSummaries(listItem);
                            }}
                            className="px-6 py-2.5 bg-amber-600 hover:bg-amber-500 text-white text-sm font-medium rounded-xl transition-colors flex items-center gap-2"
                        >
                            <FiFileText className="w-4 h-4" />
                            Zusammenfassungen
                        </button>
                        <button
                            onClick={() => { setView({ kind: 'books' }); loadCourses(); }}
                            className="px-6 py-2.5 bg-dark-700 hover:bg-dark-600 text-dark-300 text-sm font-medium rounded-xl transition-colors"
                        >
                            Zur Übersicht
                        </button>
                    </div>
                </div>
            </div>
        );
    };

    // ── Render: Book Summaries ───────────────────────────────────────
    const renderBookSummaries = () => {
        if (view.kind !== 'book-summaries') return null;
        const { courseId, title, authors } = view;
        const completedOrActive = summaryChapters.filter(ch => ch.status === 'completed' || ch.status === 'active');
        const missingCount = completedOrActive.filter(ch => !ch.summary).length;

        return (
            <div className="h-full flex flex-col">
                <div className="px-4 py-3 border-b border-dark-800 bg-dark-900/50">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-3 min-w-0">
                            <button
                                onClick={() => { setView({ kind: 'books' }); loadCourses(); }}
                                className="p-1.5 hover:bg-dark-800 rounded-lg text-dark-500 hover:text-white transition-colors flex-shrink-0"
                            >
                                <FiArrowLeft className="w-4 h-4" />
                            </button>
                            <div className="min-w-0">
                                <h3 className="text-sm font-semibold text-white truncate">{title}</h3>
                                {authors.length > 0 && (
                                    <p className="text-[10px] text-dark-500 truncate">{authors.join(', ')}</p>
                                )}
                            </div>
                        </div>
                        {missingCount > 0 && (
                            <button
                                onClick={() => handleGenerateAllSummaries(courseId)}
                                disabled={generatingSummaryFor !== null}
                                className="flex items-center gap-1.5 px-3 py-1.5 bg-amber-600/20 text-amber-400 hover:bg-amber-600/30 text-xs font-medium rounded-lg transition-colors disabled:opacity-40"
                            >
                                <FiRefreshCw className={`w-3.5 h-3.5 ${generatingSummaryFor ? 'animate-spin' : ''}`} />
                                Alle generieren ({missingCount})
                            </button>
                        )}
                    </div>
                </div>

                <div className="flex-1 overflow-y-auto">
                    {loadingSummaries ? (
                        <div className="flex items-center justify-center py-12">
                            <div className="w-8 h-8 border-2 border-amber-500 border-t-transparent rounded-full animate-spin" />
                        </div>
                    ) : summaryChapters.length === 0 ? (
                        <div className="text-center py-12">
                            <p className="text-sm text-dark-500">Keine Kapitel gefunden.</p>
                        </div>
                    ) : (
                        <div className="divide-y divide-dark-800">
                            {summaryChapters.map((ch) => {
                                const isExpanded = expandedChapters[ch.id];
                                const isGenerating = generatingSummaryFor === ch.id;
                                const hasSummary = !!ch.summary;
                                const isCompleted = ch.status === 'completed';
                                const isActive = ch.status === 'active';
                                const canGenerate = isCompleted || isActive;

                                return (
                                    <div key={ch.id} className="group">
                                        <button
                                            onClick={() => hasSummary ? toggleSummaryChapter(ch.id) : canGenerate ? handleGenerateSummary(courseId, ch.id) : undefined}
                                            disabled={!hasSummary && !canGenerate}
                                            className={`w-full flex items-center gap-3 px-4 py-3 text-left transition-colors ${hasSummary ? 'hover:bg-dark-800/50 cursor-pointer' : canGenerate ? 'hover:bg-dark-800/50 cursor-pointer' : 'opacity-40 cursor-default'}`}
                                            style={{ paddingLeft: `${(ch.level - 1) * 16 + 16}px` }}
                                        >
                                            <div className="w-4 h-4 flex-shrink-0 flex items-center justify-center">
                                                {isGenerating ? (
                                                    <div className="w-3.5 h-3.5 border-2 border-amber-400 border-t-transparent rounded-full animate-spin" />
                                                ) : hasSummary ? (
                                                    isExpanded ? <FiChevronDown className="w-3.5 h-3.5 text-amber-400" /> : <FiChevronRight className="w-3.5 h-3.5 text-dark-500" />
                                                ) : canGenerate ? (
                                                    <FiRefreshCw className="w-3.5 h-3.5 text-dark-600 group-hover:text-amber-400 transition-colors" />
                                                ) : (
                                                    <div className="w-1.5 h-1.5 rounded-full bg-dark-700" />
                                                )}
                                            </div>
                                            <div className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${isCompleted ? 'bg-green-500' : isActive ? 'bg-amber-400' : 'bg-dark-700'}`} />
                                            <span className="text-dark-500 font-mono text-[10px] w-8 flex-shrink-0">{ch.unit_number}</span>
                                            <span className={`text-sm flex-1 min-w-0 truncate ${ch.level === 1 ? 'font-semibold text-white' : ch.level === 2 ? 'text-dark-300' : 'text-dark-500'}`}>
                                                {ch.title}
                                            </span>
                                            {hasSummary && (
                                                <span className="text-[9px] text-dark-600 flex-shrink-0">
                                                    {ch.summary_generated_at ? new Date(ch.summary_generated_at).toLocaleDateString('de-DE') : ''}
                                                </span>
                                            )}
                                            {!hasSummary && canGenerate && !isGenerating && (
                                                <span className="text-[9px] text-dark-600 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
                                                    Generieren
                                                </span>
                                            )}
                                        </button>

                                        {isExpanded && hasSummary && (
                                            <div className="bg-dark-800/30 border-t border-dark-800">
                                                <div className="px-6 py-5 max-w-3xl mx-auto">
                                                    <div className="markdown-content text-sm leading-relaxed">
                                                        <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins} components={markdownComponents}>
                                                            {ch.summary!}
                                                        </ReactMarkdown>
                                                    </div>
                                                    <div className="flex items-center gap-2 mt-4 pt-3 border-t border-dark-800">
                                                        <button
                                                            onClick={(e) => {
                                                                e.stopPropagation();
                                                                handleGenerateSummary(courseId, ch.id);
                                                            }}
                                                            disabled={isGenerating}
                                                            className="flex items-center gap-1.5 px-3 py-1.5 bg-dark-700 hover:bg-dark-600 text-dark-400 text-xs rounded-lg transition-colors disabled:opacity-40"
                                                        >
                                                            <FiRefreshCw className={`w-3 h-3 ${isGenerating ? 'animate-spin' : ''}`} />
                                                            Neu generieren
                                                        </button>
                                                    </div>
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                );
                            })}
                        </div>
                    )}
                </div>
            </div>
        );
    };

    // ── Main render ──────────────────────────────────────────────────
    return (
        <div className="h-full flex flex-col">
            <div className="flex items-center gap-2 px-3 sm:px-4 py-3 border-b border-dark-800 bg-dark-900/50">
                <FiBook className="w-4 h-4 text-amber-400 flex-shrink-0" />
                <h2 className="text-sm font-semibold text-white flex-shrink-0">Bücher</h2>
                <span className="text-xs text-dark-500 ml-2 hidden sm:inline">
                    Arbeite Bücher interaktiv durch — Kapitel für Kapitel mit KI-Tutor
                </span>
            </div>

            {error && view.kind !== 'books' && (
                <div className="px-4 py-2 bg-red-900/20 border-b border-red-800/30 flex items-center justify-between">
                    <p className="text-xs text-red-400">{error}</p>
                    <button onClick={() => setError(null)} className="text-red-400 hover:text-red-300">
                        <FiX className="w-3.5 h-3.5" />
                    </button>
                </div>
            )}

            <div className="flex-1 overflow-hidden">
                {view.kind === 'books' && renderBooksList()}
                {view.kind === 'confirm-book' && renderConfirmBook()}
                {view.kind === 'loading-toc' && renderLoadingToc()}
                {view.kind === 'confirm-toc' && renderConfirmToc()}
                {view.kind === 'lesson-chat' && renderLessonChat()}
                {view.kind === 'lesson-complete' && (
                    <LessonCompleteCelebration
                        unitTitle={view.unit.title}
                        recap={recap}
                        accent="amber"
                        isLastUnit={isLastEnabledUnit(view.course, view.unit)}
                        nextLabel="Nächstes Kapitel"
                        onContinue={handleAdvanceAfterCelebration}
                        loadingRecap={loadingRecap}
                    />
                )}
                {view.kind === 'book-completed' && renderBookCompleted()}
                {view.kind === 'book-summaries' && renderBookSummaries()}
            </div>
        </div>
    );
}
