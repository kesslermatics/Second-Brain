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
  note_type: string;
  folder_id: string;
  created_at: string;
  updated_at: string;
}

export interface Tag {
  id: string;
  name: string;
  color: string | null;
  note_count: number;
}

export interface Note {
  id: string;
  title: string;
  content: string;
  note_type: string;
  folder_id: string;
  folder_path?: string;
  tags: Tag[];
  created_at: string;
  updated_at: string;
}

export interface NoteVersion {
  id: string;
  note_id: string;
  title: string;
  content: string;
  version_number: number;
  created_at: string;
}

export interface NoteLink {
  id: string;
  source_note_id: string;
  target_note_id: string;
  source_title?: string;
  target_title?: string;
  link_type: string;
  ai_generated: boolean;
  created_at: string;
}

export interface GraphNodeTag {
  id: string;
  name: string;
  color: string | null;
}

export interface GraphNode {
  id: string;
  title: string;
  folder_path: string;
  val: number;
  tags?: GraphNodeTag[];
}

export interface GraphEdge {
  source: string;
  target: string;
  link_type: string;
  ai_generated: boolean;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface SearchResultItem {
  note_id: string;
  title: string;
  folder_path: string;
  snippet: string;
  score: number;
  tags: string[];
}

export interface SearchResponse {
  query: string;
  results: SearchResultItem[];
  total: number;
}

export interface FlashCard {
  id: string;
  note_id: string;
  question: string;
  answer: string;
  easiness: number;
  interval: number;
  repetitions: number;
  next_review: string;
  last_review: string | null;
  note_title?: string;
}

export interface SRSettings {
  cards_per_session: number;
  min_easiness: number;
  max_new_cards_per_day: number;
}

export interface ReviewSession {
  cards: FlashCard[];
  total_due: number;
  new_today: number;
}

export interface DashboardData {
  total_notes: number;
  total_folders: number;
  total_tags: number;
  total_flashcards: number;
  total_words: number;
  notes_this_week: number;
  notes_this_month: number;
  top_folders: { name: string; count: number }[];
  top_tags: { name: string; count: number }[];
  activity_heatmap: { date: string; count: number }[];
  sr_stats: { total: number; due: number; mastered: number; learning: number };
}

export interface ExportRequest {
  folder_ids?: string[];
  note_ids?: string[];
  include_all?: boolean;
  format?: 'markdown' | 'json';
}

export interface SummaryRequest {
  scope: 'folder' | 'tag' | 'all';
  folder_id?: string;
  tag_name?: string;
}

export interface SummaryResponse {
  summary: string;
  source_count: number;
  scope: string;
}

export interface TagSuggestResponse {
  suggested_tags: string[];
  existing_matches: Tag[];
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

// Images
export interface ImageItem {
  id: string;
  original_filename: string;
  stored_filename: string;
  content_type: string;
  file_size: number;
  url: string;
  description: string | null;
  folder_id: string | null;
  note_id: string | null;
  embedded: boolean;
  created_at: string;
}

export interface ImageListResponse {
  images: ImageItem[];
  total: number;
}

// Books
export interface BookSearchResult {
  found: boolean;
  title?: string;
  authors?: string[];
  year?: number;
  publisher?: string;
  isbn?: string;
  language?: string;
  pages?: number;
  description?: string;
  suggestion?: string;
}

export interface BookChapter {
  chapter_number: string;
  title: string;
  level: number;
}

export interface BookTocResult {
  chapters: BookChapter[];
  total_chapters: number;
}

export interface BookChapterNoteResult {
  folder: string;
  title: string;
  content: string;
  tag_ids: string[];
  tag_names: string[];
}

// Teacher / Infinite Teacher
export interface CourseListItem {
  id: string;
  topic: string;
  title: string;
  description: string;
  status: 'draft' | 'active' | 'completed';
  kind: 'teacher' | 'book';
  parent_course_id: string | null;
  book_authors?: string[];
  book_year?: string;
  book_isbn?: string;
  book_publisher?: string;
  total_units: number;
  completed_units: number;
  enabled_units: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface CourseUnit {
  id: string;
  unit_number: string;
  title: string;
  description: string;
  learning_objectives: string[];
  level: number;
  enabled: boolean;
  status: 'pending' | 'active' | 'completed' | 'skipped';
  order_index: number;
}

export interface CourseDetail {
  id: string;
  topic: string;
  title: string;
  description: string;
  status: 'draft' | 'active' | 'completed';
  kind: 'teacher' | 'book';
  parent_course_id: string | null;
  book_authors?: string[];
  book_year?: string;
  book_isbn?: string;
  book_publisher?: string;
  units: CourseUnit[];
  created_at: string | null;
  updated_at: string | null;
}

export interface CourseMessage {
  id: string;
  role: 'system' | 'assistant' | 'user' | 'note_generated';
  content: string;
  metadata: Record<string, unknown> | null;
  created_at: string | null;
}

export interface CourseNoteResult {
  title: string;
  content: string;
  folder: string;
  tag_ids: string[];
  tag_names: string[];
}

export interface AdvancedFocusSuggestion {
  title: string;
  description: string;
  topic: string;
}
