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

  // Agent left panel
  agentViewingNote: Note | null;
  setAgentViewingNote: (note: Note | null) => void;

  // Chat
  notesSessions: ChatSession[];
  qaSessions: ChatSession[];
  agentSessions: ChatSession[];
  activeNotesSession: ChatSessionDetail | null;
  activeQASession: ChatSessionDetail | null;
  activeAgentSession: ChatSessionDetail | null;
  loadNotesSessions: () => Promise<void>;
  loadQASessions: () => Promise<void>;
  loadAgentSessions: () => Promise<void>;
  setActiveNotesSession: (session: ChatSessionDetail | null) => void;
  setActiveQASession: (session: ChatSessionDetail | null) => void;
  setActiveAgentSession: (session: ChatSessionDetail | null) => void;

  // UI
  activeView: 'chat' | 'notes' | 'dashboard' | 'graph' | 'learn' | 'search' | 'export' | 'summary' | 'images' | 'books' | 'teacher' | 'agent';
  setActiveView: (view: 'chat' | 'notes' | 'dashboard' | 'graph' | 'learn' | 'search' | 'export' | 'summary' | 'images' | 'books' | 'teacher' | 'agent') => void;
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

  // Agent left panel
  agentViewingNote: null,
  setAgentViewingNote: (note) => set({ agentViewingNote: note }),

  // Chat
  notesSessions: [],
  qaSessions: [],
  agentSessions: [],
  activeNotesSession: null,
  activeQASession: null,
  activeAgentSession: null,
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
  loadAgentSessions: async () => {
    try {
      const sessions = await api.getChatSessions('agent');
      set({ agentSessions: sessions });
    } catch (e) {
      console.error('Failed to load agent sessions:', e);
    }
  },
  setActiveNotesSession: (session) => set({ activeNotesSession: session }),
  setActiveQASession: (session) => set({ activeQASession: session }),
  setActiveAgentSession: (session) => set({ activeAgentSession: session }),

  // UI
  activeView: 'agent',
  setActiveView: (view) => set({ activeView: view }),
  sidebarOpen: typeof window !== 'undefined' ? window.innerWidth >= 1024 : true,
  setSidebarOpen: (open) => set({ sidebarOpen: open }),
}));
