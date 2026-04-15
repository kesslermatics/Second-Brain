'use client';

import { useState, useRef } from 'react';
import { FiFolder, FiFolderPlus, FiChevronRight, FiChevronDown, FiFile, FiTrash2, FiFilePlus } from 'react-icons/fi';
import { LuPencilRuler } from 'react-icons/lu';
import { useStore } from '@/lib/store';
import { createFolder, deleteFolder, getNote, createNote, deleteNote, updateNote, moveFolder } from '@/lib/api';
import type { FolderTree } from '@/lib/types';

interface Props {
    folders: FolderTree[];
    level: number;
}

export default function FolderTreeComponent({ folders, level }: Props) {
    const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set());
    const [newFolderParent, setNewFolderParent] = useState<string | null>(null);
    const [newFolderName, setNewFolderName] = useState('');
    const [dragOverFolder, setDragOverFolder] = useState<string | null>(null);
    const { loadFolderTree, setSelectedNote, setActiveView, setPendingEdit, selectedNote } = useStore();
    const dragItem = useRef<{ type: 'note' | 'folder'; id: string } | null>(null);

    const toggleFolder = (folderId: string) => {
        const next = new Set(expandedFolders);
        if (next.has(folderId)) {
            next.delete(folderId);
        } else {
            next.add(folderId);
        }
        setExpandedFolders(next);
    };

    const handleCreateFolder = async (parentId: string) => {
        if (!newFolderName.trim()) return;
        try {
            await createFolder(newFolderName.trim(), parentId);
            setNewFolderName('');
            setNewFolderParent(null);
            await loadFolderTree();
        } catch (e) {
            console.error(e);
        }
    };

    const handleDeleteFolder = async (e: React.MouseEvent, folderId: string) => {
        e.stopPropagation();
        if (!confirm('Ordner und alle Inhalte löschen?')) return;
        try {
            await deleteFolder(folderId);
            await loadFolderTree();
        } catch (e) {
            console.error(e);
        }
    };

    const handleSelectNote = async (noteId: string) => {
        try {
            const note = await getNote(noteId);
            setSelectedNote(note);
            setActiveView('notes');
        } catch (e) {
            console.error(e);
        }
    };

    const handleCreateNote = async (e: React.MouseEvent, folderId: string) => {
        e.stopPropagation();
        try {
            const note = await createNote('Neue Notiz', '', folderId);
            setSelectedNote(note);
            setPendingEdit(true);
            setActiveView('notes');
            await loadFolderTree();
            // Expand the folder to see the new note
            const next = new Set(expandedFolders);
            next.add(folderId);
            setExpandedFolders(next);
        } catch (e) {
            console.error(e);
        }
    };

    const handleCreateExcalidraw = async (e: React.MouseEvent, folderId: string) => {
        e.stopPropagation();
        try {
            const initialData = JSON.stringify({ elements: [], appState: { theme: 'dark' }, files: {} });
            const note = await createNote('Neue Zeichnung', initialData, folderId, undefined, 'excalidraw');
            setSelectedNote(note);
            setPendingEdit(true);
            setActiveView('notes');
            await loadFolderTree();
            const next = new Set(expandedFolders);
            next.add(folderId);
            setExpandedFolders(next);
        } catch (e) {
            console.error(e);
        }
    };

    const handleDeleteNote = async (e: React.MouseEvent, noteId: string) => {
        e.stopPropagation();
        if (!confirm('Notiz wirklich löschen?')) return;
        try {
            await deleteNote(noteId);
            if (selectedNote?.id === noteId) {
                setSelectedNote(null);
            }
            await loadFolderTree();
        } catch (e) {
            console.error(e);
        }
    };

    // ── Drag & Drop ──────────────────────────────────────────────

    const handleDragStart = (e: React.DragEvent, type: 'note' | 'folder', id: string) => {
        e.stopPropagation();
        dragItem.current = { type, id };
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', JSON.stringify({ type, id }));
        if (e.currentTarget instanceof HTMLElement) {
            e.currentTarget.style.opacity = '0.5';
        }
    };

    const handleDragEnd = (e: React.DragEvent) => {
        if (e.currentTarget instanceof HTMLElement) {
            e.currentTarget.style.opacity = '1';
        }
        dragItem.current = null;
        setDragOverFolder(null);
    };

    const handleDragOver = (e: React.DragEvent, folderId: string) => {
        e.preventDefault();
        e.stopPropagation();
        e.dataTransfer.dropEffect = 'move';
        setDragOverFolder(folderId);
    };

    const handleDragLeave = (e: React.DragEvent) => {
        e.stopPropagation();
        setDragOverFolder(null);
    };

    const handleDrop = async (e: React.DragEvent, targetFolderId: string) => {
        e.preventDefault();
        e.stopPropagation();
        setDragOverFolder(null);

        let data: { type: string; id: string } | null = null;
        try {
            data = JSON.parse(e.dataTransfer.getData('text/plain'));
        } catch {
            return;
        }
        if (!data) return;

        try {
            if (data.type === 'note') {
                await updateNote(data.id, { folder_id: targetFolderId });
            } else if (data.type === 'folder') {
                if (data.id === targetFolderId) return;
                await moveFolder(data.id, targetFolderId);
            }
            await loadFolderTree();
            const next = new Set(expandedFolders);
            next.add(targetFolderId);
            setExpandedFolders(next);
        } catch (e) {
            console.error('Drop failed:', e);
        }
    };

    if (folders.length === 0 && level === 0) {
        return (
            <p className="text-xs text-dark-600 px-3 py-2">Keine Ordner vorhanden</p>
        );
    }

    return (
        <div>
            {folders.map((folder) => {
                const isExpanded = expandedFolders.has(folder.id);
                const hasChildren = folder.children.length > 0 || folder.notes.length > 0;
                const isDragOver = dragOverFolder === folder.id;

                return (
                    <div key={folder.id}>
                        <div
                            className={`group flex items-center gap-1.5 px-2 py-1.5 rounded-md text-sm text-dark-400 hover:text-white hover:bg-dark-800 cursor-pointer transition-colors ${isDragOver ? 'bg-brain-600/20 ring-1 ring-brain-500/50' : ''}`}
                            style={{ paddingLeft: `${level * 16 + 8}px` }}
                            onClick={() => toggleFolder(folder.id)}
                            draggable
                            onDragStart={(e) => handleDragStart(e, 'folder', folder.id)}
                            onDragEnd={handleDragEnd}
                            onDragOver={(e) => handleDragOver(e, folder.id)}
                            onDragLeave={handleDragLeave}
                            onDrop={(e) => handleDrop(e, folder.id)}
                        >
                            {hasChildren ? (
                                isExpanded ? <FiChevronDown className="w-3.5 h-3.5 flex-shrink-0" /> : <FiChevronRight className="w-3.5 h-3.5 flex-shrink-0" />
                            ) : (
                                <span className="w-3.5" />
                            )}
                            <FiFolder className={`w-3.5 h-3.5 flex-shrink-0 ${isDragOver ? 'text-brain-400' : 'text-yellow-500'}`} />
                            <span className="truncate flex-1">{folder.name}</span>
                            <div className="opacity-0 group-hover:opacity-100 flex gap-0.5">
                                <button
                                    onClick={(e) => { e.stopPropagation(); setNewFolderParent(folder.id); }}
                                    className="p-0.5 hover:bg-dark-700 rounded"
                                    title="Unterordner erstellen"
                                >
                                    <FiFolderPlus className="w-3 h-3" />
                                </button>
                                <button
                                    onClick={(e) => handleCreateNote(e, folder.id)}
                                    className="p-0.5 hover:bg-dark-700 rounded"
                                    title="Neue Notiz erstellen"
                                >
                                    <FiFilePlus className="w-3 h-3 text-brain-400" />
                                </button>
                                <button
                                    onClick={(e) => handleCreateExcalidraw(e, folder.id)}
                                    className="p-0.5 hover:bg-dark-700 rounded"
                                    title="Neue Excalidraw Zeichnung"
                                >
                                    <LuPencilRuler className="w-3 h-3 text-purple-400" />
                                </button>
                                <button
                                    onClick={(e) => handleDeleteFolder(e, folder.id)}
                                    className="p-0.5 hover:bg-dark-700 rounded"
                                    title="Ordner löschen"
                                >
                                    <FiTrash2 className="w-3 h-3 text-red-400" />
                                </button>
                            </div>
                        </div>

                        {newFolderParent === folder.id && (
                            <div className="flex items-center gap-1 px-2 py-1" style={{ paddingLeft: `${(level + 1) * 16 + 8}px` }}>
                                <input
                                    type="text"
                                    value={newFolderName}
                                    onChange={(e) => setNewFolderName(e.target.value)}
                                    onKeyDown={(e) => {
                                        if (e.key === 'Enter') handleCreateFolder(folder.id);
                                        if (e.key === 'Escape') { setNewFolderParent(null); setNewFolderName(''); }
                                    }}
                                    placeholder="Ordnername..."
                                    className="flex-1 px-2 py-1 text-xs bg-dark-950 border border-dark-700 rounded text-white placeholder-dark-600 focus:outline-none focus:border-brain-500"
                                    autoFocus
                                />
                            </div>
                        )}

                        {isExpanded && (
                            <>
                                {folder.notes.map((note) => (
                                    <div
                                        key={note.id}
                                        onClick={() => handleSelectNote(note.id)}
                                        className="group flex items-center gap-1.5 px-2 py-1.5 rounded-md text-sm text-dark-400 hover:text-white hover:bg-dark-800 cursor-pointer transition-colors"
                                        style={{ paddingLeft: `${(level + 1) * 16 + 8}px` }}
                                        draggable
                                        onDragStart={(e) => handleDragStart(e, 'note', note.id)}
                                        onDragEnd={handleDragEnd}
                                    >
                                        {(note.note_type || 'text') === 'excalidraw' ? (
                                            <LuPencilRuler className="w-3.5 h-3.5 flex-shrink-0 text-purple-400" />
                                        ) : (
                                            <FiFile className="w-3.5 h-3.5 flex-shrink-0 text-brain-400" />
                                        )}
                                        <span className="truncate flex-1">{note.title}</span>
                                        <button
                                            onClick={(e) => handleDeleteNote(e, note.id)}
                                            className="opacity-0 group-hover:opacity-100 p-0.5 hover:bg-dark-700 rounded flex-shrink-0"
                                            title="Notiz löschen"
                                        >
                                            <FiTrash2 className="w-3 h-3 text-red-400" />
                                        </button>
                                    </div>
                                ))}
                                <FolderTreeComponent folders={folder.children} level={level + 1} />
                            </>
                        )}
                    </div>
                );
            })}
        </div>
    );
}
