'use client';

import { useEditor, EditorContent } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import Image from '@tiptap/extension-image';
import Link from '@tiptap/extension-link';
import Underline from '@tiptap/extension-underline';
import TextAlign from '@tiptap/extension-text-align';
import Placeholder from '@tiptap/extension-placeholder';
import Highlight from '@tiptap/extension-highlight';
import { Table } from '@tiptap/extension-table';
import { TableRow } from '@tiptap/extension-table-row';
import { TableCell } from '@tiptap/extension-table-cell';
import { TableHeader } from '@tiptap/extension-table-header';
import { TextStyle } from '@tiptap/extension-text-style';
import Color from '@tiptap/extension-color';
import CodeBlockLowlight from '@tiptap/extension-code-block-lowlight';
import { Markdown } from 'tiptap-markdown';
import { common, createLowlight } from 'lowlight';
import { useCallback, useRef, useState } from 'react';
import {
    FiBold, FiItalic, FiUnderline, FiList, FiAlignLeft, FiAlignCenter,
    FiAlignRight, FiLink, FiImage, FiCode, FiSave, FiX,
    FiMinus, FiPaperclip, FiTable, FiEye, FiEdit3,
} from 'react-icons/fi';
import {
    LuHeading1, LuHeading2, LuHeading3, LuListOrdered, LuQuote,
    LuStrikethrough, LuHighlighter, LuRedo, LuUndo,
} from 'react-icons/lu';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { markdownComponents } from '@/lib/markdownComponents';
import { uploadFile, uploadPastedImage } from '@/lib/api';
import type { Note } from '@/lib/types';

const lowlight = createLowlight(common);

interface Props {
    note: Note;
    onClose: () => void;
    onSave: (title: string, content: string) => Promise<void>;
}

export default function RichTextEditor({ note, onClose, onSave }: Props) {
    const [title, setTitle] = useState(note.title);
    const [saving, setSaving] = useState(false);
    const [preview, setPreview] = useState(false);
    const [uploading, setUploading] = useState(false);
    const fileInputRef = useRef<HTMLInputElement>(null);
    const attachInputRef = useRef<HTMLInputElement>(null);

    const editor = useEditor({
        extensions: [
            StarterKit.configure({
                codeBlock: false,
            }),
            Image.configure({
                inline: true,
                allowBase64: true,
                HTMLAttributes: {
                    class: 'note-image',
                },
            }),
            Link.configure({
                openOnClick: false,
                HTMLAttributes: {
                    class: 'text-brain-400 underline hover:text-brain-300',
                },
            }),
            Underline,
            TextAlign.configure({
                types: ['heading', 'paragraph'],
            }),
            Placeholder.configure({
                placeholder: 'Beginne hier zu schreiben...',
            }),
            Highlight.configure({
                multicolor: true,
            }),
            TextStyle,
            Color,
            Table.configure({
                resizable: true,
            }),
            TableRow,
            TableCell,
            TableHeader,
            CodeBlockLowlight.configure({
                lowlight,
            }),
            Markdown.configure({
                html: true,
                transformPastedText: true,
                transformCopiedText: true,
            }),
        ],
        content: note.content,
        editorProps: {
            attributes: {
                class: 'prose prose-invert max-w-none focus:outline-none min-h-[500px] px-8 py-8',
            },
            handlePaste: (view, event) => {
                const items = event.clipboardData?.items;
                if (!items) return false;

                for (let i = 0; i < items.length; i++) {
                    const item = items[i];
                    if (item.type.startsWith('image/')) {
                        event.preventDefault();
                        const file = item.getAsFile();
                        if (file) {
                            handleImageUpload(file);
                        }
                        return true;
                    }
                }
                return false;
            },
            handleDrop: (view, event) => {
                const files = event.dataTransfer?.files;
                if (!files || files.length === 0) return false;

                for (let i = 0; i < files.length; i++) {
                    const file = files[i];
                    if (file.type.startsWith('image/')) {
                        event.preventDefault();
                        handleImageUpload(file);
                        return true;
                    }
                }
                return false;
            },
        },
    });

    const handleImageUpload = useCallback(async (file: File) => {
        if (!editor) return;
        setUploading(true);
        try {
            const result = await uploadPastedImage(file);
            editor.chain().focus().setImage({ src: result.url, alt: file.name }).run();
        } catch (e) {
            console.error('Image upload failed:', e);
        } finally {
            setUploading(false);
        }
    }, [editor]);

    const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file || !editor) return;

        if (file.type.startsWith('image/')) {
            await handleImageUpload(file);
        } else {
            setUploading(true);
            try {
                const result = await uploadFile(file);
                editor.chain().focus().insertContent(
                    `<a href="${result.url}" target="_blank" class="text-brain-400 underline">${result.filename} (${formatFileSize(result.size)})</a>`
                ).run();
            } catch (e) {
                console.error('File upload failed:', e);
            } finally {
                setUploading(false);
            }
        }
        e.target.value = '';
    };

    const handleAttachmentSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file || !editor) return;

        // If it's an image, insert as image (not attachment link)
        if (file.type.startsWith('image/')) {
            await handleImageUpload(file);
            e.target.value = '';
            return;
        }

        setUploading(true);
        try {
            const result = await uploadFile(file);
            editor.chain().focus().insertContent(
                `<a href="${result.url}" target="_blank" class="text-brain-400 underline">📎 ${result.filename} (${formatFileSize(result.size)})</a>`
            ).run();
        } catch (e) {
            console.error('Attachment upload failed:', e);
        } finally {
            setUploading(false);
        }
        e.target.value = '';
    };

    const formatFileSize = (bytes: number) => {
        if (bytes < 1024) return `${bytes} B`;
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
        return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    };

    const addLink = useCallback(() => {
        if (!editor) return;
        const previousUrl = editor.getAttributes('link').href;
        const url = window.prompt('URL eingeben:', previousUrl);
        if (url === null) return;
        if (url === '') {
            editor.chain().focus().extendMarkRange('link').unsetLink().run();
            return;
        }
        editor.chain().focus().extendMarkRange('link').setLink({ href: url }).run();
    }, [editor]);

    const addTable = useCallback(() => {
        if (!editor) return;
        editor.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run();
    }, [editor]);

    const handleSave = async () => {
        if (!editor) return;
        setSaving(true);
        try {
            const markdown = (editor.storage as any).markdown.getMarkdown();
            await onSave(title, markdown);
        } finally {
            setSaving(false);
        }
    };

    const getMarkdownContent = () => {
        if (!editor) return note.content;
        return (editor.storage as any).markdown.getMarkdown();
    };

    if (!editor) return null;

    return (
        <div className="h-full flex flex-col bg-dark-950">
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-3 border-b border-dark-800 bg-dark-900/50">
                <div className="flex items-center gap-3 flex-1">
                    <input
                        type="text"
                        value={title}
                        onChange={(e) => setTitle(e.target.value)}
                        className="text-lg font-semibold bg-transparent text-white border-b border-dark-700 focus:border-brain-500 focus:outline-none px-1 py-0.5 flex-1 max-w-xl"
                        placeholder="Titel..."
                    />
                </div>
                <div className="flex items-center gap-2">
                    {uploading && (
                        <div className="flex items-center gap-1.5 text-xs text-brain-400">
                            <div className="w-3 h-3 border-2 border-brain-400 border-t-transparent rounded-full animate-spin" />
                            Lädt hoch...
                        </div>
                    )}
                    <button
                        onClick={() => setPreview(!preview)}
                        className={`flex items-center gap-1.5 px-3 py-2 text-sm rounded-lg transition-colors ${preview
                            ? 'bg-brain-600/20 text-brain-400'
                            : 'bg-dark-800 text-dark-400 hover:text-white'
                            }`}
                    >
                        {preview ? <FiEdit3 className="w-4 h-4" /> : <FiEye className="w-4 h-4" />}
                        {preview ? 'Editor' : 'Vorschau'}
                    </button>
                    <button
                        onClick={handleSave}
                        disabled={saving}
                        className="flex items-center gap-1.5 px-3 py-2 text-sm bg-brain-600 hover:bg-brain-500 text-white rounded-lg transition-colors disabled:opacity-50"
                    >
                        <FiSave className="w-4 h-4" />
                        {saving ? 'Speichert...' : 'Speichern'}
                    </button>
                    <button
                        onClick={onClose}
                        className="p-2 hover:bg-dark-800 rounded-lg transition-colors"
                    >
                        <FiX className="w-4 h-4 text-dark-400" />
                    </button>
                </div>
            </div>

            {/* Toolbar */}
            {!preview && (
                <div className="flex flex-wrap items-center gap-0.5 px-4 py-2 border-b border-dark-800 bg-dark-900/80">
                    {/* Undo / Redo */}
                    <ToolButton
                        onClick={() => editor.chain().focus().undo().run()}
                        disabled={!editor.can().undo()}
                        title="Rückgängig"
                    >
                        <LuUndo className="w-4 h-4" />
                    </ToolButton>
                    <ToolButton
                        onClick={() => editor.chain().focus().redo().run()}
                        disabled={!editor.can().redo()}
                        title="Wiederholen"
                    >
                        <LuRedo className="w-4 h-4" />
                    </ToolButton>

                    <Divider />

                    {/* Text formatting */}
                    <ToolButton
                        onClick={() => editor.chain().focus().toggleBold().run()}
                        active={editor.isActive('bold')}
                        title="Fett (Ctrl+B)"
                    >
                        <FiBold className="w-4 h-4" />
                    </ToolButton>
                    <ToolButton
                        onClick={() => editor.chain().focus().toggleItalic().run()}
                        active={editor.isActive('italic')}
                        title="Kursiv (Ctrl+I)"
                    >
                        <FiItalic className="w-4 h-4" />
                    </ToolButton>
                    <ToolButton
                        onClick={() => editor.chain().focus().toggleUnderline().run()}
                        active={editor.isActive('underline')}
                        title="Unterstreichen (Ctrl+U)"
                    >
                        <FiUnderline className="w-4 h-4" />
                    </ToolButton>
                    <ToolButton
                        onClick={() => editor.chain().focus().toggleStrike().run()}
                        active={editor.isActive('strike')}
                        title="Durchgestrichen"
                    >
                        <LuStrikethrough className="w-4 h-4" />
                    </ToolButton>
                    <ToolButton
                        onClick={() => editor.chain().focus().toggleHighlight().run()}
                        active={editor.isActive('highlight')}
                        title="Hervorheben"
                    >
                        <LuHighlighter className="w-4 h-4" />
                    </ToolButton>

                    <Divider />

                    {/* Headings */}
                    <ToolButton
                        onClick={() => editor.chain().focus().toggleHeading({ level: 1 }).run()}
                        active={editor.isActive('heading', { level: 1 })}
                        title="Überschrift 1"
                    >
                        <LuHeading1 className="w-4 h-4" />
                    </ToolButton>
                    <ToolButton
                        onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}
                        active={editor.isActive('heading', { level: 2 })}
                        title="Überschrift 2"
                    >
                        <LuHeading2 className="w-4 h-4" />
                    </ToolButton>
                    <ToolButton
                        onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()}
                        active={editor.isActive('heading', { level: 3 })}
                        title="Überschrift 3"
                    >
                        <LuHeading3 className="w-4 h-4" />
                    </ToolButton>

                    <Divider />

                    {/* Lists */}
                    <ToolButton
                        onClick={() => editor.chain().focus().toggleBulletList().run()}
                        active={editor.isActive('bulletList')}
                        title="Aufzählung"
                    >
                        <FiList className="w-4 h-4" />
                    </ToolButton>
                    <ToolButton
                        onClick={() => editor.chain().focus().toggleOrderedList().run()}
                        active={editor.isActive('orderedList')}
                        title="Nummerierte Liste"
                    >
                        <LuListOrdered className="w-4 h-4" />
                    </ToolButton>

                    <Divider />

                    {/* Alignment */}
                    <ToolButton
                        onClick={() => editor.chain().focus().setTextAlign('left').run()}
                        active={editor.isActive({ textAlign: 'left' })}
                        title="Linksbündig"
                    >
                        <FiAlignLeft className="w-4 h-4" />
                    </ToolButton>
                    <ToolButton
                        onClick={() => editor.chain().focus().setTextAlign('center').run()}
                        active={editor.isActive({ textAlign: 'center' })}
                        title="Zentriert"
                    >
                        <FiAlignCenter className="w-4 h-4" />
                    </ToolButton>
                    <ToolButton
                        onClick={() => editor.chain().focus().setTextAlign('right').run()}
                        active={editor.isActive({ textAlign: 'right' })}
                        title="Rechtsbündig"
                    >
                        <FiAlignRight className="w-4 h-4" />
                    </ToolButton>

                    <Divider />

                    {/* Blocks */}
                    <ToolButton
                        onClick={() => editor.chain().focus().toggleBlockquote().run()}
                        active={editor.isActive('blockquote')}
                        title="Zitat"
                    >
                        <LuQuote className="w-4 h-4" />
                    </ToolButton>
                    <ToolButton
                        onClick={() => editor.chain().focus().toggleCode().run()}
                        active={editor.isActive('code')}
                        title="Inline-Code"
                    >
                        <FiCode className="w-4 h-4" />
                    </ToolButton>
                    <ToolButton
                        onClick={() => editor.chain().focus().toggleCodeBlock().run()}
                        active={editor.isActive('codeBlock')}
                        title="Code-Block"
                    >
                        <span className="text-xs font-mono">{'{}'}</span>
                    </ToolButton>
                    <ToolButton
                        onClick={() => editor.chain().focus().setHorizontalRule().run()}
                        title="Trennlinie"
                    >
                        <FiMinus className="w-4 h-4" />
                    </ToolButton>

                    <Divider />

                    {/* Insert */}
                    <ToolButton onClick={addLink} active={editor.isActive('link')} title="Link einfügen">
                        <FiLink className="w-4 h-4" />
                    </ToolButton>
                    <ToolButton onClick={() => fileInputRef.current?.click()} title="Bild einfügen">
                        <FiImage className="w-4 h-4" />
                    </ToolButton>
                    <ToolButton onClick={() => attachInputRef.current?.click()} title="Anhang einfügen">
                        <FiPaperclip className="w-4 h-4" />
                    </ToolButton>
                    <ToolButton onClick={addTable} title="Tabelle einfügen">
                        <FiTable className="w-4 h-4" />
                    </ToolButton>

                    {/* Hidden file inputs */}
                    <input
                        ref={fileInputRef}
                        type="file"
                        accept="image/*"
                        className="hidden"
                        onChange={handleFileSelect}
                    />
                    <input
                        ref={attachInputRef}
                        type="file"
                        accept="*/*"
                        className="hidden"
                        onChange={handleAttachmentSelect}
                    />
                </div>
            )}

            {/* Editor / Preview */}
            <div className="flex-1 overflow-y-auto">
                {preview ? (
                    <div className="max-w-4xl mx-auto px-8 py-8">
                        <article className="markdown-content">
                            <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                                {getMarkdownContent()}
                            </ReactMarkdown>
                        </article>
                    </div>
                ) : (
                    <EditorContent editor={editor} className="h-full tiptap-editor" />
                )}
            </div>
        </div>
    );
}

/* ── Toolbar sub-components ────────────────────────────────── */

function ToolButton({
    onClick,
    active,
    disabled,
    title,
    children,
}: {
    onClick: () => void;
    active?: boolean;
    disabled?: boolean;
    title?: string;
    children: React.ReactNode;
}) {
    return (
        <button
            onClick={onClick}
            disabled={disabled}
            title={title}
            className={`p-1.5 rounded transition-colors ${active
                ? 'bg-brain-600/30 text-brain-400'
                : disabled
                    ? 'text-dark-700 cursor-not-allowed'
                    : 'text-dark-400 hover:text-white hover:bg-dark-800'
                }`}
        >
            {children}
        </button>
    );
}

function Divider() {
    return <div className="w-px h-5 bg-dark-700 mx-1" />;
}
