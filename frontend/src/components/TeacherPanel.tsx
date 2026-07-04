'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import {
    FiCheck, FiX, FiChevronRight, FiChevronDown, FiCheckSquare, FiSquare,
    FiSend, FiTrash2, FiArrowLeft, FiMessageCircle,
} from 'react-icons/fi';
import { LuGraduationCap, LuSparkles } from 'react-icons/lu';
import ReactMarkdown from 'react-markdown';
import { markdownComponents, remarkPlugins, rehypePlugins } from '@/lib/markdownComponents';
import { useStore } from '@/lib/store';
import {
    getTeacherCourses, getTeacherCourse, deleteTeacherCourse,
    generateCurriculum, updateCourseStatus, updateCourseUnit,
    getUnitMessages, sendTeacherChat, sendTeacherChatStream,
    generateAdvancedFocus, generateUnitQuiz, generateUnitRecap,
    editCurriculum,
    type TeacherSavedNote,
} from '@/lib/api';
import type {
    CourseListItem, CourseDetail, CourseUnit, CourseMessage,
    AdvancedFocusSuggestion, QuizQuestion, LessonRecap, LessonDiagram,
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
    | { kind: 'courses' }
    | { kind: 'generating-curriculum'; topic: string }
    | { kind: 'confirm-curriculum'; course: CourseDetail }
    | { kind: 'lesson-chat'; course: CourseDetail; unit: CourseUnit }
    | { kind: 'lesson-complete'; course: CourseDetail; unit: CourseUnit }
    | { kind: 'course-completed'; course: CourseDetail }
    | { kind: 'advanced-focus'; course: CourseDetail; suggestions: AdvancedFocusSuggestion[] };

// ── URL state (course/unit) — survives reload without breaking nav ────
// We use history.replaceState (not the Next router) so we never trigger a
// re-mount or interfere with the sidebar's view switching. On mount we read the
// params back and restore the lesson the student was in.
const URL_COURSE = 'tcourse';
const URL_UNIT = 'tunit';

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

// Pull diagrams / checkpoints out of a message's metadata (set by the stream).
function messageExtras(msg: CourseMessage): { diagrams: LessonDiagram[]; checkpoints: string[] } {
    const md = (msg.metadata || {}) as Record<string, unknown>;
    const diagrams = Array.isArray(md.diagrams) ? (md.diagrams as LessonDiagram[]) : [];
    const checkpoints = Array.isArray(md.checkpoints) ? (md.checkpoints as string[]) : [];
    return { diagrams, checkpoints };
}

export default function TeacherPanel() {
    // ── State ────────────────────────────────────────────────────────
    const [view, setView] = useState<View>({ kind: 'courses' });
    const [courses, setCourses] = useState<CourseListItem[]>([]);
    const [loadingCourses, setLoadingCourses] = useState(true);
    const [error, setError] = useState<string | null>(null);

    // Curriculum generation
    const [topicInput, setTopicInput] = useState('');
    const [descriptionInput, setDescriptionInput] = useState('');
    const [lessonCountInput, setLessonCountInput] = useState('');

    // Curriculum confirmation
    const [enabledUnits, setEnabledUnits] = useState<Record<string, boolean>>({});
    const [curriculumInstruction, setCurriculumInstruction] = useState('');
    const [editingCurriculum, setEditingCurriculum] = useState(false);

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

    // Section walk-through state for the current lesson
    const [section, setSection] = useState<{ current: number; total: number }>({ current: 0, total: 0 });

    // Prefetched caches
    const prefetchedMessagesRef = useRef<Map<string, CourseMessage[]>>(new Map());
    const prefetchedSectionRef = useRef<Map<string, { current: number; total: number }>>(new Map());

    // Advanced focus
    const [loadingFocus, setLoadingFocus] = useState(false);
    const [customFocusInput, setCustomFocusInput] = useState('');
    const [focusDescriptionInput, setFocusDescriptionInput] = useState('');
    const [focusLessonCountInput, setFocusLessonCountInput] = useState('');

    // Course overview: expand-on-click to reveal description + lessons
    const [expandedCourseId, setExpandedCourseId] = useState<string | null>(null);
    const [courseDetailCache, setCourseDetailCache] = useState<Record<string, CourseDetail>>({});
    const [categoryFilter, setCategoryFilter] = useState<string | null>(null);

    const toggleExpandCourse = useCallback(async (courseId: string) => {
        setExpandedCourseId((prev) => (prev === courseId ? null : courseId));
        if (!courseDetailCache[courseId]) {
            try {
                const detail = await getTeacherCourse(courseId);
                setCourseDetailCache((prev) => ({ ...prev, [courseId]: detail }));
            } catch { /* non-fatal — card still shows summary */ }
        }
    }, [courseDetailCache]);

    const chatEndRef = useRef<HTMLDivElement>(null);
    const lastAssistantRef = useRef<HTMLDivElement>(null);
    const chatInputRef = useRef<HTMLTextAreaElement>(null);
    const restoredRef = useRef(false);
    const { loadFolderTree } = useStore();

    // ── Toast helper ─────────────────────────────────────────────────
    const pushToast = useCallback((note: TeacherSavedNote) => {
        const id = `${note.note_id}-${Date.now()}`;
        setToasts((prev) => [...prev, { id, title: note.title, action: note.action }]);
    }, []);
    const dismissToast = useCallback((id: string) => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
    }, []);

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

    // Scroll to the start of the last assistant message
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

    // ── Keep URL in sync with the current lesson ─────────────────────
    useEffect(() => {
        if (view.kind === 'lesson-chat') {
            writeUrlState(view.course.id, view.unit.id);
        } else if (view.kind === 'courses') {
            writeUrlState(null, null);
        }
    }, [view]);

    // ── Restore from URL on first mount (reload lands back in the lesson) ─
    useEffect(() => {
        if (restoredRef.current) return;
        restoredRef.current = true;
        const { courseId, unitId } = readUrlState();
        if (!courseId) return;
        (async () => {
            try {
                const course = await getTeacherCourse(courseId);
                const unit = unitId
                    ? course.units.find((u) => u.id === unitId)
                    : course.units.find((u) => u.enabled && (u.status === 'active' || u.status === 'pending'));
                if (unit) {
                    await openUnitChat(course, unit);
                }
            } catch {
                /* stale link — stay on the course list */
            }
        })();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    // ── Curriculum generation ────────────────────────────────────────
    const handleGenerateCurriculum = async (
        topic: string,
        parentCourseId?: string,
        customFocus?: string,
        opts?: { focusDescription?: string; numLessons?: number },
    ) => {
        if (!topic.trim()) return;
        setError(null);
        setView({ kind: 'generating-curriculum', topic: topic.trim() });
        try {
            const course = await generateCurriculum(topic.trim(), parentCourseId, customFocus, opts);
            const defaults: Record<string, boolean> = {};
            course.units.forEach((u) => { defaults[u.id] = true; });
            setEnabledUnits(defaults);
            setView({ kind: 'confirm-curriculum', course });
        } catch {
            setError('Fehler beim Generieren des Lehrplans. Bitte versuche es erneut.');
            setView({ kind: 'courses' });
        }
    };

    const handleCreateCourse = () => {
        if (!topicInput.trim()) return;
        const parsed = parseInt(lessonCountInput, 10);
        const numLessons = Number.isFinite(parsed) && parsed > 0 ? parsed : undefined;
        handleGenerateCurriculum(topicInput, undefined, undefined, {
            focusDescription: descriptionInput.trim() || undefined,
            numLessons,
        });
        setDescriptionInput('');
        setLessonCountInput('');
    };

    const handleDeepen = (course: CourseDetail, topic: string, customFocus?: string) => {
        if (!topic.trim()) return;
        const parsed = parseInt(focusLessonCountInput, 10);
        const numLessons = Number.isFinite(parsed) && parsed > 0 ? parsed : undefined;
        handleGenerateCurriculum(topic, course.id, customFocus, {
            focusDescription: focusDescriptionInput.trim() || undefined,
            numLessons,
        });
        setFocusDescriptionInput('');
        setFocusLessonCountInput('');
        setCustomFocusInput('');
    };

    // ── Adjust the curriculum via chat ───────────────────────────────
    const handleEditCurriculum = async () => {
        if (view.kind !== 'confirm-curriculum' || !curriculumInstruction.trim() || editingCurriculum) return;
        const instruction = curriculumInstruction.trim();
        setCurriculumInstruction('');
        setEditingCurriculum(true);
        setError(null);
        try {
            const updated = await editCurriculum(view.course.id, instruction);
            const defaults: Record<string, boolean> = {};
            updated.units.forEach((u) => { defaults[u.id] = true; });
            setEnabledUnits(defaults);
            setView({ kind: 'confirm-curriculum', course: updated });
        } catch {
            setError('Fehler beim Anpassen des Lehrplans.');
        } finally {
            setEditingCurriculum(false);
        }
    };

    // ── Start / resume course ────────────────────────────────────────
    const handleStartCourse = async (course: CourseDetail) => {
        setError(null);
        try {
            for (const unit of course.units) {
                if (enabledUnits[unit.id] === false) {
                    await updateCourseUnit(course.id, unit.id, { enabled: false });
                }
            }
            await updateCourseStatus(course.id, 'active');
            const updated = await getTeacherCourse(course.id);
            const firstUnit = updated.units.find((u) => u.enabled && u.status === 'pending');
            if (firstUnit) await openUnitChat(updated, firstUnit);
        } catch {
            setError('Fehler beim Starten des Kurses.');
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
                setView({ kind: 'course-completed', course });
            }
        } catch {
            setError('Fehler beim Laden des Kurses.');
        }
    };

    // ── Reset per-lesson ephemeral state ─────────────────────────────
    const resetLessonEphemeral = () => {
        setStatusLine('');
        setInlineQuiz(null);
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

    // ── Prefetch next unit greeting ──────────────────────────────────
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
    // Runs one streamed turn, wiring live status lines + silent-save toasts.
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

    // ── After a turn: handle tutor-driven quiz + section state ───────
    const afterTurn = async (
        courseId: string,
        unitId: string,
        response: Awaited<ReturnType<typeof sendTeacherChatStream>>,
    ) => {
        setStatusLine('');
        // The tutor decided a quick check makes sense — load + show it inline.
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

    // ── Advance to the next section ──────────────────────────────────
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

    // ── Complete unit → celebration ──────────────────────────────────
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
                setView({ kind: 'course-completed', course: final });
            } catch {
                setError('Fehler beim Abschließen des Kurses.');
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

    const getUnitProgress = (course: CourseDetail, currentUnit: CourseUnit) => {
        const enabled = course.units.filter((u) => u.enabled);
        const currentIndex = enabled.findIndex((u) => u.id === currentUnit.id);
        return { current: currentIndex + 1, total: enabled.length };
    };

    const isLastEnabledUnit = (course: CourseDetail, currentUnit: CourseUnit) => {
        const sorted = [...course.units].sort((a, b) => a.order_index - b.order_index);
        const curIdx = sorted.findIndex(u => u.id === currentUnit.id);
        return !sorted.slice(curIdx + 1).some(
            u => u.enabled && (u.status === 'pending' || u.status === 'active')
        );
    };

    // ── Render: a single course card (modern, expand-on-click) ───────
    const renderCourseCard = (course: CourseListItem, done: boolean) => {
        const pct = course.enabled_units > 0
            ? Math.round((course.completed_units / course.enabled_units) * 100)
            : 0;
        const isExpanded = expandedCourseId === course.id;
        const detail = courseDetailCache[course.id];
        const lessons = detail
            ? [...detail.units].filter((u) => u.enabled && u.level === 2).sort((a, b) => a.order_index - b.order_index)
            : [];

        return (
            <div
                key={course.id}
                className={`slide-up group rounded-2xl border transition-all duration-200 overflow-hidden ${isExpanded
                    ? 'border-teal-500/40 bg-dark-800 shadow-lg shadow-teal-950/20'
                    : 'border-dark-700 bg-dark-800/60 hover:border-dark-600 hover:bg-dark-800'}`}
            >
                {/* Clickable header */}
                <button
                    onClick={() => toggleExpandCourse(course.id)}
                    className="w-full text-left p-4 flex items-start gap-4"
                >
                    {/* Progress ring */}
                    <CircularProgress pct={pct} done={done} />

                    <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1 flex-wrap">
                            {done ? (
                                <span className="px-2 py-0.5 text-[10px] font-medium rounded-full bg-green-600/20 text-green-400">
                                    Abgeschlossen
                                </span>
                            ) : (
                                <span className={`px-2 py-0.5 text-[10px] font-medium rounded-full ${course.status === 'active' ? 'bg-teal-600/20 text-teal-400' : 'bg-dark-700 text-dark-400'}`}>
                                    {course.status === 'active' ? 'Aktiv' : 'Entwurf'}
                                </span>
                            )}
                            {course.parent_course_id && (
                                <span className="px-2 py-0.5 text-[10px] font-medium rounded-full bg-purple-600/20 text-purple-400">
                                    Vertiefung
                                </span>
                            )}
                            <CategoryBadge category={course.category} />
                        </div>
                        <h4 className="text-sm font-semibold text-white truncate">{course.title}</h4>
                        <p className={`text-xs text-dark-500 mt-0.5 transition-all ${isExpanded ? '' : 'line-clamp-1'}`}>
                            {course.description || 'Keine Beschreibung'}
                        </p>
                        <p className="text-[10px] text-dark-600 mt-1.5">
                            {course.completed_units}/{course.enabled_units} Lektionen
                        </p>
                    </div>

                    <FiChevronDown
                        className={`w-4 h-4 text-dark-500 flex-shrink-0 mt-1 transition-transform duration-200 ${isExpanded ? 'rotate-180 text-teal-400' : 'group-hover:text-dark-300'}`}
                    />
                </button>

                {/* Expandable body */}
                <div className={`grid transition-all duration-300 ease-out ${isExpanded ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'}`}>
                    <div className="overflow-hidden">
                        <div className="px-4 pb-4">
                            {/* Lesson list */}
                            <div className="rounded-xl bg-dark-900/60 border border-dark-700/60 p-3 mb-3">
                                <p className="text-[10px] font-semibold uppercase tracking-wider text-dark-500 mb-2">
                                    Lektionen
                                </p>
                                {detail ? (
                                    lessons.length > 0 ? (
                                        <ul className="space-y-1 max-h-52 overflow-y-auto pr-1">
                                            {lessons.map((u) => {
                                                const uDone = u.status === 'completed';
                                                const uActive = u.status === 'active';
                                                return (
                                                    <li key={u.id} className="flex items-center gap-2 text-xs">
                                                        <span className={`w-4 h-4 rounded-full flex items-center justify-center flex-shrink-0 ${uDone ? 'bg-teal-500/80' : uActive ? 'border-2 border-teal-400' : 'border border-dark-600'}`}>
                                                            {uDone && <FiCheck className="w-2.5 h-2.5 text-white" />}
                                                        </span>
                                                        <span className={`truncate ${uDone ? 'text-dark-400' : uActive ? 'text-teal-300' : 'text-dark-300'}`}>
                                                            {u.title}
                                                        </span>
                                                    </li>
                                                );
                                            })}
                                        </ul>
                                    ) : (
                                        <p className="text-xs text-dark-500">Keine Lektionen.</p>
                                    )
                                ) : (
                                    <div className="space-y-1.5 py-1">
                                        <div className="h-3 bg-dark-700 rounded animate-pulse w-full" />
                                        <div className="h-3 bg-dark-700 rounded animate-pulse w-4/5" />
                                        <div className="h-3 bg-dark-700 rounded animate-pulse w-3/5" />
                                    </div>
                                )}
                            </div>

                            {/* Actions */}
                            <div className="flex items-center gap-2">
                                <button
                                    onClick={() => done ? handleLoadFocus(detail || courseDetailCache[course.id]!) : handleResumeCourse(course.id)}
                                    disabled={done && (loadingFocus || !detail)}
                                    className={`flex-1 flex items-center justify-center gap-2 px-4 py-2 text-xs font-semibold rounded-xl transition-colors disabled:opacity-50 ${done ? 'bg-purple-600 hover:bg-purple-500 text-white' : 'bg-teal-600 hover:bg-teal-500 text-white'}`}
                                >
                                    {done ? (
                                        <><LuSparkles className="w-3.5 h-3.5" /> Vertiefen</>
                                    ) : (
                                        <>{course.status === 'active' ? 'Fortsetzen' : 'Öffnen'} <FiChevronRight className="w-3.5 h-3.5" /></>
                                    )}
                                </button>
                                <button
                                    onClick={() => handleDeleteCourse(course.id)}
                                    className="p-2 text-dark-500 hover:text-red-400 hover:bg-dark-700 rounded-xl transition-colors"
                                    title="Kurs löschen"
                                >
                                    <FiTrash2 className="w-4 h-4" />
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        );
    };

    // ── Render: Courses list ─────────────────────────────────────────
    const renderCoursesList = () => (
        <div className="h-full flex flex-col">
            <div className="p-4 border-b border-dark-800">
                <div className="max-w-lg mx-auto space-y-2.5">
                    <div className="flex gap-2">
                        <input
                            type="text"
                            value={topicInput}
                            onChange={(e) => setTopicInput(e.target.value)}
                            onKeyDown={(e) => e.key === 'Enter' && handleCreateCourse()}
                            placeholder='Thema eingeben, z.B. "Lineare Algebra" oder "Organische Chemie"'
                            className="flex-1 px-4 py-3 bg-dark-800 border border-dark-700 rounded-xl text-white text-sm placeholder-dark-600 focus:outline-none focus:border-teal-500"
                            autoFocus
                        />
                        <button
                            onClick={handleCreateCourse}
                            disabled={!topicInput.trim()}
                            title="Lehrplan generieren"
                            className="px-4 py-3 bg-teal-600 hover:bg-teal-500 text-white rounded-xl transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            <LuGraduationCap className="w-5 h-5" />
                        </button>
                    </div>
                    <textarea
                        value={descriptionInput}
                        onChange={(e) => setDescriptionInput(e.target.value)}
                        placeholder="Beschreibung & Vertiefung (optional) — worauf legst du besonderen Wert? z.B. 'Fokus auf Beweise und praktische Beispiele, weniger Geschichte'"
                        rows={2}
                        className="w-full px-4 py-2.5 bg-dark-800 border border-dark-700 rounded-xl text-white text-sm placeholder-dark-600 focus:outline-none focus:border-teal-500 resize-none"
                    />
                    <div className="flex items-center gap-2">
                        <label className="text-xs text-dark-500 flex-shrink-0">Anzahl der Lektionen</label>
                        <input
                            type="number"
                            min={1}
                            max={60}
                            value={lessonCountInput}
                            onChange={(e) => setLessonCountInput(e.target.value)}
                            onKeyDown={(e) => e.key === 'Enter' && handleCreateCourse()}
                            placeholder="auto"
                            className="w-24 px-3 py-2 bg-dark-800 border border-dark-700 rounded-lg text-white text-sm placeholder-dark-600 focus:outline-none focus:border-teal-500"
                        />
                        <span className="text-[11px] text-dark-600">leer lassen = KI entscheidet</span>
                    </div>
                </div>
            </div>

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
                            Lerne in interaktiven Lektionen — Notizen entstehen automatisch im Hintergrund.
                        </p>
                    </div>
                ) : (
                    <div className="max-w-3xl mx-auto space-y-6">
                        {(() => {
                            // Categories present across all courses (in canonical order)
                            const present = CATEGORY_ORDER.filter(cat =>
                                courses.some(c => c.category === cat)
                            );
                            const matches = (c: CourseListItem) => !categoryFilter || c.category === categoryFilter;
                            const activeDraft = courses.filter(c => c.status !== 'completed' && matches(c));
                            const completed = courses.filter(c => c.status === 'completed' && matches(c));
                            return (
                                <>
                                    {present.length > 1 && (
                                        <CategoryFilter
                                            categories={present}
                                            active={categoryFilter}
                                            onSelect={setCategoryFilter}
                                        />
                                    )}

                                    {activeDraft.length > 0 && (
                                        <div>
                                            <h3 className="text-[11px] font-semibold uppercase tracking-wider text-dark-500 mb-3 px-1">
                                                Meine Kurse
                                            </h3>
                                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                                                {activeDraft.map((course) => renderCourseCard(course, false))}
                                            </div>
                                        </div>
                                    )}

                                    {completed.length > 0 && (
                                        <div>
                                            <h3 className="text-[11px] font-semibold uppercase tracking-wider text-dark-500 mb-3 px-1">
                                                Abgeschlossen
                                            </h3>
                                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                                                {completed.map((course) => renderCourseCard(course, true))}
                                            </div>
                                        </div>
                                    )}

                                    {activeDraft.length === 0 && completed.length === 0 && (
                                        <p className="text-center text-sm text-dark-500 py-8">
                                            Keine Kurse in dieser Kategorie.
                                        </p>
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

    // ── Render: Confirm curriculum (with chat-based editing) ─────────
    const renderConfirmCurriculum = () => {
        if (view.kind !== 'confirm-curriculum') return null;
        const course = view.course;

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

                        <div className={`max-h-[420px] overflow-y-auto space-y-0.5 mb-4 pr-2 transition-opacity ${editingCurriculum ? 'opacity-40 pointer-events-none' : ''}`}>
                            {course.units.map((unit) => {
                                const enabled = enabledUnits[unit.id] !== false;
                                const isModule = unit.level === 1;
                                return (
                                    <button
                                        key={unit.id}
                                        onClick={() => toggleUnit(unit.id)}
                                        className={`w-full flex items-start gap-2 py-2 text-sm rounded-lg px-2 transition-colors hover:bg-dark-700/50 ${!enabled ? 'opacity-40' : ''}`}
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

                        {/* Curriculum editing via chat */}
                        <div className="mb-5 rounded-xl border border-dark-700 bg-dark-900/50 p-3">
                            <div className="flex items-center gap-1.5 mb-2 text-[11px] text-dark-400">
                                <FiMessageCircle className="w-3.5 h-3.5 text-teal-400" />
                                Lehrplan anpassen — sag der KI, was du ändern möchtest
                            </div>
                            <div className="flex gap-2">
                                <input
                                    type="text"
                                    value={curriculumInstruction}
                                    onChange={(e) => setCurriculumInstruction(e.target.value)}
                                    onKeyDown={(e) => e.key === 'Enter' && handleEditCurriculum()}
                                    disabled={editingCurriculum}
                                    placeholder='z.B. "mehr Fokus auf Beweise" oder "Lektion zu Eigenwerten ergänzen"'
                                    className="flex-1 px-3 py-2 bg-dark-800 border border-dark-700 rounded-lg text-white text-xs placeholder-dark-600 focus:outline-none focus:border-teal-500 disabled:opacity-50"
                                />
                                <button
                                    onClick={handleEditCurriculum}
                                    disabled={!curriculumInstruction.trim() || editingCurriculum}
                                    className="px-3 py-2 bg-teal-600 hover:bg-teal-500 text-white text-xs rounded-lg transition-colors disabled:opacity-50 flex items-center gap-1.5"
                                >
                                    {editingCurriculum ? (
                                        <div className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />
                                    ) : (
                                        <FiSend className="w-3.5 h-3.5" />
                                    )}
                                    Anpassen
                                </button>
                            </div>
                        </div>

                        <div className="flex gap-2">
                            <button
                                onClick={() => handleStartCourse(course)}
                                disabled={enabledCount(course) === 0 || editingCurriculum}
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
        const hasSections = section.total > 0;
        const onLastSection = !hasSections || section.current >= section.total - 1;
        const currentSectionTitle =
            hasSections && unit.sections && unit.sections[section.current]
                ? unit.sections[section.current].title
                : null;

        const visibleMessages = messages.filter(m => m.role !== 'user' || !isControlMessage(m.content));

        return (
            <div className="h-full flex flex-col relative">
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
                                        Lektion {progress.current}/{progress.total}
                                    </span>
                                    <h3 className="text-sm font-semibold text-white truncate">{unit.title}</h3>
                                </div>
                                {hasSections ? (
                                    <p className="text-[10px] text-dark-500 truncate">
                                        <span className="text-teal-500/80">Abschnitt {section.current + 1}/{section.total}</span>
                                        {currentSectionTitle ? ` · ${currentSectionTitle}` : ''}
                                    </p>
                                ) : (
                                    <p className="text-[10px] text-dark-500 truncate">{course.title}</p>
                                )}
                            </div>
                        </div>
                        <div className="flex items-center gap-1.5 flex-shrink-0">
                            <LearningPathButton accent="teal" onClick={() => setShowPath(true)} />
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
                                    className={`h-1.5 flex-1 rounded-full transition-colors ${i < section.current ? 'bg-teal-500' : i === section.current ? 'bg-teal-400' : 'bg-dark-800'}`}
                                />
                            ))}
                        </div>
                    ) : (
                        <div className="mt-2 h-1 bg-dark-800 rounded-full overflow-hidden">
                            <div
                                className="h-full bg-teal-500 rounded-full transition-all"
                                style={{ width: `${Math.round((progress.current / progress.total) * 100)}%` }}
                            />
                        </div>
                    )}
                </div>

                {showPath && (
                    <LearningPathOverlay
                        units={course.units}
                        currentUnitId={unit.id}
                        accent="teal"
                        title={course.title}
                        onClose={() => setShowPath(false)}
                        onSelectUnit={(u) => { setShowPath(false); openUnitChat(course, u); }}
                    />
                )}

                {/* Messages */}
                <div className="flex-1 overflow-y-auto p-4 space-y-4">
                    <LessonObjectivesCard unit={unit} accent="teal" />
                    {visibleMessages.map((msg, idx, arr) => {
                        const isLastAssistant = msg.role === 'assistant' && idx === arr.length - 1;
                        if (msg.role === 'note_generated') {
                            // Notes are silent now; keep old markers subtle for existing courses.
                            return null;
                        }
                        const { diagrams, checkpoints } = msg.role === 'assistant' ? messageExtras(msg) : { diagrams: [], checkpoints: [] };
                        return (
                            <div
                                key={msg.id}
                                ref={isLastAssistant ? lastAssistantRef : undefined}
                                className={`chat-message flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                            >
                                <div
                                    className={`max-w-[85%] sm:max-w-[78%] px-4 py-3 rounded-2xl text-sm ${msg.role === 'user'
                                        ? 'bg-teal-600 text-white rounded-br-md'
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
                                                <div key={i} className="mt-3 flex items-start gap-2 px-3 py-2 rounded-xl bg-teal-600/10 border border-teal-500/20">
                                                    <FiMessageCircle className="w-3.5 h-3.5 text-teal-300 mt-0.5 flex-shrink-0" />
                                                    <p className="text-xs text-teal-100">{q}</p>
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

                    {/* Tutor-driven inline quiz */}
                    {inlineQuiz && !sendingChat && (
                        <div className="flex justify-start">
                            <div className="w-full max-w-[92%]">
                                <InlineQuiz
                                    questions={inlineQuiz}
                                    accent="teal"
                                    onFinished={() => { /* stays visible with result */ }}
                                />
                            </div>
                        </div>
                    )}

                    {/* Thinking status while the tutor works */}
                    {sendingChat && (
                        <div className="flex justify-start">
                            <div className="bg-dark-800 border border-dark-700 rounded-2xl rounded-bl-md px-4 py-3 max-w-[85%]">
                                <ThinkingStatus status={statusLine} accent="teal" />
                            </div>
                        </div>
                    )}

                    <div ref={chatEndRef} />
                </div>

                {/* Chat input + single primary action */}
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
                                className="flex items-center gap-1.5 px-4 py-2.5 bg-teal-600 hover:bg-teal-500 text-white text-sm font-semibold rounded-xl transition-colors disabled:opacity-40 disabled:cursor-not-allowed flex-shrink-0"
                            >
                                Weiter
                                <FiChevronRight className="w-4 h-4" />
                            </button>
                        ) : (
                            <button
                                onClick={handleCompleteUnit}
                                disabled={sendingChat || messages.length < 2}
                                title="Lektion abschließen"
                                className="flex items-center gap-1.5 px-4 py-2.5 bg-teal-600 hover:bg-teal-500 text-white text-sm font-semibold rounded-xl transition-colors disabled:opacity-40 disabled:cursor-not-allowed flex-shrink-0"
                            >
                                <FiCheck className="w-4 h-4" />
                                Abschließen
                            </button>
                        )}
                    </div>
                </div>

                {/* Silent note-saved toasts */}
                <NoteToastHost toasts={toasts} accent="teal" onDismiss={dismissToast} />
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

                    <div className="bg-dark-800/50 border border-dark-700 rounded-xl p-4 mb-3 space-y-2.5">
                        <p className="text-xs text-dark-400 font-medium">Optionen für die Vertiefung</p>
                        <textarea
                            value={focusDescriptionInput}
                            onChange={(e) => setFocusDescriptionInput(e.target.value)}
                            placeholder="Beschreibung & Vertiefung (optional) — worauf legst du besonderen Wert?"
                            rows={2}
                            className="w-full px-3 py-2 bg-dark-900 border border-dark-700 rounded-lg text-white text-xs placeholder-dark-600 focus:outline-none focus:border-purple-500 resize-none"
                        />
                        <div className="flex items-center gap-2">
                            <label className="text-xs text-dark-500 flex-shrink-0">Anzahl der Lektionen</label>
                            <input
                                type="number"
                                min={1}
                                max={60}
                                value={focusLessonCountInput}
                                onChange={(e) => setFocusLessonCountInput(e.target.value)}
                                placeholder="auto"
                                className="w-24 px-3 py-1.5 bg-dark-900 border border-dark-700 rounded-lg text-white text-xs placeholder-dark-600 focus:outline-none focus:border-purple-500"
                            />
                            <span className="text-[11px] text-dark-600">leer lassen = KI entscheidet</span>
                        </div>
                    </div>

                    <div className="bg-dark-800 border border-dark-700 rounded-xl p-4 mb-5">
                        <p className="text-xs text-dark-400 mb-2 font-medium">Eigenes Vertiefungsthema</p>
                        <div className="flex gap-2">
                            <input
                                type="text"
                                value={customFocusInput}
                                onChange={(e) => setCustomFocusInput(e.target.value)}
                                onKeyDown={(e) => e.key === 'Enter' && customFocusInput.trim() && handleDeepen(course, customFocusInput, customFocusInput)}
                                placeholder="z.B. Eigenwertprobleme, Fourier-Transformation..."
                                className="flex-1 px-3 py-2 bg-dark-900 border border-dark-700 rounded-lg text-white text-sm placeholder-dark-600 focus:outline-none focus:border-purple-500"
                            />
                            <button
                                onClick={() => customFocusInput.trim() && handleDeepen(course, customFocusInput, customFocusInput)}
                                disabled={!customFocusInput.trim()}
                                className="flex items-center gap-1.5 px-4 py-2 bg-purple-600 hover:bg-purple-500 text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex-shrink-0"
                            >
                                <LuGraduationCap className="w-4 h-4" />
                                Erstellen
                            </button>
                        </div>
                    </div>

                    <p className="text-xs text-dark-400 font-medium mb-2">Oder ein vorgeschlagenes Thema wählen:</p>
                    <div className="space-y-3 mb-4">
                        {suggestions.map((s, i) => (
                            <button
                                key={i}
                                onClick={() => handleDeepen(course, s.topic)}
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
                </div>
            </div>
        );
    };

    // ── Main render ──────────────────────────────────────────────────
    return (
        <div className="h-full flex flex-col">
            <div className="flex items-center gap-2 px-3 sm:px-4 py-3 border-b border-dark-800 bg-dark-900/50">
                <LuGraduationCap className="w-4 h-4 text-teal-400 flex-shrink-0" />
                <h2 className="text-sm font-semibold text-white flex-shrink-0">Infinite Teacher</h2>
                <span className="text-xs text-dark-500 ml-2 hidden sm:inline">
                    Lerne jedes Thema interaktiv mit deinem persönlichen KI-Lehrer
                </span>
            </div>

            {error && (
                <div className="px-4 py-2 bg-red-900/20 border-b border-red-800/30 flex items-center justify-between">
                    <p className="text-xs text-red-400">{error}</p>
                    <button onClick={() => setError(null)} className="text-red-400 hover:text-red-300">
                        <FiX className="w-3.5 h-3.5" />
                    </button>
                </div>
            )}

            <div className="flex-1 overflow-hidden">
                {view.kind === 'courses' && renderCoursesList()}
                {view.kind === 'generating-curriculum' && renderGeneratingCurriculum()}
                {view.kind === 'confirm-curriculum' && renderConfirmCurriculum()}
                {view.kind === 'lesson-chat' && renderLessonChat()}
                {view.kind === 'lesson-complete' && (
                    <LessonCompleteCelebration
                        unitTitle={view.unit.title}
                        recap={recap}
                        accent="teal"
                        isLastUnit={isLastEnabledUnit(view.course, view.unit)}
                        nextLabel="Nächste Lektion"
                        onContinue={handleAdvanceAfterCelebration}
                        loadingRecap={loadingRecap}
                    />
                )}
                {view.kind === 'course-completed' && renderCourseCompleted()}
                {view.kind === 'advanced-focus' && renderAdvancedFocus()}
            </div>
        </div>
    );
}

// ── Circular progress ring for course cards ──────────────────────────
function CircularProgress({ pct, done }: { pct: number; done: boolean }) {
    const size = 44;
    const stroke = 4;
    const r = (size - stroke) / 2;
    const circ = 2 * Math.PI * r;
    const offset = circ - (pct / 100) * circ;
    const color = done ? '#22c55e' : '#2dd4bf';

    return (
        <div className="relative flex-shrink-0" style={{ width: size, height: size }}>
            <svg width={size} height={size} className="-rotate-90">
                <circle cx={size / 2} cy={size / 2} r={r} stroke="#1f2937" strokeWidth={stroke} fill="none" />
                <circle
                    cx={size / 2} cy={size / 2} r={r}
                    stroke={color} strokeWidth={stroke} fill="none"
                    strokeLinecap="round"
                    strokeDasharray={circ}
                    strokeDashoffset={offset}
                    style={{ transition: 'stroke-dashoffset 0.5s ease-out' }}
                />
            </svg>
            <div className="absolute inset-0 flex items-center justify-center">
                {done ? (
                    <FiCheck className="w-4 h-4 text-green-400" />
                ) : (
                    <span className="text-[10px] font-semibold text-white">{pct}%</span>
                )}
            </div>
        </div>
    );
}
