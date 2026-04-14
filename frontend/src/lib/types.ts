export interface User {
  id: string;
  email: string;
  created_at: string;
}

export interface Folder {
  id: string;
  name: string;
  path: string;
  parent_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface FolderTree {
  id: string;
  name: string;
  path: string;
  parent_id: string | null;
  children: FolderTree[];
  notes: NoteListItem[];
}

export interface NoteListItem {
  id: string;
  title: string;
  folder_id: string;
  created_at: string;
  updated_at: string;
}

export interface Note {
  id: string;
  title: string;
  content: string;
  folder_id: string;
  folder_path?: string;
  created_at: string;
  updated_at: string;
}

export interface ChatSession {
  id: string;
  title: string;
  session_type: 'notes' | 'qa';
  created_at: string;
  updated_at: string;
}

export interface ChatMessage {
  id: string;
  session_id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
}

export interface ChatSessionDetail extends ChatSession {
  messages: ChatMessage[];
}

export interface AIEditResponse {
  original_content: string;
  suggested_content: string;
}

export interface UserSettings {
  note_prompt: string | null;
  qa_prompt: string | null;
  edit_prompt: string | null;
  note_prompt_default: string;
  qa_prompt_default: string;
  edit_prompt_default: string;
}
