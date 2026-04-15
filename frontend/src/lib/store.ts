import { create } from 'zustand';
import type { User, FolderTree, Note, ChatSession, ChatSessionDetail } from './types';
import * as api from './api';

interface AppState {
  // Auth
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
  setUser: (user: User | null) => void;
  setToken: (token: string | null) => void;
  logout: () => void;

  // Folders
  folderTree: FolderTree[];
  loadFolderTree: () => Promise<void>;

  // Notes
  selectedNote: Note | null;
  setSelectedNote: (note: Note | null) => void;
  loadNote: (noteId: string) => Promise<void>;
  pendingEdit: boolean;
  setPendingEdit: (pending: boolean) => void;

  // Chat
  notesSessions: ChatSession[];
  qaSessions: ChatSession[];
  activeNotesSession: ChatSessionDetail | null;
  activeQASession: ChatSessionDetail | null;
  loadNotesSessions: () => Promise<void>;
  loadQASessions: () => Promise<void>;
  setActiveNotesSession: (session: ChatSessionDetail | null) => void;
  setActiveQASession: (session: ChatSessionDetail | null) => void;

  // UI
  activeView: 'chat' | 'notes' | 'dashboard' | 'graph' | 'learn' | 'search' | 'export' | 'summary' | 'images' | 'books';
  setActiveView: (view: 'chat' | 'notes' | 'dashboard' | 'graph' | 'learn' | 'search' | 'export' | 'summary' | 'images' | 'books') => void;
  sidebarOpen: boolean;
  setSidebarOpen: (open: boolean) => void;
}

export const useStore = create<AppState>((set, get) => ({
  // Auth
  user: null,
  token: typeof window !== 'undefined' ? localStorage.getItem('brain_token') : null,
  isAuthenticated: false,
  setUser: (user) => set({ user, isAuthenticated: !!user }),
  setToken: (token) => {
    if (token) {
      localStorage.setItem('brain_token', token);
    } else {
      localStorage.removeItem('brain_token');
    }
    set({ token });
  },
  logout: () => {
    localStorage.removeItem('brain_token');
    set({ user: null, token: null, isAuthenticated: false });
  },

  // Folders
  folderTree: [],
  loadFolderTree: async () => {
    try {
      const tree = await api.getFolderTree();
      set({ folderTree: tree });
    } catch (e) {
      console.error('Failed to load folder tree:', e);
    }
  },

  // Notes
  selectedNote: null,
  setSelectedNote: (note) => set({ selectedNote: note }),
  loadNote: async (noteId: string) => {
    try {
      const note = await api.getNote(noteId);
      set({ selectedNote: note });
    } catch (e) {
      console.error('Failed to load note:', e);
    }
  },
  pendingEdit: false,
  setPendingEdit: (pending) => set({ pendingEdit: pending }),

  // Chat
  notesSessions: [],
  qaSessions: [],
  activeNotesSession: null,
  activeQASession: null,
  loadNotesSessions: async () => {
    try {
      const sessions = await api.getChatSessions('notes');
      set({ notesSessions: sessions });
    } catch (e) {
      console.error('Failed to load notes sessions:', e);
    }
  },
  loadQASessions: async () => {
    try {
      const sessions = await api.getChatSessions('qa');
      set({ qaSessions: sessions });
    } catch (e) {
      console.error('Failed to load QA sessions:', e);
    }
  },
  setActiveNotesSession: (session) => set({ activeNotesSession: session }),
  setActiveQASession: (session) => set({ activeQASession: session }),

  // UI
  activeView: 'chat',
  setActiveView: (view) => set({ activeView: view }),
  sidebarOpen: true,
  setSidebarOpen: (open) => set({ sidebarOpen: open }),
}));
