'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import {
    FiCheck, FiX, FiChevronRight, FiLoader, FiSquare, FiCheckSquare,
    FiSend, FiZap, FiTrash2, FiArrowLeft, FiPlus, FiBookOpen,
    FiChevronDown, FiChevronUp,
} from 'react-icons/fi';
import { LuBrain, LuGraduationCap, LuSparkles } from 'react-icons/lu';
import ReactMarkdown from 'react-markdown';
import { markdownComponents, remarkPlugins, rehypePlugins } from '@/lib/markdownComponents';
import { useStore } from '@/lib/store';
import {
    getTeacherCourses, getTeacherCourse, deleteTeacherCourse,
    generateCurriculum, updateCourseStatus, updateCourseUnit,
    getUnitMessages, sendTeacherChat,
    generateLessonNotes, generateTermNote,
    generateAdvancedFocus,
    ensureFolderPath, createNote,
} from '@/lib/api';
import type {
    CourseListItem, CourseDetail, CourseUnit, CourseMessage,
    CourseNoteResult, AdvancedFocusSuggestion,
} from '@/lib/types';

type View =
    | { kind: 'courses' }
    | { kind: 'generating-curriculum'; topic: string }
    | { kind: 'confirm-curriculum'; course: CourseDetail }
    | { kind: 'lesson-chat'; course: CourseDetail; unit: CourseUnit }
    | { kind: 'note-review'; course: CourseDetail; unit: CourseUnit; notes: CourseNoteResult[]; currentIdx: number }
    | { kind: 'course-completed'; course: CourseDetail }
    | { kind: 'advanced-focus'; course: CourseDetail; suggestions: AdvancedFocusSuggestion[] };

export default function TeacherPanel() {
    // ── State ────────────────────────────────────────────────────────
    const [view, setView] = useState<View>({ kind: 'courses' });
    const [courses, setCourses] = useState<CourseListItem[]>([]);
    const [loadingCourses, setLoadingCourses] = useState(true);
    const [error, setError] = useState<string | null>(null);

    // Curriculum generation
    const [topicInput, setTopicInput] = useState('');

    // curriculum confirmation
    const [enabledUnits, setEnabledUnits] = useState<Record<string, boolean>>({});

    // Chat
    const [messages, setMessages] = useState<CourseMessage[]>([]);
    const [chatInput, setChatInput] = useState('');
    const [sendingChat, setSendingChat] = useState(false);
    const [loadingMessages, setLoadingMessages] = useState(false);

    // Note generation
    const [generatingNotes, setGeneratingNotes] = useState(false);
    const [savingNote, setSavingNote] = useState(false);

    // Term note
    const [termInput, setTermInput] = useState('');
    const [generatingTerm, setGeneratingTerm] = useState(false);

    // Advanced focus
    const [loadingFocus, setLoadingFocus] = useState(false);
    const [customFocusInput, setCustomFocusInput] = useState('');

    const chatEndRef = useRef<HTMLDivElement>(null);
    const lastAssistantRef = useRef<HTMLDivElement>(null);
    const chatInputRef = useRef<HTMLTextAreaElement>(null);
    const { loadFolderTree } = useStore();

    // ── Load courses ─────────────────────────────────────────────────
    const loadCourses = useCallback(async () => {
        setLoadingCourses(true);
        try {
            const data = await getTeacherCourses();
            setCourses(data);
        } catch {
            setError('Fehler beim Laden der Kurse');
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

    // ── Curriculum generation ────────────────────────────────────────
    const handleGenerateCurriculum = async (topic: string, parentCourseId?: string, customFocus?: string) => {
        if (!topic.trim()) return;
        setError(null);
        setView({ kind: 'generating-curriculum', topic: topic.trim() });
        try {
            const course = await generateCurriculum(topic.trim(), parentCourseId, customFocus);
            const defaults: Record<string, boolean> = {};
            course.units.forEach((u) => { defaults[u.id] = true; });
            setEnabledUnits(defaults);
            setView({ kind: 'confirm-curriculum', course });
        } catch {
            setError('Fehler beim Generieren des Lehrplans. Bitte versuche es erneut.');
            setView({ kind: 'courses' });
        }
    };

    // ── Start course (activate) ──────────────────────────────────────
    const handleStartCourse = async (course: CourseDetail) => {
        setError(null);
        try {
            // Disable unchecked units
            for (const unit of course.units) {
                if (enabledUnits[unit.id] === false) {
                    await updateCourseUnit(course.id, unit.id, { enabled: false });
                }
            }
            await updateCourseStatus(course.id, 'active');
            // Reload course
            const updated = await getTeacherCourse(course.id);
            // Open first enabled pending unit
            const firstUnit = updated.units.find((u) => u.enabled && u.status === 'pending');
            if (firstUnit) {
                await openUnitChat(updated, firstUnit);
            }
        } catch {
            setError('Fehler beim Starten des Kurses.');
        }
    };

    // ── Resume course ────────────────────────────────────────────────
    const handleResumeCourse = async (courseId: string) => {
        setError(null);
        try {
            const course = await getTeacherCourse(courseId);
            // Find current unit: first enabled non-completed
            const currentUnit = course.units.find(
                (u) => u.enabled && (u.status === 'active' || u.status === 'pending')
            );
            if (currentUnit) {
                await openUnitChat(course, currentUnit);
            } else {
                // All units completed
                setView({ kind: 'course-completed', course });
            }
        } catch {
            setError('Fehler beim Laden des Kurses.');
        }
    };

    // ── Open unit chat ───────────────────────────────────────────────
    const openUnitChat = async (course: CourseDetail, unit: CourseUnit) => {
        setLoadingMessages(true);
        setMessages([]);
        setView({ kind: 'lesson-chat', course, unit });
        try {
            const msgs = await getUnitMessages(course.id, unit.id);
            setMessages(msgs);
            setLoadingMessages(false);
            // If no messages yet, send initial greeting
            if (msgs.length === 0) {
                setSendingChat(true);
                const response = await sendTeacherChat(
                    course.id,
                    unit.id,
                    '[START]' // Signal to teacher to introduce the topic
                );
                setMessages([
                    { id: 'start', role: 'user', content: '[START]', metadata: null, created_at: null },
                    response,
                ]);
                setSendingChat(false);
            }
            // Prefetch next lesson greeting in background
            prefetchNextUnit(course, unit);
        } catch {
            setError('Fehler beim Laden des Chats.');
        } finally {
            setLoadingMessages(false);
            setSendingChat(false);
        }
    };

    // ── Prefetch next unit greeting ──────────────────────────────────
    const prefetchNextUnit = (course: CourseDetail, currentUnit: CourseUnit) => {
        const sorted = [...course.units].sort((a, b) => a.order_index - b.order_index);
        const curIdx = sorted.findIndex(u => u.id === currentUnit.id);
        const nextUnit = sorted.slice(curIdx + 1).find(
            u => u.enabled && (u.status === 'pending' || u.status === 'active')
        );
        if (!nextUnit) return;
        // Fire-and-forget: check if already has messages, if not send [START]
        getUnitMessages(course.id, nextUnit.id).then(msgs => {
            if (msgs.length === 0) {
                sendTeacherChat(course.id, nextUnit.id, '[START]').catch(() => {});
            }
        }).catch(() => {});
    };

    // ── Send chat message ────────────────────────────────────────────
    const handleSendMessage = async () => {
        if (!chatInput.trim() || sendingChat || view.kind !== 'lesson-chat') return;
        const msg = chatInput.trim();
        setChatInput('');
        setSendingChat(true);

        // Optimistic add user message
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
            // Remove optimistic message
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
            const notes = await generateLessonNotes(view.course.id, view.unit.id);
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
            // Show as single-note review
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
            // All notes reviewed — go back to chat or advance unit
            returnToChat(view.course, view.unit);
        }
    };

    // ── Return to chat after note review ─────────────────────────────
    const returnToChat = async (course: CourseDetail, unit: CourseUnit) => {
        setLoadingMessages(true);
        setMessages([]);
        setView({ kind: 'lesson-chat', course, unit });
        try {
            const msgs = await getUnitMessages(course.id, unit.id);
            setMessages(msgs);
            setLoadingMessages(false);
            // Automatically send follow-up so teacher asks about more questions
            setSendingChat(true);
            await sendTeacherChat(course.id, unit.id, '[NOTIZEN_ERSTELLT]');
            const refreshed = await getUnitMessages(course.id, unit.id);
            setMessages(refreshed);
        } catch {
            setError('Fehler beim Laden des Chats.');
        } finally {
            setSendingChat(false);
            setLoadingMessages(false);
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
                setView({ kind: 'course-completed', course: final });
            } catch {
                setError('Fehler beim Abschließen des Kurses.');
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
                setView({ kind: 'course-completed', course: final });
            } catch {
                setError('Fehler beim Überspringen.');
            }
        }
    };

    // ── Advanced focus ───────────────────────────────────────────────
    const handleLoadFocus = async (course: CourseDetail) => {
        setLoadingFocus(true);
        setError(null);
        try {
            const suggestions = await generateAdvancedFocus(course.id);
            setView({ kind: 'advanced-focus', course, suggestions });
        } catch {
            setError('Fehler beim Generieren der Vorschläge.');
        } finally {
            setLoadingFocus(false);
        }
    };

    // ── Delete course ────────────────────────────────────────────────
    const handleDeleteCourse = async (courseId: string) => {
        try {
            await deleteTeacherCourse(courseId);
            await loadCourses();
        } catch {
            setError('Fehler beim Löschen des Kurses.');
        }
    };

    // ── Curriculum checkbox helpers ──────────────────────────────────
    const toggleUnit = (unitId: string) => {
        setEnabledUnits((prev) => ({ ...prev, [unitId]: !prev[unitId] }));
    };

    const selectAllUnits = (course: CourseDetail) => {
        const next: Record<string, boolean> = {};
        course.units.forEach((u) => { next[u.id] = true; });
        setEnabledUnits(next);
    };

    const deselectAllUnits = (course: CourseDetail) => {
        const next: Record<string, boolean> = {};
        course.units.forEach((u) => { next[u.id] = false; });
        setEnabledUnits(next);
    };

    const enabledCount = (course: CourseDetail) =>
        course.units.filter((u) => enabledUnits[u.id] !== false).length;

    // ── Get current unit progress info ───────────────────────────────
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

    // ── Render: Courses list ─────────────────────────────────────────
    const renderCoursesList = () => (
        <div className="h-full flex flex-col">
            {/* New course input */}
            <div className="p-4 border-b border-dark-800">
                <div className="max-w-lg mx-auto">
                    <div className="flex gap-2">
                        <input
                            type="text"
                            value={topicInput}
                            onChange={(e) => setTopicInput(e.target.value)}
                            onKeyDown={(e) => e.key === 'Enter' && handleGenerateCurriculum(topicInput)}
                            placeholder='Thema eingeben, z.B. "Lineare Algebra" oder "Organische Chemie"'
                            className="flex-1 px-4 py-3 bg-dark-800 border border-dark-700 rounded-xl text-white text-sm placeholder-dark-600 focus:outline-none focus:border-teal-500"
                            autoFocus
                        />
                        <button
                            onClick={() => handleGenerateCurriculum(topicInput)}
                            disabled={!topicInput.trim()}
                            className="px-4 py-3 bg-teal-600 hover:bg-teal-500 text-white rounded-xl transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            <LuGraduationCap className="w-5 h-5" />
                        </button>
                    </div>
                </div>
            </div>

            {/* Courses grid */}
            <div className="flex-1 overflow-y-auto p-4">
                {loadingCourses ? (
                    <div className="flex items-center justify-center py-12">
                        <div className="w-8 h-8 border-2 border-teal-500 border-t-transparent rounded-full animate-spin" />
                    </div>
                ) : courses.length === 0 ? (
                    <div className="text-center py-12">
                        <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-teal-900/30 mb-4">
                            <LuGraduationCap className="w-8 h-8 text-teal-400" />
                        </div>
                        <h3 className="text-lg font-semibold text-white mb-2">Infinite Teacher</h3>
                        <p className="text-sm text-dark-500 max-w-md mx-auto">
                            Gib ein Thema ein und die KI erstellt einen personalisierten Lehrplan.
                            Lerne in interaktiven Lektionen mit einem KI-Lehrer und generiere
                            automatisch Notizen.
                        </p>
                    </div>
                ) : (
                    <div className="max-w-2xl mx-auto space-y-6">
                        {/* Active & Draft courses */}
                        {(() => {
                            const activeDraft = courses.filter(c => c.status !== 'completed');
                            const completed = courses.filter(c => c.status === 'completed');

                            return (
                                <>
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
                                                                <span className={`px-2 py-0.5 text-[10px] font-medium rounded-full ${course.status === 'active'
                                                                        ? 'bg-teal-600/20 text-teal-400'
                                                                        : 'bg-dark-700 text-dark-400'
                                                                    }`}>
                                                                    {course.status === 'active' ? 'Aktiv' : 'Entwurf'}
                                                                </span>
                                                                {course.parent_course_id && (
                                                                    <span className="px-2 py-0.5 text-[10px] font-medium rounded-full bg-purple-600/20 text-purple-400">
                                                                        Vertiefung
                                                                    </span>
                                                                )}
                                                            </div>
                                                            <h4 className="text-sm font-semibold text-white truncate">{course.title}</h4>
                                                            <p className="text-xs text-dark-500 mt-0.5 line-clamp-2">{course.description}</p>
                                                            {course.total_units > 0 && (
                                                                <div className="flex items-center gap-2 mt-2">
                                                                    <div className="flex-1 h-1.5 bg-dark-700 rounded-full overflow-hidden">
                                                                        <div
                                                                            className="h-full bg-teal-500 rounded-full transition-all"
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
                                                            {course.status === 'active' && (
                                                                <button
                                                                    onClick={() => handleResumeCourse(course.id)}
                                                                    className="px-3 py-1.5 bg-teal-600 hover:bg-teal-500 text-white text-xs font-medium rounded-lg transition-colors"
                                                                >
                                                                    Fortsetzen
                                                                </button>
                                                            )}
                                                            {course.status === 'draft' && (
                                                                <button
                                                                    onClick={() => handleResumeCourse(course.id)}
                                                                    className="px-3 py-1.5 bg-dark-700 hover:bg-dark-600 text-white text-xs font-medium rounded-lg transition-colors"
                                                                >
                                                                    Öffnen
                                                                </button>
                                                            )}
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

                                    {/* Completed courses */}
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
                                                                        {course.completed_units}/{course.enabled_units} Lektionen
                                                                        {course.parent_course_id && ' · Vertiefung'}
                                                                    </p>
                                                                </div>
                                                            </div>
                                                            <div className="flex items-center gap-1.5">
                                                                <button
                                                                    onClick={() => handleResumeCourse(course.id)}
                                                                    className="px-3 py-1.5 bg-purple-600 hover:bg-purple-500 text-white text-xs font-medium rounded-lg transition-colors"
                                                                >
                                                                    Vertiefen
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
                                </>
                            );
                        })()}
                    </div>
                )}
            </div>
        </div>
    );

    // ── Render: Generating curriculum ────────────────────────────────
    const renderGeneratingCurriculum = () => {
        if (view.kind !== 'generating-curriculum') return null;
        return (
            <div className="h-full flex items-center justify-center">
                <div className="text-center">
                    <div className="w-12 h-12 border-2 border-teal-500 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
                    <h3 className="text-lg font-semibold text-white mb-2">Lehrplan wird erstellt...</h3>
                    <p className="text-sm text-dark-500">
                        Thema: <span className="text-teal-400">{view.topic}</span>
                    </p>
                    <p className="text-xs text-dark-600 mt-1">
                        Die KI recherchiert und erstellt einen strukturierten Lehrplan
                    </p>
                </div>
            </div>
        );
    };

    // ── Render: Confirm curriculum ───────────────────────────────────
    const renderConfirmCurriculum = () => {
        if (view.kind !== 'confirm-curriculum') return null;
        const course = view.course;
        const modules = course.units.filter((u) => u.level === 1);

        return (
            <div className="h-full overflow-y-auto p-4">
                <div className="max-w-2xl mx-auto">
                    <button
                        onClick={() => { setView({ kind: 'courses' }); loadCourses(); }}
                        className="flex items-center gap-1 text-xs text-dark-500 hover:text-white mb-4 transition-colors"
                    >
                        <FiArrowLeft className="w-3.5 h-3.5" />
                        Zurück
                    </button>

                    <div className="bg-dark-800 border border-dark-700 rounded-2xl p-6">
                        <div className="mb-4">
                            <h3 className="text-lg font-bold text-white">{course.title}</h3>
                            <p className="text-sm text-dark-400 mt-1">{course.description}</p>
                        </div>

                        <div className="flex items-center justify-between mb-3">
                            <p className="text-xs text-dark-500">
                                {course.units.length} Einheiten — <span className="text-teal-400">{enabledCount(course)} ausgewählt</span>
                            </p>
                            <div className="flex gap-3 text-xs">
                                <button onClick={() => selectAllUnits(course)} className="text-dark-400 hover:text-white transition-colors">
                                    Alle auswählen
                                </button>
                                <span className="text-dark-700">|</span>
                                <button onClick={() => deselectAllUnits(course)} className="text-dark-400 hover:text-white transition-colors">
                                    Alle abwählen
                                </button>
                            </div>
                        </div>

                        <div className="max-h-[500px] overflow-y-auto space-y-0.5 mb-6 pr-2">
                            {course.units.map((unit) => {
                                const enabled = enabledUnits[unit.id] !== false;
                                const isModule = unit.level === 1;
                                return (
                                    <button
                                        key={unit.id}
                                        onClick={() => toggleUnit(unit.id)}
                                        className={`w-full flex items-start gap-2 py-2 text-sm rounded-lg px-2 transition-colors hover:bg-dark-700/50 ${!enabled ? 'opacity-40' : ''
                                            }`}
                                        style={{ paddingLeft: `${(unit.level - 1) * 20 + 8}px` }}
                                    >
                                        {enabled ? (
                                            <FiCheckSquare className="w-3.5 h-3.5 flex-shrink-0 text-teal-400 mt-0.5" />
                                        ) : (
                                            <FiSquare className="w-3.5 h-3.5 flex-shrink-0 text-dark-600 mt-0.5" />
                                        )}
                                        <div className="text-left flex-1 min-w-0">
                                            <span className={isModule ? 'text-white font-semibold' : 'text-dark-300'}>
                                                {unit.title}
                                            </span>
                                            {unit.description && (
                                                <p className="text-[10px] text-dark-600 mt-0.5 line-clamp-1">
                                                    {unit.description}
                                                </p>
                                            )}
                                        </div>
                                    </button>
                                );
                            })}
                        </div>

                        <div className="flex gap-2">
                            <button
                                onClick={() => handleStartCourse(course)}
                                disabled={enabledCount(course) === 0}
                                className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 bg-teal-600 hover:bg-teal-500 text-white text-sm font-medium rounded-xl transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                                <LuGraduationCap className="w-4 h-4" />
                                Kurs starten ({enabledCount(course)} Lektionen)
                            </button>
                            <button
                                onClick={() => { handleDeleteCourse(course.id); setView({ kind: 'courses' }); }}
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
                                onClick={() => { setView({ kind: 'courses' }); loadCourses(); }}
                                className="p-1.5 hover:bg-dark-800 rounded-lg text-dark-500 hover:text-white transition-colors flex-shrink-0"
                            >
                                <FiArrowLeft className="w-4 h-4" />
                            </button>
                            <div className="min-w-0">
                                <div className="flex items-center gap-2">
                                    <span className="text-[10px] text-teal-400 font-medium">
                                        {progress.current}/{progress.total}
                                    </span>
                                    <h3 className="text-sm font-semibold text-white truncate">{unit.title}</h3>
                                </div>
                                <p className="text-[10px] text-dark-500 truncate">{course.title}</p>
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
                            className="h-full bg-teal-500 rounded-full transition-all"
                            style={{ width: `${Math.round((progress.current / progress.total) * 100)}%` }}
                        />
                    </div>
                </div>

                {/* Messages */}
                <div className="flex-1 overflow-y-auto p-4 space-y-4">
                    {loadingMessages && (
                        <div className="flex justify-center py-8">
                            <div className="w-6 h-6 border-2 border-teal-500 border-t-transparent rounded-full animate-spin" />
                        </div>
                    )}

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
                                            ? 'bg-teal-600 text-white rounded-br-md'
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
                                                                    className="flex items-center gap-1.5 px-3 py-1.5 bg-teal-600/20 text-teal-300 hover:bg-teal-600/30 text-xs font-medium rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
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
                                    <div className="w-2 h-2 bg-teal-400 rounded-full animate-pulse" />
                                    <div className="w-2 h-2 bg-teal-400 rounded-full animate-pulse" style={{ animationDelay: '0.2s' }} />
                                    <div className="w-2 h-2 bg-teal-400 rounded-full animate-pulse" style={{ animationDelay: '0.4s' }} />
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
                            className="flex-1 px-3 py-2.5 bg-dark-800 border border-dark-700 rounded-xl text-white text-sm placeholder-dark-600 focus:outline-none focus:border-teal-500 resize-none min-h-[40px] max-h-[120px]"
                            style={{ height: 'auto' }}
                        />
                        <button
                            onClick={handleSendMessage}
                            disabled={!chatInput.trim() || sendingChat}
                            className="p-2.5 bg-teal-600 hover:bg-teal-500 text-white rounded-xl transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex-shrink-0"
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
                            className="flex items-center gap-1.5 px-3 py-1.5 bg-teal-600/20 text-teal-400 hover:bg-teal-600/30 text-xs font-medium rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                        >
                            <FiChevronRight className="w-3.5 h-3.5" />
                            Nächste Lektion
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
                        Ordner: <span className="text-teal-400">{note.folder}</span>
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

    // ── Render: Course completed ─────────────────────────────────────
    const renderCourseCompleted = () => {
        if (view.kind !== 'course-completed') return null;
        const course = view.course;
        const completedCount = course.units.filter((u) => u.status === 'completed').length;
        const totalUnits = course.units.filter((u) => u.enabled).length;

        return (
            <div className="h-full flex items-center justify-center p-4">
                <div className="text-center max-w-md">
                    <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-green-900/30 mb-4">
                        <FiCheck className="w-8 h-8 text-green-400" />
                    </div>
                    <h3 className="text-lg font-semibold text-white mb-2">Kurs abgeschlossen!</h3>
                    <p className="text-sm text-dark-400 mb-1">
                        <span className="text-teal-400 font-medium">{course.title}</span>
                    </p>
                    <p className="text-xs text-dark-500 mb-6">
                        {completedCount} von {totalUnits} Lektionen abgeschlossen
                    </p>

                    <div className="space-y-2">
                        <button
                            onClick={() => handleLoadFocus(course)}
                            disabled={loadingFocus}
                            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-purple-600 hover:bg-purple-500 text-white text-sm font-medium rounded-xl transition-colors disabled:opacity-50"
                        >
                            {loadingFocus ? (
                                <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                            ) : (
                                <LuSparkles className="w-4 h-4" />
                            )}
                            Erweiterter Schwerpunkt — Vertiefen
                        </button>
                        <button
                            onClick={() => { setView({ kind: 'courses' }); loadCourses(); }}
                            className="w-full px-4 py-2.5 bg-dark-700 hover:bg-dark-600 text-dark-300 text-sm rounded-xl transition-colors"
                        >
                            Zurück zur Übersicht
                        </button>
                    </div>
                </div>
            </div>
        );
    };

    // ── Render: Advanced focus ────────────────────────────────────────
    const renderAdvancedFocus = () => {
        if (view.kind !== 'advanced-focus') return null;
        const { course, suggestions } = view;

        return (
            <div className="h-full overflow-y-auto p-4">
                <div className="max-w-2xl mx-auto">
                    <button
                        onClick={() => { setView({ kind: 'courses' }); loadCourses(); }}
                        className="flex items-center gap-1 text-xs text-dark-500 hover:text-white mb-4 transition-colors"
                    >
                        <FiArrowLeft className="w-3.5 h-3.5" />
                        Zurück
                    </button>

                    <div className="text-center mb-6">
                        <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-purple-900/30 mb-3">
                            <LuSparkles className="w-6 h-6 text-purple-400" />
                        </div>
                        <h3 className="text-lg font-semibold text-white mb-1">Erweiterter Schwerpunkt</h3>
                        <p className="text-sm text-dark-500">
                            Basierend auf <span className="text-teal-400">{course.title}</span> — wähle ein Vertiefungsthema
                        </p>
                    </div>

                    <div className="space-y-3 mb-6">
                        {suggestions.map((s, i) => (
                            <button
                                key={i}
                                onClick={() => handleGenerateCurriculum(s.topic, course.id)}
                                className="w-full bg-dark-800 border border-dark-700 hover:border-purple-500/50 rounded-xl p-4 text-left transition-colors group"
                            >
                                <div className="flex items-center justify-between mb-1">
                                    <h4 className="text-sm font-semibold text-white group-hover:text-purple-300 transition-colors">
                                        {s.title}
                                    </h4>
                                    <FiChevronRight className="w-4 h-4 text-dark-600 group-hover:text-purple-400 transition-colors" />
                                </div>
                                <p className="text-xs text-dark-500">{s.description}</p>
                            </button>
                        ))}
                    </div>

                    {/* Custom focus */}
                    <div className="bg-dark-800 border border-dark-700 rounded-xl p-4">
                        <p className="text-xs text-dark-400 mb-2 font-medium">Oder eigenes Thema eingeben:</p>
                        <div className="flex gap-2">
                            <input
                                type="text"
                                value={customFocusInput}
                                onChange={(e) => setCustomFocusInput(e.target.value)}
                                onKeyDown={(e) => e.key === 'Enter' && customFocusInput.trim() && handleGenerateCurriculum(customFocusInput, course.id, customFocusInput)}
                                placeholder="z.B. Eigenwertprobleme, Fourier-Transformation..."
                                className="flex-1 px-3 py-2 bg-dark-900 border border-dark-700 rounded-lg text-white text-xs placeholder-dark-600 focus:outline-none focus:border-purple-500"
                            />
                            <button
                                onClick={() => customFocusInput.trim() && handleGenerateCurriculum(customFocusInput, course.id, customFocusInput)}
                                disabled={!customFocusInput.trim()}
                                className="px-3 py-2 bg-purple-600 hover:bg-purple-500 text-white text-xs rounded-lg transition-colors disabled:opacity-50"
                            >
                                <FiChevronRight className="w-4 h-4" />
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        );
    };

    // ── Main render ──────────────────────────────────────────────────
    return (
        <div className="h-full flex flex-col">
            {/* Header */}
            <div className="flex items-center gap-2 px-3 sm:px-4 py-3 border-b border-dark-800 bg-dark-900/50">
                <LuGraduationCap className="w-4 h-4 text-teal-400 flex-shrink-0" />
                <h2 className="text-sm font-semibold text-white flex-shrink-0">Infinite Teacher</h2>
                <span className="text-xs text-dark-500 ml-2 hidden sm:inline">
                    Lerne jedes Thema interaktiv mit deinem persönlichen KI-Lehrer
                </span>
            </div>

            {/* Error bar */}
            {error && (
                <div className="px-4 py-2 bg-red-900/20 border-b border-red-800/30 flex items-center justify-between">
                    <p className="text-xs text-red-400">{error}</p>
                    <button onClick={() => setError(null)} className="text-red-400 hover:text-red-300">
                        <FiX className="w-3.5 h-3.5" />
                    </button>
                </div>
            )}

            {/* Content */}
            <div className="flex-1 overflow-hidden">
                {view.kind === 'courses' && renderCoursesList()}
                {view.kind === 'generating-curriculum' && renderGeneratingCurriculum()}
                {view.kind === 'confirm-curriculum' && renderConfirmCurriculum()}
                {view.kind === 'lesson-chat' && renderLessonChat()}
                {view.kind === 'note-review' && renderNoteReview()}
                {view.kind === 'course-completed' && renderCourseCompleted()}
                {view.kind === 'advanced-focus' && renderAdvancedFocus()}
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
                            placeholder="z.B. Gauß-Elimination, Determinante..."
                            className="flex-1 px-2.5 py-1.5 bg-dark-800 border border-dark-700 rounded-lg text-white text-xs placeholder-dark-600 focus:outline-none focus:border-teal-500 min-w-0"
                        />
                        <button
                            onClick={onGenerate}
                            disabled={!termInput.trim() || generating}
                            className="px-2.5 py-1.5 bg-teal-600 hover:bg-teal-500 text-white text-xs rounded-lg transition-colors disabled:opacity-50 flex items-center gap-1"
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
