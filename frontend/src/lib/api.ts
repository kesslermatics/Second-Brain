import axios from 'axios';
import type {
  User, Folder, FolderTree, Note, NoteListItem,
  ChatSession, ChatSessionDetail, ChatMessage, AIEditResponse, UserSettings,
  Tag, TagSuggestResponse, SearchResponse, NoteVersion, NoteLink, GraphData,
  FlashCard, SRSettings, ReviewSession, DashboardData, SummaryRequest, SummaryResponse,
  ExportRequest, ImageItem, ImageListResponse,
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

export default api;
