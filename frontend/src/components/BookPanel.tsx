'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import {
    FiCheck, FiX, FiChevronRight, FiSearch, FiSquare, FiCheckSquare,
    FiSend, FiTrash2, FiArrowLeft, FiBook,
    FiChevronDown, FiChevronUp, FiBookOpen, FiRefreshCw, FiFileText,
} from 'react-icons/fi';
import { LuBrain } from 'react-icons/lu';
import ReactMarkdown from 'react-markdown';
import { markdownComponents, remarkPlugins, rehypePlugins } from '@/lib/markdownComponents';
import { useStore } from '@/lib/store';
import {
    searchBook, getBookToc,
    getBookCourses, getTeacherCourse, deleteTeacherCourse,
    createBookCourse, updateCourseStatus, updateCourseUnit,
    getUnitMessages, sendTeacherChat,
    generateLessonNotes, generateTermNote,
    ensureFolderPath, createNote,
    getBookSummaries, generateChapterSummary,
} from '@/lib/api';
import type {
    BookSearchResult, BookChapter,
    CourseListItem, CourseDetail, CourseUnit, CourseMessage,
    CourseNoteResult, BookSummaryChapter,
} from '@/lib/types';

type View =
    | { kind: 'books' }
    | { kind: 'confirm-book'; bookInfo: BookSearchResult }
    | { kind: 'loading-toc'; bookInfo: BookSearchResult }
    | { kind: 'confirm-toc'; bookInfo: BookSearchResult; chapters: BookChapter[] }
    | { kind: 'lesson-chat'; course: CourseDetail; unit: CourseUnit }
    | { kind: 'note-review'; course: CourseDetail; unit: CourseUnit; notes: CourseNoteResult[]; currentIdx: number }
    | { kind: 'book-completed'; course: CourseDetail }
    | { kind: 'book-summaries'; courseId: string; title: string; authors: string[] };

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

    // Chat
    const [messages, setMessages] = useState<CourseMessage[]>([]);
    const [chatInput, setChatInput] = useState('');
    const [sendingChat, setSendingChat] = useState(false);

    // Note generation
    const [generatingNotes, setGeneratingNotes] = useState(false);
    const [savingNote, setSavingNote] = useState(false);

    // Term note
    const [termInput, setTermInput] = useState('');
    const [generatingTerm, setGeneratingTerm] = useState(false);

    // Prefetched caches: unitId -> data
    const prefetchedNotesRef = useRef<Map<string, CourseNoteResult[]>>(new Map());
    const prefetchedMessagesRef = useRef<Map<string, CourseMessage[]>>(new Map());
    const userSentMessageRef = useRef(false);

    // Summaries
    const [summaryChapters, setSummaryChapters] = useState<BookSummaryChapter[]>([]);
    const [loadingSummaries, setLoadingSummaries] = useState(false);
    const [expandedChapters, setExpandedChapters] = useState<Record<string, boolean>>({});
    const [generatingSummaryFor, setGeneratingSummaryFor] = useState<string | null>(null);

    const chatEndRef = useRef<HTMLDivElement>(null);
    const lastAssistantRef = useRef<HTMLDivElement>(null);
    const chatInputRef = useRef<HTMLTextAreaElement>(null);
    const { loadFolderTree } = useStore();

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

    // Scroll to the start of the last assistant message so the user can read from the top
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

    // ── Confirm book → load TOC ──────────────────────────────────────
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

    // ── Start book course from TOC ───────────────────────────────────
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
                },
                selectedChapters,
            );

            const firstUnit = course.units.find((u) => u.enabled && u.status === 'pending');
            if (firstUnit) {
                await openUnitChat(course, firstUnit);
            }
        } catch {
            setError('Fehler beim Erstellen des Buchkurses.');
        }
    };

    // ── Resume book course ───────────────────────────────────────────
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
        userSentMessageRef.current = false;
        setView({ kind: 'lesson-chat', course, unit });

        // Use prefetched messages from memory if available (instant)
        const cached = prefetchedMessagesRef.current.get(unit.id);
        prefetchedMessagesRef.current.delete(unit.id);

        if (cached && cached.length > 0) {
            setMessages(cached);
            userSentMessageRef.current = cached.some(
                m => m.role === 'user' && m.content !== '[START]' && m.content !== '[NOTIZEN_ERSTELLT]'
            );
            prefetchNotesForUnit(course.id, unit.id);
            prefetchNextUnit(course, unit);
            return;
        }

        // No cache — fetch from server
        setMessages([]);
        try {
            const msgs = await getUnitMessages(course.id, unit.id);
            setMessages(msgs);
            if (msgs.length === 0) {
                setSendingChat(true);
                const response = await sendTeacherChat(course.id, unit.id, '[START]');
                setMessages([
                    { id: 'start', role: 'user', content: '[START]', metadata: null, created_at: null },
                    response,
                ]);
                setSendingChat(false);
            } else {
                userSentMessageRef.current = msgs.some(
                    m => m.role === 'user' && m.content !== '[START]' && m.content !== '[NOTIZEN_ERSTELLT]'
                );
            }
            prefetchNotesForUnit(course.id, unit.id);
            prefetchNextUnit(course, unit);
        } catch {
            setError('Fehler beim Laden des Chats.');
        } finally {
            setSendingChat(false);
        }
    };

    // ── Prefetch notes for a unit in background ─────────────────────
    const prefetchNotesForUnit = (courseId: string, unitId: string) => {
        if (prefetchedNotesRef.current.has(unitId)) return;
        generateLessonNotes(courseId, unitId).then(notes => {
            if (notes.length > 0) prefetchedNotesRef.current.set(unitId, notes);
        }).catch(() => {});
    };

    // ── Prefetch next unit greeting ──────────────────────────────────
    const prefetchNextUnit = (course: CourseDetail, currentUnit: CourseUnit) => {
        const sorted = [...course.units].sort((a, b) => a.order_index - b.order_index);
        const curIdx = sorted.findIndex(u => u.id === currentUnit.id);
        const nextUnit = sorted.slice(curIdx + 1).find(
            u => u.enabled && (u.status === 'pending' || u.status === 'active')
        );
        if (!nextUnit) return;
        if (prefetchedMessagesRef.current.has(nextUnit.id)) return; // already cached
        // Fire-and-forget: fetch or create greeting, cache in memory
        getUnitMessages(course.id, nextUnit.id).then(msgs => {
            if (msgs.length > 0) {
                prefetchedMessagesRef.current.set(nextUnit.id, msgs);
                prefetchNotesForUnit(course.id, nextUnit.id);
            } else {
                sendTeacherChat(course.id, nextUnit.id, '[START]').then(response => {
                    prefetchedMessagesRef.current.set(nextUnit.id, [
                        { id: 'start', role: 'user', content: '[START]', metadata: null, created_at: null },
                        response,
                    ]);
                    prefetchNotesForUnit(course.id, nextUnit.id);
                }).catch(() => {});
            }
        }).catch(() => {});
    };

    // ── Send chat message ────────────────────────────────────────────
    const handleSendMessage = async () => {
        if (!chatInput.trim() || sendingChat || view.kind !== 'lesson-chat') return;
        const msg = chatInput.trim();
        setChatInput('');
        setSendingChat(true);
        userSentMessageRef.current = true;  // invalidate prefetched notes

        const tempId = `temp-${Date.now()}`;
        setMessages((prev) => [
            ...prev,
            { id: tempId, role: 'user', content: msg, metadata: null, created_at: new Date().toISOString() },
        ]);

        try {
            const response = await sendTeacherChat(view.course.id, view.unit.id, msg);
            setMessages((prev) => [...prev.filter((m) => m.id !== tempId),
            { id: tempId, role: 'user', content: msg, metadata: null, created_at: new Date().toISOString() },
                response
            ]);
        } catch {
            setError('Fehler beim Senden der Nachricht.');
            setMessages((prev) => prev.filter((m) => m.id !== tempId));
        } finally {
            setSendingChat(false);
            chatInputRef.current?.focus();
        }
    };

    // ── "Verstanden" → generate notes ────────────────────────────────
    const handleUnderstood = async () => {
        if (view.kind !== 'lesson-chat' || generatingNotes) return;
        setGeneratingNotes(true);
        setError(null);
        try {
            // Use prefetched notes if user didn't add messages
            const unitId = view.unit.id;
            const cached = !userSentMessageRef.current ? prefetchedNotesRef.current.get(unitId) : undefined;
            const notes = cached || await generateLessonNotes(view.course.id, unitId);
            prefetchedNotesRef.current.delete(unitId);
            if (notes.length > 0) {
                setView({
                    kind: 'note-review',
                    course: view.course,
                    unit: view.unit,
                    notes,
                    currentIdx: 0,
                });
            } else {
                setError('Keine Notizen generiert. Versuche es nach mehr Konversation erneut.');
            }
        } catch {
            setError('Fehler beim Generieren der Notizen.');
        } finally {
            setGeneratingNotes(false);
        }
    };

    // ── Generate term note (from chat or inline [NOTIZ_ANFRAGE]) ─────
    const handleGenerateTermNote = async (topicOverride?: string) => {
        const term = topicOverride || termInput.trim();
        if (!term || generatingTerm || view.kind !== 'lesson-chat') return;
        if (!topicOverride) setTermInput('');
        setGeneratingTerm(true);
        setError(null);
        try {
            const note = await generateTermNote(view.course.id, view.unit.id, term);
            setView({
                kind: 'note-review',
                course: view.course,
                unit: view.unit,
                notes: [note],
                currentIdx: 0,
            });
        } catch {
            setError(`Fehler beim Generieren der Notiz für "${term}".`);
        } finally {
            setGeneratingTerm(false);
        }
    };

    // ── Accept/Skip note ─────────────────────────────────────────────
    const handleAcceptNote = async () => {
        if (view.kind !== 'note-review' || savingNote) return;
        setSavingNote(true);
        setError(null);
        const note = view.notes[view.currentIdx];
        try {
            const folder = await ensureFolderPath(note.folder);
            await createNote(note.title, note.content, folder.id, note.tag_ids);
            loadFolderTree();  // fire-and-forget — don't block UI
            advanceNoteReview();
        } catch {
            setError('Fehler beim Speichern der Notiz.');
        } finally {
            setSavingNote(false);
        }
    };

    const handleSkipNote = () => {
        if (view.kind !== 'note-review') return;
        advanceNoteReview();
    };

    const advanceNoteReview = () => {
        if (view.kind !== 'note-review') return;
        const nextIdx = view.currentIdx + 1;
        if (nextIdx < view.notes.length) {
            setView({ ...view, currentIdx: nextIdx });
        } else {
            returnToChat(view.course, view.unit);
        }
    };

    // ── Return to chat after note review ─────────────────────────────
    const returnToChat = async (course: CourseDetail, unit: CourseUnit) => {
        setMessages([]);
        setView({ kind: 'lesson-chat', course, unit });
        try {
            const msgs = await getUnitMessages(course.id, unit.id);
            setMessages(msgs);
        } catch {
            setError('Fehler beim Laden des Chats.');
        }
    };

    // ── Complete unit and advance ────────────────────────────────────
    const handleCompleteUnit = async () => {
        if (view.kind !== 'lesson-chat') return;
        setError(null);

        const currentCourse = view.course;
        const currentUnit = view.unit;

        // Find next unit locally — no need to refetch the whole course
        const sorted = [...currentCourse.units].sort((a, b) => a.order_index - b.order_index);
        const curIdx = sorted.findIndex(u => u.id === currentUnit.id);
        const nextUnit = sorted.slice(curIdx + 1).find(
            u => u.enabled && (u.status === 'pending' || u.status === 'active')
        );

        // Fire completion in background — don't block navigation
        updateCourseUnit(currentCourse.id, currentUnit.id, { status: 'completed' }).catch(() => {});

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

    // ── Skip unit ────────────────────────────────────────────────────
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

        // Fire skip in background
        updateCourseUnit(currentCourse.id, currentUnit.id, { status: 'skipped' }).catch(() => {});

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

    // ── Delete course ────────────────────────────────────────────────
    const handleDeleteCourse = async (courseId: string) => {
        try {
            await deleteTeacherCourse(courseId);
            await loadCourses();
        } catch {
            setError('Fehler beim Löschen.');
        }
    };

    // ── Open book summaries ──────────────────────────────────────────
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
            // Auto-expand first chapter that has a summary
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

    // ── Get current unit progress ────────────────────────────────────
    const getUnitProgress = (course: CourseDetail, currentUnit: CourseUnit) => {
        const enabled = course.units.filter((u) => u.enabled);
        const currentIndex = enabled.findIndex((u) => u.id === currentUnit.id);
        return { current: currentIndex + 1, total: enabled.length };
    };

    // ── Parse [NOTIZ_ANFRAGE: ...] markers from assistant messages ───
    const extractNoteRequests = (content: string): { cleanContent: string; requests: string[] } => {
        const regex = /\[NOTIZ_ANFRAGE:\s*(.+?)\]/g;
        const requests: string[] = [];
        let match;
        while ((match = regex.exec(content)) !== null) {
            requests.push(match[1].trim());
        }
        const cleanContent = content.replace(/\s*\[NOTIZ_ANFRAGE:\s*.+?\]/g, '').trim();
        return { cleanContent, requests };
    };

    // ── Render: Books list ───────────────────────────────────────────
    const renderBooksList = () => {
        const activeDraft = courses.filter(c => c.status !== 'completed');
        const completed = courses.filter(c => c.status === 'completed');

        return (
            <div className="h-full flex flex-col">
                {/* Search bar */}
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

                {/* Courses grid */}
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
                                Gib den Titel eines Buches ein. Die KI sucht nach dem Buch,
                                zeigt dir das Inhaltsverzeichnis und erklärt dir jedes Kapitel
                                interaktiv — wie ein persönlicher Tutor.
                            </p>
                        </div>
                    ) : (
                        <div className="max-w-2xl mx-auto space-y-6">
                            {/* Active books */}
                            {activeDraft.length > 0 && (
                                <div className="space-y-3">
                                    {activeDraft.map((course) => (
                                        <div
                                            key={course.id}
                                            className="bg-dark-800 border border-dark-700 rounded-xl p-4 hover:border-dark-600 transition-colors group"
                                        >
                                            <div className="flex items-start justify-between gap-3">
                                                <div className="flex-1 min-w-0">
                                                    <div className="flex items-center gap-2 mb-1">
                                                        <span className="px-2 py-0.5 text-[10px] font-medium rounded-full bg-amber-600/20 text-amber-400">
                                                            In Bearbeitung
                                                        </span>
                                                    </div>
                                                    <h4 className="text-sm font-semibold text-white truncate">{course.title}</h4>
                                                    {course.book_authors && course.book_authors.length > 0 && (
                                                        <p className="text-xs text-dark-500 mt-0.5">{course.book_authors.join(', ')}</p>
                                                    )}
                                                    {course.total_units > 0 && (
                                                        <div className="flex items-center gap-2 mt-2">
                                                            <div className="flex-1 h-1.5 bg-dark-700 rounded-full overflow-hidden">
                                                                <div
                                                                    className="h-full bg-amber-500 rounded-full transition-all"
                                                                    style={{ width: `${Math.round((course.completed_units / course.enabled_units) * 100)}%` }}
                                                                />
                                                            </div>
                                                            <span className="text-[10px] text-dark-500">
                                                                {course.completed_units}/{course.enabled_units}
                                                            </span>
                                                        </div>
                                                    )}
                                                </div>
                                                <div className="flex items-center gap-1.5">
                                                    <button
                                                        onClick={() => handleOpenSummaries(course)}
                                                        className="px-3 py-1.5 bg-dark-700 hover:bg-dark-600 text-dark-300 text-xs font-medium rounded-lg transition-colors"
                                                        title="Kapitel-Zusammenfassungen"
                                                    >
                                                        <FiFileText className="w-3.5 h-3.5" />
                                                    </button>
                                                    <button
                                                        onClick={() => handleResumeCourse(course.id)}
                                                        className="px-3 py-1.5 bg-amber-600 hover:bg-amber-500 text-white text-xs font-medium rounded-lg transition-colors"
                                                    >
                                                        Fortsetzen
                                                    </button>
                                                    <button
                                                        onClick={() => handleDeleteCourse(course.id)}
                                                        className="p-1.5 text-dark-600 hover:text-red-400 transition-colors opacity-0 group-hover:opacity-100"
                                                    >
                                                        <FiTrash2 className="w-3.5 h-3.5" />
                                                    </button>
                                                </div>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}

                            {/* Completed books */}
                            {completed.length > 0 && (
                                <div>
                                    {activeDraft.length > 0 && (
                                        <div className="flex items-center gap-3 mb-3">
                                            <div className="h-px flex-1 bg-dark-700" />
                                            <span className="text-[10px] text-dark-500 font-medium uppercase tracking-wider">Abgeschlossen</span>
                                            <div className="h-px flex-1 bg-dark-700" />
                                        </div>
                                    )}
                                    <div className="space-y-2">
                                        {completed.map((course) => (
                                            <div
                                                key={course.id}
                                                className="bg-dark-800/50 border border-dark-700/50 rounded-xl p-3 group"
                                            >
                                                <div className="flex items-center justify-between gap-3">
                                                    <div className="flex items-center gap-3 min-w-0">
                                                        <FiCheck className="w-4 h-4 text-green-500 flex-shrink-0" />
                                                        <div className="min-w-0">
                                                            <h4 className="text-sm font-medium text-dark-300 truncate">{course.title}</h4>
                                                            <p className="text-[10px] text-dark-600">
                                                                {course.completed_units}/{course.enabled_units} Kapitel
                                                                {course.book_authors && course.book_authors.length > 0 && ` · ${course.book_authors.join(', ')}`}
                                                            </p>
                                                        </div>
                                                    </div>
                                                    <div className="flex items-center gap-1.5">
                                                        <button
                                                            onClick={() => handleOpenSummaries(course)}
                                                            className="px-3 py-1.5 bg-dark-700 hover:bg-dark-600 text-dark-300 text-xs font-medium rounded-lg transition-colors"
                                                        >
                                                            <FiFileText className="w-3.5 h-3.5" />
                                                        </button>
                                                        <button
                                                            onClick={() => handleDeleteCourse(course.id)}
                                                            className="p-1.5 text-dark-600 hover:text-red-400 transition-colors opacity-0 group-hover:opacity-100"
                                                        >
                                                            <FiTrash2 className="w-3.5 h-3.5" />
                                                        </button>
                                                    </div>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                </div>
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

                        {error && (
                            <p className="mt-3 text-sm text-red-400">{error}</p>
                        )}
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
                                        className={`w-full flex items-center gap-2 py-2 text-sm rounded-lg px-2 transition-colors hover:bg-dark-700/50 ${!enabled ? 'opacity-40' : ''
                                            }`}
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
                                        <span className={`text-left ${ch.level === 1 ? 'text-white font-semibold' :
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

        return (
            <div className="h-full flex flex-col">
                {/* Unit header */}
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
                                <div className="flex items-center gap-2">
                                    <span className="text-[10px] text-amber-400 font-medium">
                                        {progress.current}/{progress.total}
                                    </span>
                                    <span className="text-dark-500 font-mono text-[10px]">{unit.unit_number}</span>
                                    <h3 className="text-sm font-semibold text-white truncate">{unit.title}</h3>
                                </div>
                                <p className="text-[10px] text-dark-500 truncate">{course.title}{course.book_authors && course.book_authors.length > 0 ? ` · ${course.book_authors.join(', ')}` : ''}</p>
                            </div>
                        </div>
                        <div className="flex items-center gap-1.5 flex-shrink-0">
                            <button
                                onClick={handleSkipUnit}
                                className="px-2.5 py-1.5 text-[10px] bg-dark-700 hover:bg-dark-600 text-dark-400 rounded-lg transition-colors"
                            >
                                Überspringen
                            </button>
                        </div>
                    </div>
                    {/* Progress bar */}
                    <div className="mt-2 h-1 bg-dark-800 rounded-full overflow-hidden">
                        <div
                            className="h-full bg-amber-500 rounded-full transition-all"
                            style={{ width: `${Math.round((progress.current / progress.total) * 100)}%` }}
                        />
                    </div>
                </div>

                {/* Messages */}
                <div className="flex-1 overflow-y-auto p-4 space-y-4">
                    {messages.filter(m => m.role !== 'user' || (m.content !== '[START]' && m.content !== '[NOTIZEN_ERSTELLT]')).map((msg, idx, arr) => {
                        const isLastAssistant = msg.role === 'assistant' && idx === arr.length - 1;
                        return (
                        <div
                            key={msg.id}
                            ref={isLastAssistant ? lastAssistantRef : undefined}
                            className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                        >
                            {msg.role === 'note_generated' ? (
                                <div className="flex items-center gap-2 px-3 py-2 bg-green-900/20 border border-green-800/30 rounded-lg text-xs text-green-400">
                                    <FiCheck className="w-3.5 h-3.5" />
                                    {msg.content}
                                </div>
                            ) : (
                                <div
                                    className={`max-w-[85%] sm:max-w-[75%] px-4 py-3 rounded-2xl text-sm ${msg.role === 'user'
                                            ? 'bg-amber-600 text-white rounded-br-md'
                                            : 'bg-dark-800 border border-dark-700 text-dark-200 rounded-bl-md'
                                        }`}
                                >
                                    {msg.role === 'assistant' ? (
                                        (() => {
                                            const { cleanContent, requests } = extractNoteRequests(msg.content);
                                            return (
                                                <>
                                                    <div className="markdown-content text-sm leading-relaxed">
                                                        <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins} components={markdownComponents}>
                                                            {cleanContent}
                                                        </ReactMarkdown>
                                                    </div>
                                                    {requests.length > 0 && (
                                                        <div className="mt-3 flex flex-wrap gap-1.5">
                                                            {requests.map((topic, i) => (
                                                                <button
                                                                    key={i}
                                                                    onClick={() => handleGenerateTermNote(topic)}
                                                                    disabled={generatingTerm}
                                                                    className="flex items-center gap-1.5 px-3 py-1.5 bg-amber-600/20 text-amber-300 hover:bg-amber-600/30 text-xs font-medium rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                                                                >
                                                                    <FiBookOpen className="w-3.5 h-3.5" />
                                                                    Notiz erstellen: {topic}
                                                                </button>
                                                            ))}
                                                        </div>
                                                    )}
                                                </>
                                            );
                                        })()
                                    ) : (
                                        <p className="whitespace-pre-wrap">{msg.content}</p>
                                    )}
                                </div>
                            )}
                        </div>
                    );
                    })}

                    {sendingChat && (
                        <div className="flex justify-start">
                            <div className="bg-dark-800 border border-dark-700 rounded-2xl rounded-bl-md px-4 py-3">
                                <div className="flex items-center gap-2 text-dark-400">
                                    <div className="w-2 h-2 bg-amber-400 rounded-full animate-pulse" />
                                    <div className="w-2 h-2 bg-amber-400 rounded-full animate-pulse" style={{ animationDelay: '0.2s' }} />
                                    <div className="w-2 h-2 bg-amber-400 rounded-full animate-pulse" style={{ animationDelay: '0.4s' }} />
                                </div>
                            </div>
                        </div>
                    )}

                    <div ref={chatEndRef} />
                </div>

                {/* Term note input (collapsible) */}
                <TermNoteBar
                    termInput={termInput}
                    setTermInput={setTermInput}
                    onGenerate={handleGenerateTermNote}
                    generating={generatingTerm}
                />

                {/* Chat input */}
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
                            style={{ height: 'auto' }}
                        />
                        <button
                            onClick={handleSendMessage}
                            disabled={!chatInput.trim() || sendingChat}
                            className="p-2.5 bg-amber-600 hover:bg-amber-500 text-white rounded-xl transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex-shrink-0"
                        >
                            <FiSend className="w-4 h-4" />
                        </button>
                    </div>
                    {/* Action buttons */}
                    <div className="flex gap-2 mt-2">
                        <button
                            onClick={handleUnderstood}
                            disabled={generatingNotes || sendingChat || messages.length < 2}
                            className="flex items-center gap-1.5 px-3 py-1.5 bg-green-600/20 text-green-400 hover:bg-green-600/30 text-xs font-medium rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                        >
                            {generatingNotes ? (
                                <div className="w-3 h-3 border-2 border-green-400 border-t-transparent rounded-full animate-spin" />
                            ) : (
                                <FiCheck className="w-3.5 h-3.5" />
                            )}
                            Verstanden — Notizen generieren
                        </button>
                        <button
                            onClick={handleCompleteUnit}
                            disabled={sendingChat || messages.length < 2}
                            className="flex items-center gap-1.5 px-3 py-1.5 bg-amber-600/20 text-amber-400 hover:bg-amber-600/30 text-xs font-medium rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                        >
                            <FiChevronRight className="w-3.5 h-3.5" />
                            Nächstes Kapitel
                        </button>
                    </div>
                </div>
            </div>
        );
    };

    // ── Render: Note Review ──────────────────────────────────────────
    const renderNoteReview = () => {
        if (view.kind !== 'note-review') return null;
        const note = view.notes[view.currentIdx];
        const isLast = view.currentIdx === view.notes.length - 1;

        return (
            <div className="h-full flex flex-col">
                {/* Header */}
                <div className="px-4 py-3 border-b border-dark-800 bg-dark-900/50 flex items-center justify-between">
                    <div>
                        <p className="text-xs text-dark-500">
                            Notiz {view.currentIdx + 1} von {view.notes.length}
                        </p>
                        <h3 className="text-sm font-semibold text-white">{note.title}</h3>
                    </div>
                    <div className="flex items-center gap-2">
                        {note.tag_names.length > 0 && (
                            <div className="flex gap-1 flex-wrap">
                                {note.tag_names.map((tag, i) => (
                                    <span key={i} className="px-2 py-0.5 text-[10px] bg-dark-700 text-dark-400 rounded-full">
                                        {tag}
                                    </span>
                                ))}
                            </div>
                        )}
                    </div>
                </div>

                {/* Folder */}
                <div className="px-4 py-1.5 border-b border-dark-800 bg-dark-900/30">
                    <p className="text-[10px] text-dark-500">
                        Ordner: <span className="text-amber-400">{note.folder}</span>
                    </p>
                </div>

                {/* Content */}
                <div className="flex-1 overflow-y-auto px-6 py-5">
                    <div className="markdown-content text-sm">
                        <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins} components={markdownComponents}>
                            {note.content}
                        </ReactMarkdown>
                    </div>
                </div>

                {/* Actions */}
                <div className="px-4 py-3 border-t border-dark-800 flex gap-2">
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
                        {isLast ? 'Überspringen & zurück' : 'Überspringen'}
                    </button>
                </div>
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
                        <p className="text-xs text-dark-500 mb-1">
                            {course.book_authors.join(', ')}
                        </p>
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
                {/* Header */}
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

                {/* Content */}
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
                                        {/* Chapter row */}
                                        <button
                                            onClick={() => hasSummary ? toggleSummaryChapter(ch.id) : canGenerate ? handleGenerateSummary(courseId, ch.id) : undefined}
                                            disabled={!hasSummary && !canGenerate}
                                            className={`w-full flex items-center gap-3 px-4 py-3 text-left transition-colors ${
                                                hasSummary ? 'hover:bg-dark-800/50 cursor-pointer' :
                                                canGenerate ? 'hover:bg-dark-800/50 cursor-pointer' :
                                                'opacity-40 cursor-default'
                                            }`}
                                            style={{ paddingLeft: `${(ch.level - 1) * 16 + 16}px` }}
                                        >
                                            {/* Expand/collapse indicator */}
                                            <div className="w-4 h-4 flex-shrink-0 flex items-center justify-center">
                                                {isGenerating ? (
                                                    <div className="w-3.5 h-3.5 border-2 border-amber-400 border-t-transparent rounded-full animate-spin" />
                                                ) : hasSummary ? (
                                                    isExpanded ?
                                                        <FiChevronDown className="w-3.5 h-3.5 text-amber-400" /> :
                                                        <FiChevronRight className="w-3.5 h-3.5 text-dark-500" />
                                                ) : canGenerate ? (
                                                    <FiRefreshCw className="w-3.5 h-3.5 text-dark-600 group-hover:text-amber-400 transition-colors" />
                                                ) : (
                                                    <div className="w-1.5 h-1.5 rounded-full bg-dark-700" />
                                                )}
                                            </div>

                                            {/* Status indicator */}
                                            <div className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                                                isCompleted ? 'bg-green-500' :
                                                isActive ? 'bg-amber-400' :
                                                'bg-dark-700'
                                            }`} />

                                            {/* Chapter info */}
                                            <span className="text-dark-500 font-mono text-[10px] w-8 flex-shrink-0">{ch.unit_number}</span>
                                            <span className={`text-sm flex-1 min-w-0 truncate ${
                                                ch.level === 1 ? 'font-semibold text-white' :
                                                ch.level === 2 ? 'text-dark-300' : 'text-dark-500'
                                            }`}>
                                                {ch.title}
                                            </span>

                                            {/* Summary badge */}
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

                                        {/* Expanded summary content */}
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
            {/* Header */}
            <div className="flex items-center gap-2 px-3 sm:px-4 py-3 border-b border-dark-800 bg-dark-900/50">
                <FiBook className="w-4 h-4 text-amber-400 flex-shrink-0" />
                <h2 className="text-sm font-semibold text-white flex-shrink-0">Bücher</h2>
                <span className="text-xs text-dark-500 ml-2 hidden sm:inline">
                    Arbeite Bücher interaktiv durch — Kapitel für Kapitel mit KI-Tutor
                </span>
            </div>

            {/* Error bar */}
            {error && view.kind !== 'books' && (
                <div className="px-4 py-2 bg-red-900/20 border-b border-red-800/30 flex items-center justify-between">
                    <p className="text-xs text-red-400">{error}</p>
                    <button onClick={() => setError(null)} className="text-red-400 hover:text-red-300">
                        <FiX className="w-3.5 h-3.5" />
                    </button>
                </div>
            )}

            {/* Content */}
            <div className="flex-1 overflow-hidden">
                {view.kind === 'books' && renderBooksList()}
                {view.kind === 'confirm-book' && renderConfirmBook()}
                {view.kind === 'loading-toc' && renderLoadingToc()}
                {view.kind === 'confirm-toc' && renderConfirmToc()}
                {view.kind === 'lesson-chat' && renderLessonChat()}
                {view.kind === 'note-review' && renderNoteReview()}
                {view.kind === 'book-completed' && renderBookCompleted()}
                {view.kind === 'book-summaries' && renderBookSummaries()}
            </div>
        </div>
    );
}

// ── Term Note Bar (collapsible) ──────────────────────────────────────
function TermNoteBar({
    termInput,
    setTermInput,
    onGenerate,
    generating,
}: {
    termInput: string;
    setTermInput: (v: string) => void;
    onGenerate: () => void;
    generating: boolean;
}) {
    const [expanded, setExpanded] = useState(false);

    return (
        <div className="border-t border-dark-800">
            <button
                onClick={() => setExpanded(!expanded)}
                className="w-full flex items-center justify-between px-3 py-1.5 text-[10px] text-dark-500 hover:text-dark-300 transition-colors"
            >
                <span className="flex items-center gap-1">
                    <FiBookOpen className="w-3 h-3" />
                    Einzelne Notiz zu einem Begriff
                </span>
                {expanded ? <FiChevronDown className="w-3 h-3" /> : <FiChevronUp className="w-3 h-3" />}
            </button>
            {expanded && (
                <div className="px-3 pb-2">
                    <div className="flex gap-1.5">
                        <input
                            type="text"
                            value={termInput}
                            onChange={(e) => setTermInput(e.target.value)}
                            onKeyDown={(e) => e.key === 'Enter' && onGenerate()}
                            placeholder="z.B. Habit Loop, Growth Mindset..."
                            className="flex-1 px-2.5 py-1.5 bg-dark-800 border border-dark-700 rounded-lg text-white text-xs placeholder-dark-600 focus:outline-none focus:border-amber-500 min-w-0"
                        />
                        <button
                            onClick={onGenerate}
                            disabled={!termInput.trim() || generating}
                            className="px-2.5 py-1.5 bg-amber-600 hover:bg-amber-500 text-white text-xs rounded-lg transition-colors disabled:opacity-50 flex items-center gap-1"
                        >
                            {generating ? (
                                <div className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />
                            ) : (
                                <FiBookOpen className="w-3 h-3" />
                            )}
                            Notiz
                        </button>
                    </div>
                </div>
            )}
        </div>
    );
}
