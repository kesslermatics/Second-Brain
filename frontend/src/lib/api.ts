import axios from 'axios';
import type {
  User, Folder, FolderTree, Note, NoteListItem,
  ChatSession, ChatSessionDetail, ChatMessage, AIEditResponse,
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

export const createNote = async (title: string, content: string, folderId: string) => {
  const { data } = await api.post<Note>('/notes/', { title, content, folder_id: folderId });
  return data;
};

export const updateNote = async (noteId: string, updates: { title?: string; content?: string; folder_id?: string }) => {
  const { data } = await api.put<Note>(`/notes/${noteId}`, updates);
  return data;
};

export const deleteNote = async (noteId: string) => {
  await api.delete(`/notes/${noteId}`);
};

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

export default api;
