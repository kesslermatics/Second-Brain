import axios from 'axios';
import type {
  User, Folder, FolderTree, Note, NoteListItem,
  ChatSession, ChatSessionDetail, ChatMessage, AIEditResponse, UserSettings,
  Tag, TagSuggestResponse, SearchResponse, NoteVersion, NoteLink, GraphData,
  FlashCard, SRSettings, ReviewSession, DashboardData, SummaryRequest, SummaryResponse,
  ExportRequest, ImageItem, ImageListResponse,
  BookSearchResult, BookTocResult, BookChapter, BookChapterNoteResult,
  CourseListItem, CourseDetail, CourseMessage as CourseMsg, CourseNoteResult, AdvancedFocusSuggestion,
  BookSummariesResponse, QuizQuestion, LessonRecap, TeacherChatResponse,
  AgentRunResult, AgentStep, AgentProposal,
} from './types';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const api = axios.create({
  baseURL: `${API_URL}/api`,
  headers: { 'Content-Type': 'application/json' },
});

api.interceptors.request.use((config) => {
  if (typeof window !== 'undefined') {
    const token = localStorage.getItem('brain_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401 && typeof window !== 'undefined') {
      localStorage.removeItem('brain_token');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

// Auth
export const login = async (email: string, password: string) => {
  const { data } = await api.post<{ access_token: string; token_type: string }>('/auth/login', { email, password });
  return data;
};

export const getMe = async () => {
  const { data } = await api.get<User>('/auth/me');
  return data;
};

// Folders
export const getFolders = async () => {
  const { data } = await api.get<Folder[]>('/folders/');
  return data;
};

export const getFolderTree = async () => {
  const { data } = await api.get<FolderTree[]>('/folders/tree');
  return data;
};

export const createFolder = async (name: string, parentId?: string) => {
  const { data } = await api.post<Folder>('/folders/', { name, parent_id: parentId || null });
  return data;
};

export const ensureFolderPath = async (path: string) => {
  const { data } = await api.post<Folder>('/folders/ensure-path', { path });
  return data;
};

export const deleteFolder = async (folderId: string) => {
  await api.delete(`/folders/${folderId}`);
};

export const moveFolder = async (folderId: string, newParentId: string | null) => {
  const { data } = await api.put<Folder>(`/folders/${folderId}`, { parent_id: newParentId });
  return data;
};

export const renameFolder = async (folderId: string, name: string) => {
  const { data } = await api.put<Folder>(`/folders/${folderId}`, { name });
  return data;
};

// Notes
export const getNotes = async (folderId?: string) => {
  const params = folderId ? { folder_id: folderId } : {};
  const { data } = await api.get<NoteListItem[]>('/notes/', { params });
  return data;
};

export const getNote = async (noteId: string) => {
  const { data } = await api.get<Note>(`/notes/${noteId}`);
  return data;
};

export const createNote = async (title: string, content: string, folderId: string, tagIds?: string[], noteType?: string) => {
  const { data } = await api.post<Note>('/notes/', { title, content, folder_id: folderId, tag_ids: tagIds, note_type: noteType || 'text' });
  return data;
};

export const updateNote = async (noteId: string, updates: { title?: string; content?: string; folder_id?: string; tag_ids?: string[]; note_type?: string }) => {
  const { data } = await api.put<Note>(`/notes/${noteId}`, updates);
  return data;
};

export const deleteNote = async (noteId: string) => {
  await api.delete(`/notes/${noteId}`);
};

// File Uploads
export const uploadFile = async (file: File) => {
  const formData = new FormData();
  formData.append('file', file);
  const { data } = await api.post<{ url: string; filename: string; size: number; content_type: string }>(
    '/uploads/',
    formData,
    { headers: { 'Content-Type': 'multipart/form-data' } }
  );
  return data;
};

export const uploadPastedImage = async (file: File) => {
  const formData = new FormData();
  formData.append('file', file);
  const { data } = await api.post<{ url: string; filename: string; size: number; content_type: string }>(
    '/uploads/paste',
    formData,
    { headers: { 'Content-Type': 'multipart/form-data' } }
  );
  return data;
};

// Tags
export const getTags = async () => {
  const { data } = await api.get<Tag[]>('/tags');
  return data;
};

export const createTag = async (name: string, color?: string) => {
  const { data } = await api.post<Tag>('/tags', { name, color });
  return data;
};

export const deleteTag = async (tagId: string) => {
  await api.delete(`/tags/${tagId}`);
};

export const suggestTags = async (title: string, content: string) => {
  const { data } = await api.post<TagSuggestResponse>('/tags/suggest', { title, content });
  return data;
};

// Search
export const searchNotes = async (query: string, limit?: number) => {
  const params: Record<string, string | number> = { q: query };
  if (limit) params.limit = limit;
  const { data } = await api.get<SearchResponse>('/search', { params });
  return data;
};

// Note Versions
export const getNoteVersions = async (noteId: string) => {
  const { data } = await api.get<NoteVersion[]>(`/notes/${noteId}/versions`);
  return data;
};

export const getNoteVersion = async (noteId: string, versionId: string) => {
  const { data } = await api.get<NoteVersion>(`/notes/${noteId}/versions/${versionId}`);
  return data;
};

export const restoreNoteVersion = async (noteId: string, versionId: string) => {
  const { data } = await api.post<Note>(`/notes/${noteId}/versions/${versionId}/restore`);
  return data;
};

// Note Links
export const getNoteLinks = async (noteId: string) => {
  const { data } = await api.get<NoteLink[]>(`/links/note/${noteId}`);
  return data;
};

export const createNoteLink = async (noteId: string, targetNoteId: string, linkType?: string) => {
  const { data } = await api.post<NoteLink>(`/links/note/${noteId}`, { target_note_id: targetNoteId, link_type: linkType || 'related' });
  return data;
};

export const deleteNoteLink = async (linkId: string) => {
  await api.delete(`/links/${linkId}`);
};

export const autoLinkNote = async (noteId: string) => {
  const { data } = await api.post<NoteLink[]>(`/links/note/${noteId}/auto-link`);
  return data;
};

export const getGraphData = async () => {
  const { data } = await api.get<GraphData>('/links/graph');
  return data;
};

// Spaced Repetition
export const getSRSettings = async () => {
  const { data } = await api.get<SRSettings>('/sr/settings');
  return data;
};

export const updateSRSettings = async (settings: Partial<SRSettings>) => {
  const { data } = await api.put<SRSettings>('/sr/settings', settings);
  return data;
};

export const generateFlashcards = async (noteId: string) => {
  const { data } = await api.post<FlashCard[]>(`/sr/generate/${noteId}`);
  return data;
};

export const generateFolderFlashcards = async (folderId: string) => {
  const { data } = await api.post<FlashCard[]>(`/sr/generate-folder/${folderId}`);
  return data;
};

export const getReviewSession = async () => {
  const { data } = await api.get<ReviewSession>('/sr/review');
  return data;
};

export const submitReview = async (cardId: string, quality: number) => {
  const { data } = await api.post<FlashCard>('/sr/review', { card_id: cardId, quality });
  return data;
};

export const getAllFlashcards = async () => {
  const { data } = await api.get<FlashCard[]>('/sr/cards');
  return data;
};

export const deleteFlashcard = async (cardId: string) => {
  await api.delete(`/sr/cards/${cardId}`);
};

// Dashboard
export const getDashboard = async () => {
  const { data } = await api.get<DashboardData>('/dashboard');
  return data;
};

// Export
export const exportNotes = async (request: ExportRequest) => {
  const response = await api.post('/export', request, { responseType: 'blob' });
  const url = window.URL.createObjectURL(new Blob([response.data]));
  const link = document.createElement('a');
  link.href = url;
  link.setAttribute('download', 'brain_export.zip');
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
};

// Summary
export const generateSummary = async (request: SummaryRequest) => {
  const { data } = await api.post<SummaryResponse>('/summary', request);
  return data;
};

// Streaming Chat
export const getStreamingUrl = () => `${API_URL}/api`;

// Chat
export const getChatSessions = async (sessionType?: string) => {
  const params = sessionType ? { session_type: sessionType } : {};
  const { data } = await api.get<ChatSession[]>('/chat/sessions', { params });
  return data;
};

export const createChatSession = async (sessionType: string, title?: string) => {
  const { data } = await api.post<ChatSession>('/chat/sessions', { session_type: sessionType, title });
  return data;
};

export const getChatSession = async (sessionId: string) => {
  const { data } = await api.get<ChatSessionDetail>(`/chat/sessions/${sessionId}`);
  return data;
};

export const deleteChatSession = async (sessionId: string) => {
  await api.delete(`/chat/sessions/${sessionId}`);
};

export const updateChatSession = async (sessionId: string, title: string) => {
  const { data } = await api.put<ChatSession>(`/chat/sessions/${sessionId}`, { title });
  return data;
};

export const sendChatMessage = async (sessionId: string, content: string) => {
  const { data } = await api.post<ChatMessage>(`/chat/sessions/${sessionId}/messages`, { content });
  return data;
};

// AI
export const aiEditNote = async (noteId: string, instruction: string) => {
  const { data } = await api.post<AIEditResponse>('/ai/edit-note', { note_id: noteId, instruction });
  return data;
};

// Settings
export const getSettings = async () => {
  const { data } = await api.get<UserSettings>('/settings');
  return data;
};

export const updateSettings = async (settings: { note_prompt?: string | null; qa_prompt?: string | null; edit_prompt?: string | null }) => {
  const { data } = await api.put<UserSettings>('/settings', settings);
  return data;
};

export const resetSettings = async () => {
  const { data } = await api.post<UserSettings>('/settings/reset');
  return data;
};

// Images
export const getImages = async (folderId?: string, noteId?: string) => {
  const params: Record<string, string> = {};
  if (folderId) params.folder_id = folderId;
  if (noteId) params.note_id = noteId;
  const { data } = await api.get<ImageListResponse>('/images/', { params });
  return data;
};

export const getImage = async (imageId: string) => {
  const { data } = await api.get<ImageItem>(`/images/${imageId}`);
  return data;
};

export const uploadImage = async (file: File, folderId?: string, noteId?: string) => {
  const formData = new FormData();
  formData.append('file', file);
  const params: Record<string, string> = {};
  if (folderId) params.folder_id = folderId;
  if (noteId) params.note_id = noteId;
  const { data } = await api.post<ImageItem>(
    '/images/upload',
    formData,
    { headers: { 'Content-Type': 'multipart/form-data' }, params }
  );
  return data;
};

export const reanalyzeImage = async (imageId: string) => {
  const { data } = await api.post<ImageItem>(`/images/${imageId}/reanalyze`);
  return data;
};

export const deleteImage = async (imageId: string) => {
  await api.delete(`/images/${imageId}`);
};

// Books
export const searchBook = async (query: string) => {
  const { data } = await api.post<BookSearchResult>('/books/search', { query });
  return data;
};

export const getBookToc = async (title: string, authors: string[]) => {
  const { data } = await api.post<BookTocResult>('/books/toc', { title, authors });
  return data;
};

export const generateChapterNote = async (bookTitle: string, authors: string[], chapter: BookChapter) => {
  const { data } = await api.post<BookChapterNoteResult>('/books/generate-chapter-note', {
    book_title: bookTitle,
    authors,
    chapter,
  });
  return data;
};

export const generateTopicNote = async (bookTitle: string, authors: string[], topic: string) => {
  const { data } = await api.post<BookChapterNoteResult>('/books/generate-topic-note', {
    book_title: bookTitle,
    authors,
    topic,
  });
  return data;
};

export const aiEditBookContent = async (content: string, instruction: string) => {
  const { data } = await api.post<{ suggested_content: string }>('/books/ai-edit-content', {
    content,
    instruction,
  });
  return data;
};

// User State (cross-device key-value persistence)
export const getUserState = async (key: string): Promise<string | null> => {
  const { data } = await api.get<{ key: string; value: string | null }>(`/state/${encodeURIComponent(key)}`);
  return data.value;
};

export const putUserState = async (key: string, value: string): Promise<void> => {
  await api.put(`/state/${encodeURIComponent(key)}`, { value });
};

export const deleteUserState = async (key: string): Promise<void> => {
  await api.delete(`/state/${encodeURIComponent(key)}`);
};

// ── Infinite Teacher ─────────────────────────────────────────────────

export const getTeacherCourses = async () => {
  const { data } = await api.get<CourseListItem[]>('/teacher/courses', { params: { kind: 'teacher' } });
  return data;
};

export const getTeacherCourse = async (courseId: string) => {
  const { data } = await api.get<CourseDetail>(`/teacher/courses/${courseId}`);
  return data;
};

export const deleteTeacherCourse = async (courseId: string) => {
  await api.delete(`/teacher/courses/${courseId}`);
};

export const generateCurriculum = async (
  topic: string,
  parentCourseId?: string,
  customFocus?: string,
  opts?: { focusDescription?: string; numLessons?: number },
) => {
  const { data } = await api.post<CourseDetail>('/teacher/generate-curriculum', {
    topic,
    parent_course_id: parentCourseId || null,
    custom_focus: customFocus || null,
    focus_description: opts?.focusDescription || null,
    num_lessons: opts?.numLessons || null,
  });
  return data;
};

export const updateCourseStatus = async (courseId: string, status: string) => {
  const { data } = await api.patch(`/teacher/courses/${courseId}/status`, { status });
  return data;
};

export const updateCourseUnit = async (courseId: string, unitId: string, updates: { enabled?: boolean; status?: string }) => {
  const { data } = await api.patch(`/teacher/courses/${courseId}/units/${unitId}`, updates);
  return data;
};

export const getUnitMessages = async (courseId: string, unitId: string) => {
  const { data } = await api.get<CourseMsg[]>(`/teacher/courses/${courseId}/units/${unitId}/messages`);
  return data;
};

export const sendTeacherChat = async (courseId: string, unitId: string, message: string) => {
  const { data } = await api.post<TeacherChatResponse>(`/teacher/courses/${courseId}/units/${unitId}/chat`, { message });
  return data;
};

export interface TeacherSavedNote {
  note_id: string;
  title: string;
  folder?: string;
  action: 'created' | 'updated';
}

export interface TeacherDiagram {
  code: string;
  caption?: string;
}

export interface TeacherUnderstanding {
  concept: string;
  status: string;
}

export type TeacherStreamEvent =
  | { type: 'thinking'; content: string }
  | { type: 'status'; content: string }
  | { type: 'status_phrases'; phrases: string[] }
  | { type: 'chunk'; content: string }
  | { type: 'quiz_suggested' }
  | { type: 'quiz_ready' }
  | { type: 'knowledge_searched'; count: number; top_title: string; top_score_pct: number; query: string }
  | { type: 'note_saved'; note: TeacherSavedNote }
  | { type: 'note_read'; note_id: string; title: string }
  | { type: 'difficulty'; level: string }
  | { type: 'understanding'; concept: string; status: string }
  | { type: 'checkpoint'; question: string }
  | { type: 'diagram'; code: string; caption?: string }
  | {
      type: 'done';
      message_id: string;
      sections: unknown[];
      current_section: number;
      total_sections: number;
      is_last_section: boolean;
      quiz_suggested?: boolean;
      saved_notes?: TeacherSavedNote[];
      diagrams?: TeacherDiagram[];
      checkpoints?: string[];
      understanding?: TeacherUnderstanding[];
    };

/**
 * Shared helper: connect to GET /api/jobs/{job_id}/events and stream events.
 * Automatically reconnects (with the last received index) when the page becomes
 * visible again or the connection drops — so tab switches and phone-app changes
 * no longer interrupt a running job.
 */
async function _streamJobEvents(
  jobId: string,
  token: string | null,
  onEvent?: (event: Record<string, unknown>) => void,
): Promise<void> {
  let fromIndex = 0;
  let done = false;

  // Explicit type annotation prevents TypeScript from narrowing to `never`
  // when the variable is assigned inside a nested function closure.
  const controllerRef: { current: AbortController | null } = { current: null };

  const connect = async (): Promise<void> => {
    controllerRef.current?.abort();
    controllerRef.current = new AbortController();

    const url = `${API_URL}/api/jobs/${jobId}/events?from=${fromIndex}`;
    let response: Response;
    try {
      response = await fetch(url, {
        signal: controllerRef.current.signal,
        headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      });
    } catch (e: unknown) {
      if ((e as Error)?.name === 'AbortError') return;
      throw e;
    }
    if (!response.ok) throw new Error(`Job stream failed: ${response.status}`);

    const reader = response.body?.getReader();
    if (!reader) throw new Error('No reader available');
    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        let result: ReadableStreamReadResult<Uint8Array>;
        try {
          result = await reader.read();
        } catch {
          break; // aborted or network error — outer loop will reconnect
        }
        if (result.done) break;

        buffer += decoder.decode(result.value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const jsonStr = line.slice(6).trim();
          if (!jsonStr) continue;
          try {
            const event = JSON.parse(jsonStr) as Record<string, unknown>;
            if (typeof event._idx === 'number') fromIndex = (event._idx as number) + 1;
            if (event.type === 'done') done = true;
            onEvent?.(event);
          } catch { /* skip malformed */ }
        }
      }
    } finally {
      reader.releaseLock();
    }
  };

  // When the page becomes visible again, abort the stalled connection so the
  // reconnect loop picks up immediately (rather than waiting for a timeout).
  const onVisibilityChange = () => {
    if (typeof document !== 'undefined' &&
        document.visibilityState === 'visible' && !done) {
      controllerRef.current?.abort();
    }
  };
  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', onVisibilityChange);
  }

  try {
    while (!done) {
      try {
        await connect();
      } catch {
        if (done) break;
      }
      if (done) break;
      // If the page is hidden, wait for it to become visible before retrying
      if (typeof document !== 'undefined' && document.visibilityState !== 'visible') {
        await new Promise<void>((resolve) => {
          const handler = () => {
            if (document.visibilityState === 'visible') {
              document.removeEventListener('visibilitychange', handler);
              resolve();
            }
          };
          document.addEventListener('visibilitychange', handler);
        });
      } else {
        await new Promise((r) => setTimeout(r, 500));
      }
    }
  } finally {
    if (typeof document !== 'undefined') {
      document.removeEventListener('visibilitychange', onVisibilityChange);
    }
    controllerRef.current?.abort();
  }
}

export const sendTeacherChatStream = async (
  courseId: string,
  unitId: string,
  message: string,
  onEvent?: (event: TeacherStreamEvent) => void,
): Promise<TeacherChatResponse> => {
  const token = typeof window !== 'undefined' ? localStorage.getItem('brain_token') : null;

  // Step 1: POST to start the background job — returns immediately with a job_id
  const startResponse = await fetch(`${API_URL}/api/teacher/courses/${courseId}/units/${unitId}/chat/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ message }),
  });
  if (!startResponse.ok) throw new Error(`Teacher stream failed: ${startResponse.status}`);
  const { job_id } = await startResponse.json();

  // Step 2: Stream events from the job
  let fullContent = '';
  let doneEvent: TeacherStreamEvent | null = null;

  await _streamJobEvents(job_id, token, (event) => {
    const e = event as unknown as TeacherStreamEvent;
    if (e.type === 'chunk') fullContent += e.content;
    if (e.type === 'done') doneEvent = e;
    onEvent?.(e);
  });

  // Return a compatible TeacherChatResponse
  const done = doneEvent as Extract<TeacherStreamEvent, { type: 'done' }> | null;
  return {
    message: {
      id: done?.message_id || `stream-${Date.now()}`,
      role: 'assistant',
      content: fullContent,
      metadata: (done && (done.diagrams?.length || done.checkpoints?.length))
        ? { diagrams: done.diagrams || [], checkpoints: done.checkpoints || [] }
        : null,
      created_at: new Date().toISOString(),
    },
    sections: (done?.sections || []) as TeacherChatResponse['sections'],
    current_section: done?.current_section ?? 0,
    total_sections: done?.total_sections ?? 0,
    is_last_section: done?.is_last_section ?? false,
    quiz_suggested: done?.quiz_suggested ?? false,
    saved_notes: done?.saved_notes ?? [],
    diagrams: done?.diagrams ?? [],
    checkpoints: done?.checkpoints ?? [],
  };
};

export const editCurriculum = async (courseId: string, instruction: string) => {
  const { data } = await api.post<CourseDetail>(`/teacher/courses/${courseId}/edit-curriculum`, { instruction });
  return data;
};

export const generateLessonNotes = async (courseId: string, unitId: string) => {
  const { data } = await api.post<{ notes: CourseNoteResult[] }>(`/teacher/courses/${courseId}/units/${unitId}/generate-notes`);
  return data.notes;
};

export const recordNotesGenerated = async (courseId: string, unitId: string, noteTitles: string[]) => {
  const { data } = await api.post<{ ok: boolean }>(`/teacher/courses/${courseId}/units/${unitId}/record-notes`, { note_titles: noteTitles });
  return data;
};

export const generateUnitQuiz = async (courseId: string, unitId: string, numQuestions?: number) => {
  const { data } = await api.post<{ questions: QuizQuestion[] }>(
    `/teacher/courses/${courseId}/units/${unitId}/quiz`,
    numQuestions ? { num_questions: numQuestions } : {},
  );
  return data.questions;
};

export const generateUnitRecap = async (courseId: string, unitId: string) => {
  const { data } = await api.post<LessonRecap>(`/teacher/courses/${courseId}/units/${unitId}/recap`);
  return data;
};

export const generateTermNote = async (courseId: string, unitId: string, term: string) => {
  const { data } = await api.post<CourseNoteResult>(`/teacher/courses/${courseId}/units/${unitId}/generate-term-note`, { term });
  return data;
};

export const generateAdvancedFocus = async (courseId: string) => {
  const { data } = await api.post<{ suggestions: AdvancedFocusSuggestion[] }>(`/teacher/courses/${courseId}/generate-focus`);
  return data.suggestions;
};

export const aiEditTeacherContent = async (content: string, instruction: string) => {
  const { data } = await api.post<{ suggested_content: string }>('/teacher/ai-edit-content', {
    content,
    instruction,
  });
  return data;
};

// ── Book Courses (interactive chapter learning) ──────────────────────

export const getBookCourses = async () => {
  const { data } = await api.get<CourseListItem[]>('/teacher/courses', { params: { kind: 'book' } });
  return data;
};

export const createBookCourse = async (
  bookInfo: { title: string; authors: string[]; description?: string; year?: number; isbn?: string; publisher?: string; cover_url?: string; category?: string },
  chapters: { chapter_number: string; title: string; level: number; enabled: boolean }[],
) => {
  const { data } = await api.post<CourseDetail>('/teacher/create-book-course', {
    title: bookInfo.title,
    authors: bookInfo.authors,
    description: bookInfo.description || '',
    year: bookInfo.year,
    isbn: bookInfo.isbn,
    publisher: bookInfo.publisher,
    cover_url: bookInfo.cover_url,
    category: bookInfo.category,
    chapters,
  });
  return data;
};

export const getCoverCandidates = async (courseId: string) => {
  const { data } = await api.get<{ candidates: string[] }>(`/teacher/courses/${courseId}/cover-candidates`);
  return data.candidates;
};

export const updateCourseCover = async (courseId: string, coverUrl: string) => {
  const { data } = await api.patch<{ ok: boolean; cover_url: string | null }>(
    `/teacher/courses/${courseId}/cover`,
    { cover_url: coverUrl },
  );
  return data;
};

export const getBookSummaries = async (courseId: string) => {
  const { data } = await api.get<BookSummariesResponse>(`/teacher/courses/${courseId}/summaries`);
  return data;
};

export const generateChapterSummary = async (courseId: string, unitId: string) => {
  const { data } = await api.post<{ unit_id: string; summary: string; summary_generated_at: string }>(
    `/teacher/courses/${courseId}/units/${unitId}/generate-summary`
  );
  return data;
};

export default api;

// ── Agentic Workspace ────────────────────────────────────────────────

export const runAgent = async (sessionId: string, content: string, autoAccept: boolean = false, files?: File[]) => {
  const formData = new FormData();
  formData.append('content', content);
  formData.append('auto_accept', String(autoAccept));
  if (files && files.length > 0) {
    for (const file of files) {
      formData.append('files', file);
    }
  }
  const { data } = await api.post<AgentRunResult>(`/agent/sessions/${sessionId}/messages`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
};

export type AgentStreamEvent =
  | { type: 'thinking'; content: string }
  | { type: 'chunk'; content: string }
  | { type: 'tool_call'; content: string }
  | { type: 'tool_result'; content: string }
  | { type: 'proposal'; proposal: AgentProposal }
  | { type: 'sources'; sources: { title: string; url: string }[] }
  | { type: 'done'; proposals: AgentProposal[]; steps: AgentStep[]; apply_result?: unknown; image_urls?: string[] };

export const runAgentStream = async (
  sessionId: string,
  content: string,
  autoAccept: boolean = false,
  files?: File[],
  onEvent?: (event: AgentStreamEvent) => void,
): Promise<void> => {
  const formData = new FormData();
  formData.append('content', content);
  formData.append('auto_accept', String(autoAccept));
  if (files && files.length > 0) {
    for (const file of files) {
      formData.append('files', file);
    }
  }

  const token = typeof window !== 'undefined' ? localStorage.getItem('brain_token') : null;

  // Step 1: POST to start the background job — returns immediately with a job_id
  const startResponse = await fetch(`${API_URL}/api/agent/sessions/${sessionId}/messages/stream`, {
    method: 'POST',
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: formData,
  });
  if (!startResponse.ok) throw new Error(`Agent stream failed: ${startResponse.status}`);
  const { job_id } = await startResponse.json();

  // Step 2: Stream events from the job — reconnects automatically on visibility change
  await _streamJobEvents(job_id, token, onEvent as (e: Record<string, unknown>) => void);
};

export const applyAgentProposals = async (proposals: unknown[]) => {
  const { data } = await api.post<{
    applied: number;
    errors: string[];
    created_notes: { note_id: string; title: string; folder_path: string }[];
    updated_notes: { note_id: string; title: string; folder_path: string }[];
    deleted_notes: string[];
  }>('/agent/apply', { proposals });
  return data;
};

export const markProposalsApplied = async (messageId: string, appliedIndices: number[]) => {
  await api.post('/agent/mark-applied', { message_id: messageId, applied_indices: appliedIndices });
};

// ── Backups ──────────────────────────────────────────────────────────

export interface BackupItem {
  id: string;
  filename: string;
  created_at: string;
  label: string;
  notes_count: number;
  folders_count: number;
  size_bytes: number;
}

export const listBackups = async (): Promise<BackupItem[]> => {
  const { data } = await api.get<{ backups: BackupItem[] }>('/backups');
  return data.backups;
};

export const createBackup = async (label?: string): Promise<BackupItem> => {
  const { data } = await api.post<BackupItem>('/backups', { label: label || 'Manuelles Backup' });
  return data;
};

export const restoreBackup = async (backupId: string) => {
  const { data } = await api.post<{ status: string; notes_count: number; folders_count: number }>(`/backups/${backupId}/restore`);
  return data;
};

export const deleteBackup = async (backupId: string) => {
  await api.delete(`/backups/${backupId}`);
};
