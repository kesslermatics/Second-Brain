'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import {
    FiCheck, FiX, FiChevronRight, FiLoader, FiSquare, FiCheckSquare,
    FiSend, FiZap, FiTrash2, FiArrowLeft, FiPlus, FiBookOpen,
    FiChevronDown, FiChevronUp,
} from 'react-icons/fi';
import { LuBrain, LuGraduationCap, LuSparkles, LuListChecks } from 'react-icons/lu';
import ReactMarkdown from 'react-markdown';
import { markdownComponents, remarkPlugins, rehypePlugins } from '@/lib/markdownComponents';
import { useStore } from '@/lib/store';
import {
    getTeacherCourses, getTeacherCourse, deleteTeacherCourse,
    generateCurriculum, updateCourseStatus, updateCourseUnit,
    getUnitMessages, sendTeacherChat, sendTeacherChatStream,
    generateLessonNotes, generateTermNote,
    recordNotesGenerated,
    generateAdvancedFocus,
    generateUnitQuiz, generateUnitRecap,
    ensureFolderPath, createNote,
} from '@/lib/api';
import type {
    CourseListItem, CourseDetail, CourseUnit, CourseMessage,
    CourseNoteResult, AdvancedFocusSuggestion, QuizQuestion, LessonRecap,
} from '@/lib/types';
import {
    LessonObjectivesCard, LearningPathButton, LearningPathOverlay,
    LessonQuiz, LessonCompleteCelebration, isControlMessage,
} from './TeachingComponents';

type View =
    | { kind: 'courses' }
    | { kind: 'generating-curriculum'; topic: string }
    | { kind: 'confirm-curriculum'; course: CourseDetail }
    | { kind: 'lesson-chat'; course: CourseDetail; unit: CourseUnit }
    | { kind: 'note-review'; course: CourseDetail; unit: CourseUnit; notes: CourseNoteResult[]; currentIdx: number }
    | { kind: 'quiz'; course: CourseDetail; unit: CourseUnit; questions: QuizQuestion[] }
    | { kind: 'lesson-complete'; course: CourseDetail; unit: CourseUnit }
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
    const [descriptionInput, setDescriptionInput] = useState('');
    const [lessonCountInput, setLessonCountInput] = useState('');

    // curriculum confirmation
    const [enabledUnits, setEnabledUnits] = useState<Record<string, boolean>>({});

    // Chat
    const [messages, setMessages] = useState<CourseMessage[]>([]);
    const [chatInput, setChatInput] = useState('');
    const [sendingChat, setSendingChat] = useState(false);
    const [streamingThought, setStreamingThought] = useState('');

    // Note generation
    const [generatingNotes, setGeneratingNotes] = useState(false);
    const [savingNote, setSavingNote] = useState(false);

    // Term note
    const [termInput, setTermInput] = useState('');
    const [generatingTerm, setGeneratingTerm] = useState(false);

    // Quiz / recap / learning path
    const [quizSuggested, setQuizSuggested] = useState(false);
    const [generatingQuiz, setGeneratingQuiz] = useState(false);
    // Agentic teacher: live tool steps + notes the tutor proposes to save
    const [toolSteps, setToolSteps] = useState<string[]>([]);
    const [proposedNotes, setProposedNotes] = useState<CourseNoteResult[]>([]);
    const [recap, setRecap] = useState<LessonRecap | null>(null);
    const [loadingRecap, setLoadingRecap] = useState(false);
    const [showPath, setShowPath] = useState(false);

    // Section walk-through state for the current lesson
    const [section, setSection] = useState<{ current: number; total: number }>({ current: 0, total: 0 });

    // Prefetched caches: unitId -> data
    const prefetchedNotesRef = useRef<Map<string, CourseNoteResult[]>>(new Map());
    const prefetchedMessagesRef = useRef<Map<string, CourseMessage[]>>(new Map());
    const prefetchedSectionRef = useRef<Map<string, { current: number; total: number }>>(new Map());
    const userSentMessageRef = useRef(false);

    // Advanced focus
    const [loadingFocus, setLoadingFocus] = useState(false);
    const [customFocusInput, setCustomFocusInput] = useState('');
    const [focusDescriptionInput, setFocusDescriptionInput] = useState('');
    const [focusLessonCountInput, setFocusLessonCountInput] = useState('');

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

    // ── Create course from the main form (topic + description + lessons) ─
    const handleCreateCourse = () => {
        if (!topicInput.trim()) return;
        const parsed = parseInt(lessonCountInput, 10);
        const numLessons = Number.isFinite(parsed) && parsed > 0 ? parsed : undefined;
        handleGenerateCurriculum(topicInput, undefined, undefined, {
            focusDescription: descriptionInput.trim() || undefined,
            numLessons,
        });
        // Reset the form for next time
        setDescriptionInput('');
        setLessonCountInput('');
    };

    // ── Start a deepening course (advanced focus) ────────────────────
    const handleDeepen = (course: CourseDetail, topic: string, customFocus?: string) => {
        if (!topic.trim()) return;
        const parsed = parseInt(focusLessonCountInput, 10);
        const numLessons = Number.isFinite(parsed) && parsed > 0 ? parsed : undefined;
        handleGenerateCurriculum(topic, course.id, customFocus, {
            focusDescription: focusDescriptionInput.trim() || undefined,
            numLessons,
        });
        // Reset deepening form
        setFocusDescriptionInput('');
        setFocusLessonCountInput('');
        setCustomFocusInput('');
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
        userSentMessageRef.current = false;
        setView({ kind: 'lesson-chat', course, unit });

        // Use prefetched messages from memory if available (instant)
        const cached = prefetchedMessagesRef.current.get(unit.id);
        prefetchedMessagesRef.current.delete(unit.id);

        if (cached && cached.length > 0) {
            setMessages(cached);
            userSentMessageRef.current = cached.some(
                m => m.role === 'user' && !isControlMessage(m.content)
            );
            const cachedSection = prefetchedSectionRef.current.get(unit.id);
            prefetchedSectionRef.current.delete(unit.id);
            setSection(cachedSection || {
                current: unit.current_section || 0,
                total: unit.sections?.length || 0,
            });
            prefetchNotesForUnit(course.id, unit.id);
            prefetchNextUnit(course, unit);
            return;
        }

        // No cache — fetch from server
        setMessages([]);
        // Initialise section state from the unit (may be empty until first [START])
        setSection({ current: unit.current_section || 0, total: unit.sections?.length || 0 });
        try {
            const msgs = await getUnitMessages(course.id, unit.id);
            setMessages(msgs);
            if (msgs.length === 0) {
                setSendingChat(true);
                setStreamingThought('');
                setToolSteps([]);
                let fullContent = '';
                const response = await sendTeacherChatStream(course.id, unit.id, '[START]', (event) => {
                    if (event.type === 'thinking') {
                        setStreamingThought((prev) => prev + event.content);
                    } else if (event.type === 'chunk') {
                        // Accumulate only — the answer is rendered formatted once complete.
                        fullContent += event.content;
                    } else if (event.type === 'tool_call') {
                        setToolSteps((prev) => [...prev, event.content]);
                    }
                });
                setStreamingThought('');
                setToolSteps([]);
                setMessages([
                    { id: 'start', role: 'user', content: '[START]', metadata: null, created_at: null },
                    response.message,
                ]);
                setSection({ current: response.current_section, total: response.total_sections });
                setSendingChat(false);
            } else {
                userSentMessageRef.current = msgs.some(
                    m => m.role === 'user' && !isControlMessage(m.content)
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
        }).catch(() => { });
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
                        response.message,
                    ]);
                    prefetchedSectionRef.current.set(nextUnit.id, {
                        current: response.current_section,
                        total: response.total_sections,
                    });
                    prefetchNotesForUnit(course.id, nextUnit.id);
                }).catch(() => { });
            }
        }).catch(() => { });
    };

    // ── Send chat message ────────────────────────────────────────────
    const handleSendMessage = async () => {
        if (!chatInput.trim() || sendingChat || view.kind !== 'lesson-chat') return;
        const msg = chatInput.trim();
        setChatInput('');
        setSendingChat(true);
        setStreamingThought('');
        setQuizSuggested(false);
        setToolSteps([]);
        setProposedNotes([]);
        userSentMessageRef.current = true;  // invalidate prefetched notes

        // Optimistic add user message
        const tempId = `temp-${Date.now()}`;
        setMessages((prev) => [
            ...prev,
            { id: tempId, role: 'user', content: msg, metadata: null, created_at: new Date().toISOString() },
        ]);

        try {
            let fullContent = '';
            const noteProposals: CourseNoteResult[] = [];
            const response = await sendTeacherChatStream(view.course.id, view.unit.id, msg, (event) => {
                if (event.type === 'thinking') {
                    setStreamingThought((prev) => prev + event.content);
                } else if (event.type === 'chunk') {
                    // Accumulate only — the answer is rendered formatted once complete.
                    fullContent += event.content;
                } else if (event.type === 'tool_call') {
                    setToolSteps((prev) => [...prev, event.content]);
                } else if (event.type === 'note_proposal') {
                    noteProposals.push({
                        title: event.note.title,
                        content: event.note.content,
                        folder: `Kurse/${view.course.title}`,
                        tag_ids: [],
                        tag_names: event.note.tags || [],
                    });
                }
            });
            setStreamingThought('');
            setToolSteps([]);
            setMessages((prev) => [...prev.filter((m) => m.id !== tempId),
            { id: tempId, role: 'user', content: msg, metadata: null, created_at: new Date().toISOString() },
            response.message
            ]);
            setSection({ current: response.current_section, total: response.total_sections });
            setQuizSuggested(!!response.quiz_suggested);
            if (noteProposals.length > 0) setProposedNotes(noteProposals);
        } catch {
            setError('Fehler beim Senden der Nachricht.');
            setMessages((prev) => prev.filter((m) => m.id !== tempId));
            setStreamingThought('');
            setToolSteps([]);
        } finally {
            setSendingChat(false);
            chatInputRef.current?.focus();
        }
    };

    // ── Advance to the next section within the lesson ────────────────
    // Sends the [ABSCHNITT_WEITER] control message; the teacher then explains
    // the next section. When already on the last section this is not shown.
    const handleNextSection = async () => {
        if (view.kind !== 'lesson-chat' || sendingChat) return;
        setSendingChat(true);
        setStreamingThought('');
        setQuizSuggested(false);
        setToolSteps([]);
        userSentMessageRef.current = true;
        try {
            let fullContent = '';
            const noteProposals: CourseNoteResult[] = [];
            const response = await sendTeacherChatStream(view.course.id, view.unit.id, '[ABSCHNITT_WEITER]', (event) => {
                if (event.type === 'thinking') {
                    setStreamingThought((prev) => prev + event.content);
                } else if (event.type === 'chunk') {
                    // Accumulate only — the answer is rendered formatted once complete.
                    fullContent += event.content;
                } else if (event.type === 'tool_call') {
                    setToolSteps((prev) => [...prev, event.content]);
                } else if (event.type === 'note_proposal') {
                    noteProposals.push({
                        title: event.note.title,
                        content: event.note.content,
                        folder: `Kurse/${view.course.title}`,
                        tag_ids: [],
                        tag_names: event.note.tags || [],
                    });
                }
            });
            setStreamingThought('');
            setToolSteps([]);
            setMessages((prev) => [...prev, response.message]);
            setSection({ current: response.current_section, total: response.total_sections });
            setQuizSuggested(!!response.quiz_suggested);
            if (noteProposals.length > 0) setProposedNotes(noteProposals);
        } catch {
            setError('Fehler beim Laden des nächsten Abschnitts.');
            setStreamingThought('');
            setToolSteps([]);
        } finally {
            setSendingChat(false);
        }
    };

    // ── Has the current context already produced notes? ──────────────
    // True when a note_generated marker exists and no new content
    // came after it. New content = a real student message OR a section
    // advance ([ABSCHNITT_WEITER]), since a new section brings new material
    // worth taking notes on. [START]/[NOTIZEN_ERSTELLT] don't count.
    const notesGeneratedForContext = (() => {
        let lastMarker = -1;
        let lastContent = -1;
        messages.forEach((m, i) => {
            if (m.role === 'note_generated') lastMarker = i;
            if (m.role === 'user' && (!isControlMessage(m.content) || m.content === '[ABSCHNITT_WEITER]')) lastContent = i;
        });
        return lastMarker >= 0 && lastMarker > lastContent;
    })();

    // ── Record that notes were generated for the current unit ────────
    const markNotesGenerated = (course: CourseDetail, unit: CourseUnit, noteTitles: string[]) => {
        // Optimistic local marker so the indicator shows and buttons disable instantly
        setMessages((prev) => [
            ...prev,
            {
                id: `notegen-${Date.now()}`,
                role: 'note_generated',
                content: `Notizen generiert: ${noteTitles.join(', ')}`,
                metadata: null,
                created_at: new Date().toISOString(),
            },
        ]);
        userSentMessageRef.current = false;
        recordNotesGenerated(course.id, unit.id, noteTitles).catch(() => { });
    };

    // ── "Notizen prüfen" → generate notes and open preview ───────────
    const handlePreviewNotes = async () => {
        if (view.kind !== 'lesson-chat' || generatingNotes || notesGeneratedForContext) return;
        setGeneratingNotes(true);
        setError(null);
        try {
            const unitId = view.unit.id;
            const cached = !userSentMessageRef.current ? prefetchedNotesRef.current.get(unitId) : undefined;
            const notes = cached || await generateLessonNotes(view.course.id, unitId);
            prefetchedNotesRef.current.delete(unitId);
            if (notes.length > 0) {
                markNotesGenerated(view.course, view.unit, notes.map((n) => n.title));
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

    // ── "Notizen direkt speichern" → generate and save without preview ─
    const handleGenerateAndSaveNotes = async () => {
        if (view.kind !== 'lesson-chat' || generatingNotes || notesGeneratedForContext) return;
        setGeneratingNotes(true);
        setError(null);
        try {
            const unitId = view.unit.id;
            const cached = !userSentMessageRef.current ? prefetchedNotesRef.current.get(unitId) : undefined;
            const notes = cached || await generateLessonNotes(view.course.id, unitId);
            prefetchedNotesRef.current.delete(unitId);
            if (notes.length === 0) {
                setError('Keine Notizen generiert. Versuche es nach mehr Konversation erneut.');
                return;
            }
            // Save every note directly
            for (const note of notes) {
                const folder = await ensureFolderPath(note.folder);
                await createNote(note.title, note.content, folder.id, note.tag_ids);
            }
            loadFolderTree();  // fire-and-forget
            markNotesGenerated(view.course, view.unit, notes.map((n) => n.title));
        } catch {
            setError('Fehler beim Speichern der Notizen.');
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
        setMessages([]);
        setView({ kind: 'lesson-chat', course, unit });
        try {
            const msgs = await getUnitMessages(course.id, unit.id);
            setMessages(msgs);
            // Restore section state from the (possibly updated) unit
            const fresh = await getTeacherCourse(course.id);
            const freshUnit = fresh.units.find((u) => u.id === unit.id);
            if (freshUnit) {
                setSection({
                    current: freshUnit.current_section || 0,
                    total: freshUnit.sections?.length || 0,
                });
            }
        } catch {
            setError('Fehler beim Laden des Chats.');
        }
    };

    // ── Start quiz ───────────────────────────────────────────────────
    const handleStartQuiz = async () => {
        if (view.kind !== 'lesson-chat' || generatingQuiz) return;
        setQuizSuggested(false);
        setGeneratingQuiz(true);
        setError(null);
        try {
            const questions = await generateUnitQuiz(view.course.id, view.unit.id);
            if (questions.length > 0) {
                setView({ kind: 'quiz', course: view.course, unit: view.unit, questions });
            } else {
                setError('Konnte kein Quiz generieren. Versuche es nach etwas mehr Konversation erneut.');
            }
        } catch {
            setError('Fehler beim Generieren des Quiz.');
        } finally {
            setGeneratingQuiz(false);
        }
    };

    // ── Complete unit → show celebration with recap ──────────────────
    const handleCompleteUnit = async () => {
        if (view.kind !== 'lesson-chat') return;
        setError(null);

        const currentCourse = view.course;
        const currentUnit = view.unit;

        // Mark complete in background — don't block the celebration
        updateCourseUnit(currentCourse.id, currentUnit.id, { status: 'completed' }).catch(() => { });

        // Show celebration immediately, load recap in background
        setRecap(null);
        setLoadingRecap(true);
        setView({ kind: 'lesson-complete', course: currentCourse, unit: currentUnit });
        generateUnitRecap(currentCourse.id, currentUnit.id)
            .then((r) => setRecap(r))
            .catch(() => setRecap(null))
            .finally(() => setLoadingRecap(false));
    };

    // ── Advance to next unit after the celebration screen ────────────
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

    // ── Get current unit progress info ───────────────────────────────
    const getUnitProgress = (course: CourseDetail, currentUnit: CourseUnit) => {
        const enabled = course.units.filter((u) => u.enabled);
        const currentIndex = enabled.findIndex((u) => u.id === currentUnit.id);
        return { current: currentIndex + 1, total: enabled.length };
    };

    // ── Is this the last enabled unit awaiting completion? ───────────
    const isLastEnabledUnit = (course: CourseDetail, currentUnit: CourseUnit) => {
        const sorted = [...course.units].sort((a, b) => a.order_index - b.order_index);
        const curIdx = sorted.findIndex(u => u.id === currentUnit.id);
        return !sorted.slice(curIdx + 1).some(
            u => u.enabled && (u.status === 'pending' || u.status === 'active')
        );
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
                <div className="max-w-lg mx-auto space-y-2.5">
                    {/* Topic */}
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

                    {/* Description / deepening */}
                    <textarea
                        value={descriptionInput}
                        onChange={(e) => setDescriptionInput(e.target.value)}
                        placeholder="Beschreibung & Vertiefung (optional) — worauf legst du besonderen Wert? z.B. 'Fokus auf Beweise und praktische Beispiele, weniger Geschichte'"
                        rows={2}
                        className="w-full px-4 py-2.5 bg-dark-800 border border-dark-700 rounded-xl text-white text-sm placeholder-dark-600 focus:outline-none focus:border-teal-500 resize-none"
                    />

                    {/* Lesson count */}
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
        const hasSections = section.total > 0;
        const onLastSection = !hasSections || section.current >= section.total - 1;
        const currentSectionTitle =
            hasSections && unit.sections && unit.sections[section.current]
                ? unit.sections[section.current].title
                : null;

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
                                {/* Section sub-status: where in the lesson we are */}
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
                    {/* Section progress dots — tangible sense of progress within the lesson */}
                    {hasSections ? (
                        <div className="mt-2 flex items-center gap-1">
                            {Array.from({ length: section.total }).map((_, i) => (
                                <div
                                    key={i}
                                    className={`h-1.5 flex-1 rounded-full transition-colors ${i < section.current
                                        ? 'bg-teal-500'
                                        : i === section.current
                                            ? 'bg-teal-400'
                                            : 'bg-dark-800'
                                        }`}
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

                {/* Learning path overlay */}
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
                    {/* Lesson objectives — visible at a glance without reading prose */}
                    <LessonObjectivesCard unit={unit} accent="teal" />
                    {messages.filter(m => m.role !== 'user' || !isControlMessage(m.content)).map((msg, idx, arr) => {
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
                                        className={`max-w-[85%] sm:max-w-[78%] px-4 py-3 rounded-2xl text-sm ${msg.role === 'user'
                                            ? 'bg-teal-600 text-white rounded-br-md'
                                            : 'bg-dark-900 border border-dark-700 text-dark-100 rounded-bl-md'
                                            }`}
                                    >
                                        {msg.role === 'assistant' ? (
                                            (() => {
                                                const { cleanContent, requests } = extractNoteRequests(msg.content);
                                                return (
                                                    <>
                                                        <div className="markdown-content lesson-prose">
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
                            <div className="bg-dark-800 border border-dark-700 rounded-2xl rounded-bl-md px-4 py-3 max-w-[85%] space-y-2">
                                {/* Live tool steps — the tutor acting autonomously */}
                                {toolSteps.length > 0 && (
                                    <div className="flex flex-wrap gap-1.5">
                                        {toolSteps.map((step, i) => (
                                            <span key={i} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-teal-500/10 text-teal-300 border border-teal-500/20">
                                                ⚙ {step}
                                            </span>
                                        ))}
                                    </div>
                                )}
                                {/* No live text streaming — the answer is unformatted while
                                    streaming and just renders as one block once complete. */}
                                <div className="flex items-center gap-2 text-xs text-dark-500">
                                    <div className="flex gap-0.5">
                                        <div className="w-1.5 h-1.5 bg-teal-400 rounded-full animate-pulse" />
                                        <div className="w-1.5 h-1.5 bg-teal-400 rounded-full animate-pulse" style={{ animationDelay: '0.15s' }} />
                                        <div className="w-1.5 h-1.5 bg-teal-400 rounded-full animate-pulse" style={{ animationDelay: '0.3s' }} />
                                    </div>
                                    <span>{toolSteps.length > 0 ? 'Arbeitet...' : 'Formuliert Erklärung...'}</span>
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

                {/* Notes the tutor proposed on its own — offer to review & save */}
                {proposedNotes.length > 0 && !sendingChat && view.kind === 'lesson-chat' && (
                    <div className="mx-3 mb-1 mt-2 flex items-center gap-2 px-3 py-2 bg-green-600/15 border border-green-500/30 rounded-xl">
                        <FiCheck className="w-4 h-4 text-green-300 flex-shrink-0" />
                        <span className="text-xs text-green-200 flex-1">
                            Der Tutor schlägt {proposedNotes.length} Notiz{proposedNotes.length > 1 ? 'en' : ''} zum Speichern vor.
                        </span>
                        <button
                            onClick={() => {
                                if (view.kind !== 'lesson-chat') return;
                                setView({ kind: 'note-review', course: view.course, unit: view.unit, notes: proposedNotes, currentIdx: 0 });
                                setProposedNotes([]);
                            }}
                            className="flex items-center gap-1.5 px-3 py-1 bg-green-600 hover:bg-green-500 text-white text-xs font-medium rounded-lg transition-colors"
                        >
                            <FiCheck className="w-3.5 h-3.5" /> Ansehen & speichern
                        </button>
                        <button
                            onClick={() => setProposedNotes([])}
                            className="p-1 text-green-300/60 hover:text-green-200"
                            title="Verwerfen"
                        >
                            <FiX className="w-3.5 h-3.5" />
                        </button>
                    </div>
                )}

                {/* Quiz suggestion — the tutor decided a quick check makes sense here */}
                {quizSuggested && !sendingChat && (
                    <div className="mx-3 mb-1 mt-2 flex items-center gap-2 px-3 py-2 bg-purple-600/15 border border-purple-500/30 rounded-xl">
                        <LuListChecks className="w-4 h-4 text-purple-300 flex-shrink-0" />
                        <span className="text-xs text-purple-200 flex-1">
                            Wie wär's mit einem kurzen Quiz, um das eben Gelernte zu festigen?
                        </span>
                        <button
                            onClick={handleStartQuiz}
                            disabled={generatingQuiz}
                            className="flex items-center gap-1.5 px-3 py-1 bg-purple-600 hover:bg-purple-500 text-white text-xs font-medium rounded-lg transition-colors disabled:opacity-50"
                        >
                            {generatingQuiz ? (
                                <div className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />
                            ) : (
                                <LuListChecks className="w-3.5 h-3.5" />
                            )}
                            Quiz starten
                        </button>
                        <button
                            onClick={() => setQuizSuggested(false)}
                            className="p-1 text-purple-300/60 hover:text-purple-200"
                            title="Später"
                        >
                            <FiX className="w-3.5 h-3.5" />
                        </button>
                    </div>
                )}

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
                    <div className="flex flex-wrap gap-2 mt-2">
                        <button
                            onClick={handlePreviewNotes}
                            disabled={generatingNotes || sendingChat || messages.length < 2 || notesGeneratedForContext}
                            title={notesGeneratedForContext ? 'Für diesen Stand wurden bereits Notizen erstellt. Stelle eine neue Frage, um weitere zu generieren.' : 'Notizen generieren und vor dem Speichern ansehen'}
                            className="flex items-center gap-1.5 px-3 py-1.5 bg-green-600/20 text-green-400 hover:bg-green-600/30 text-xs font-medium rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                        >
                            {generatingNotes ? (
                                <div className="w-3 h-3 border-2 border-green-400 border-t-transparent rounded-full animate-spin" />
                            ) : (
                                <FiCheck className="w-3.5 h-3.5" />
                            )}
                            Notizen prüfen & speichern
                        </button>
                        <button
                            onClick={handleGenerateAndSaveNotes}
                            disabled={generatingNotes || sendingChat || messages.length < 2 || notesGeneratedForContext}
                            title={notesGeneratedForContext ? 'Für diesen Stand wurden bereits Notizen erstellt. Stelle eine neue Frage, um weitere zu generieren.' : 'Notizen generieren und sofort ohne Vorschau speichern'}
                            className="flex items-center gap-1.5 px-3 py-1.5 bg-green-600/10 text-green-400 hover:bg-green-600/20 text-xs font-medium rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                        >
                            {generatingNotes ? (
                                <div className="w-3 h-3 border-2 border-green-400 border-t-transparent rounded-full animate-spin" />
                            ) : (
                                <FiZap className="w-3.5 h-3.5" />
                            )}
                            Direkt speichern
                        </button>
                        <button
                            onClick={handleStartQuiz}
                            disabled={generatingQuiz || sendingChat || messages.length < 2}
                            title="Kurzes Quiz zur aktuellen Lektion"
                            className="flex items-center gap-1.5 px-3 py-1.5 bg-purple-600/20 text-purple-300 hover:bg-purple-600/30 text-xs font-medium rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                        >
                            {generatingQuiz ? (
                                <div className="w-3 h-3 border-2 border-purple-300 border-t-transparent rounded-full animate-spin" />
                            ) : (
                                <LuListChecks className="w-3.5 h-3.5" />
                            )}
                            Quiz
                        </button>
                        {/* Section navigation: walk through the lesson, recap only at the end */}
                        {!onLastSection ? (
                            <button
                                onClick={handleNextSection}
                                disabled={sendingChat || messages.length < 2}
                                title="Zum nächsten Abschnitt dieser Lektion"
                                className="flex items-center gap-1.5 px-3 py-1.5 bg-teal-600 hover:bg-teal-500 text-white text-xs font-medium rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                            >
                                <FiChevronRight className="w-3.5 h-3.5" />
                                Weiter
                            </button>
                        ) : (
                            <button
                                onClick={handleCompleteUnit}
                                disabled={sendingChat || messages.length < 2}
                                title="Lektion abschließen"
                                className="flex items-center gap-1.5 px-3 py-1.5 bg-teal-600/20 text-teal-400 hover:bg-teal-600/30 text-xs font-medium rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                            >
                                <FiCheck className="w-3.5 h-3.5" />
                                Lektion abschließen
                            </button>
                        )}
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

                    {/* Shared deepening options — applied to whichever topic you pick below */}
                    <div className="bg-dark-800/50 border border-dark-700 rounded-xl p-4 mb-3 space-y-2.5">
                        <p className="text-xs text-dark-400 font-medium">Optionen für die Vertiefung</p>
                        <p className="text-[11px] text-dark-600 -mt-1">
                            Diese Einstellungen gelten für das Thema, das du unten auswählst oder eingibst.
                        </p>
                        <textarea
                            value={focusDescriptionInput}
                            onChange={(e) => setFocusDescriptionInput(e.target.value)}
                            placeholder="Beschreibung & Vertiefung (optional) — worauf legst du besonderen Wert? z.B. 'Mehr Beweise, konkrete Anwendungsbeispiele'"
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

                    {/* Custom topic — primary path with its own clear action button */}
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

                    {/* AI suggestions — pick one to generate with the options above */}
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
                {view.kind === 'quiz' && (
                    <LessonQuiz
                        questions={view.questions}
                        accent="teal"
                        onClose={() => returnToChat(view.course, view.unit)}
                    />
                )}
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
