'use client';

import { useEffect, useState, useRef, useCallback } from 'react';
import { useStore } from '@/lib/store';
import { LuBrain } from 'react-icons/lu';
import {
    FiMessageSquare, FiBookOpen, FiPlus, FiTrash2,
    FiChevronRight, FiChevronDown, FiLogOut, FiMenu, FiFile, FiSettings,
    FiSearch, FiGrid, FiShare2, FiRepeat, FiDownload, FiFileText, FiImage, FiEdit2,
} from 'react-icons/fi';
import { createChatSession, getChatSession, deleteChatSession, updateChatSession } from '@/lib/api';
import FolderTreeComponent from './FolderTree';
import SettingsModal from './SettingsModal';
import type { ChatSession } from '@/lib/types';

export default function Sidebar() {
    const {
        activeView, setActiveView, sidebarOpen, setSidebarOpen,
        notesSessions, qaSessions, loadNotesSessions, loadQASessions,
        setActiveNotesSession, setActiveQASession, loadFolderTree,
        folderTree, logout,
    } = useStore();

    const [notesExpanded, setNotesExpanded] = useState(true);
    const [qaExpanded, setQAExpanded] = useState(true);
    const [foldersExpanded, setFoldersExpanded] = useState(true);
    const [settingsOpen, setSettingsOpen] = useState(false);
    const [sidebarWidth, setSidebarWidth] = useState(288);
    const [renamingSession, setRenamingSession] = useState<string | null>(null);
    const [renameValue, setRenameValue] = useState('');
    const isResizing = useRef(false);

    const handleMouseDown = useCallback((e: React.MouseEvent) => {
        e.preventDefault();
        isResizing.current = true;
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';

        const handleMouseMove = (e: MouseEvent) => {
            if (!isResizing.current) return;
            const newWidth = Math.min(Math.max(e.clientX, 220), 600);
            setSidebarWidth(newWidth);
        };
        const handleMouseUp = () => {
            isResizing.current = false;
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
            document.removeEventListener('mousemove', handleMouseMove);
            document.removeEventListener('mouseup', handleMouseUp);
        };
        document.addEventListener('mousemove', handleMouseMove);
        document.addEventListener('mouseup', handleMouseUp);
    }, []);

    useEffect(() => {
        loadNotesSessions();
        loadQASessions();
        loadFolderTree();
    }, [loadNotesSessions, loadQASessions, loadFolderTree]);

    const handleNewNotesSession = async () => {
        try {
            const session = await createChatSession('notes', 'Neue Notiz');
            const detail = await getChatSession(session.id);
            setActiveNotesSession(detail);
            setActiveView('chat');
            await loadNotesSessions();
        } catch (e) {
            console.error(e);
        }
    };

    const handleNewQASession = async () => {
        try {
            const session = await createChatSession('qa', 'Neue Frage');
            const detail = await getChatSession(session.id);
            setActiveQASession(detail);
            setActiveView('chat');
            await loadQASessions();
        } catch (e) {
            console.error(e);
        }
    };

    const handleSelectSession = async (session: ChatSession, type: 'notes' | 'qa') => {
        try {
            const detail = await getChatSession(session.id);
            if (type === 'notes') {
                setActiveNotesSession(detail);
            } else {
                setActiveQASession(detail);
            }
            setActiveView('chat');
        } catch (e) {
            console.error(e);
        }
    };

    const handleDeleteSession = async (e: React.MouseEvent, sessionId: string, type: 'notes' | 'qa') => {
        e.stopPropagation();
        try {
            await deleteChatSession(sessionId);
            if (type === 'notes') {
                await loadNotesSessions();
                setActiveNotesSession(null);
            } else {
                await loadQASessions();
                setActiveQASession(null);
            }
        } catch (e) {
            console.error(e);
        }
    };

    const handleRenameSession = async (sessionId: string, type: 'notes' | 'qa') => {
        if (!renameValue.trim()) { setRenamingSession(null); return; }
        try {
            await updateChatSession(sessionId, renameValue.trim());
            setRenamingSession(null);
            setRenameValue('');
            if (type === 'notes') await loadNotesSessions();
            else await loadQASessions();
        } catch (e) {
            console.error(e);
        }
    };

    const startRenameSession = (e: React.MouseEvent, sessionId: string, currentTitle: string) => {
        e.stopPropagation();
        setRenamingSession(sessionId);
        setRenameValue(currentTitle);
    };

    return (
        <>
            {/* Mobile toggle */}
            <button
                onClick={() => setSidebarOpen(!sidebarOpen)}
                className="lg:hidden fixed top-3 left-3 z-50 p-2 bg-dark-900 rounded-lg border border-dark-800"
            >
                <FiMenu className="w-5 h-5" />
            </button>

            {/* Overlay */}
            {sidebarOpen && (
                <div
                    className="lg:hidden fixed inset-0 bg-black/50 z-30"
                    onClick={() => setSidebarOpen(false)}
                />
            )}

            <aside
                className={`${sidebarOpen ? 'translate-x-0' : '-translate-x-full'
                    } lg:translate-x-0 fixed lg:relative z-40 h-full bg-dark-900 border-r border-dark-800 flex flex-col transition-transform duration-200`}
                style={{ width: `${sidebarWidth}px`, minWidth: `${sidebarWidth}px` }}
            >
                {/* Header */}
                <div className="p-4 border-b border-dark-800">
                    <div className="flex items-center gap-3">
                        <div className="p-2 bg-brain-600/20 rounded-xl">
                            <LuBrain className="w-5 h-5 text-brain-400" />
                        </div>
                        <span className="font-bold text-lg text-white">Brain</span>
                    </div>
                </div>

                {/* Navigation */}
                <div className="flex border-b border-dark-800">
                    <button
                        onClick={() => setActiveView('chat')}
                        className={`flex-1 flex items-center justify-center gap-2 py-3 text-sm font-medium transition-colors ${activeView === 'chat'
                            ? 'text-brain-400 border-b-2 border-brain-400'
                            : 'text-dark-500 hover:text-dark-300'
                            }`}
                    >
                        <FiMessageSquare className="w-4 h-4" />
                        Chat
                    </button>
                    <button
                        onClick={() => setActiveView('notes')}
                        className={`flex-1 flex items-center justify-center gap-2 py-3 text-sm font-medium transition-colors ${activeView === 'notes'
                            ? 'text-brain-400 border-b-2 border-brain-400'
                            : 'text-dark-500 hover:text-dark-300'
                            }`}
                    >
                        <FiBookOpen className="w-4 h-4" />
                        Notizen
                    </button>
                </div>

                {/* Quick Actions */}
                <div className="grid grid-cols-3 gap-1 p-2 border-b border-dark-800">
                    <button
                        onClick={() => setActiveView('search')}
                        className={`flex flex-col items-center gap-1 py-2 px-1 rounded-lg text-[10px] font-medium transition-colors ${activeView === 'search' ? 'bg-brain-600/20 text-brain-400' : 'text-dark-500 hover:text-white hover:bg-dark-800'
                            }`}
                    >
                        <FiSearch className="w-3.5 h-3.5" />
                        Suche
                    </button>
                    <button
                        onClick={() => setActiveView('dashboard')}
                        className={`flex flex-col items-center gap-1 py-2 px-1 rounded-lg text-[10px] font-medium transition-colors ${activeView === 'dashboard' ? 'bg-brain-600/20 text-brain-400' : 'text-dark-500 hover:text-white hover:bg-dark-800'
                            }`}
                    >
                        <FiGrid className="w-3.5 h-3.5" />
                        Dashboard
                    </button>
                    <button
                        onClick={() => setActiveView('graph')}
                        className={`flex flex-col items-center gap-1 py-2 px-1 rounded-lg text-[10px] font-medium transition-colors ${activeView === 'graph' ? 'bg-brain-600/20 text-brain-400' : 'text-dark-500 hover:text-white hover:bg-dark-800'
                            }`}
                    >
                        <FiShare2 className="w-3.5 h-3.5" />
                        Graph
                    </button>
                    <button
                        onClick={() => setActiveView('learn')}
                        className={`flex flex-col items-center gap-1 py-2 px-1 rounded-lg text-[10px] font-medium transition-colors ${activeView === 'learn' ? 'bg-green-600/20 text-green-400' : 'text-dark-500 hover:text-white hover:bg-dark-800'
                            }`}
                    >
                        <FiRepeat className="w-3.5 h-3.5" />
                        Lernen
                    </button>
                    <button
                        onClick={() => setActiveView('export')}
                        className={`flex flex-col items-center gap-1 py-2 px-1 rounded-lg text-[10px] font-medium transition-colors ${activeView === 'export' ? 'bg-brain-600/20 text-brain-400' : 'text-dark-500 hover:text-white hover:bg-dark-800'
                            }`}
                    >
                        <FiDownload className="w-3.5 h-3.5" />
                        Export
                    </button>
                    <button
                        onClick={() => setActiveView('summary')}
                        className={`flex flex-col items-center gap-1 py-2 px-1 rounded-lg text-[10px] font-medium transition-colors ${activeView === 'summary' ? 'bg-purple-600/20 text-purple-400' : 'text-dark-500 hover:text-white hover:bg-dark-800'
                            }`}
                    >
                        <FiFileText className="w-3.5 h-3.5" />
                        Zusammen.
                    </button>
                    <button
                        onClick={() => setActiveView('images')}
                        className={`flex flex-col items-center gap-1 py-2 px-1 rounded-lg text-[10px] font-medium transition-colors ${activeView === 'images' ? 'bg-indigo-600/20 text-indigo-400' : 'text-dark-500 hover:text-white hover:bg-dark-800'
                            }`}
                    >
                        <FiImage className="w-3.5 h-3.5" />
                        Bilder
                    </button>
                </div>

                {/* Content */}
                <div className="flex-1 overflow-y-auto p-3 space-y-1">
                    {/* Notes Chat Sessions */}
                    <div className="mb-2">
                        <button
                            onClick={() => setNotesExpanded(!notesExpanded)}
                            className="flex items-center gap-2 w-full text-left text-xs font-semibold text-dark-500 uppercase tracking-wider px-2 py-1.5 hover:text-dark-300"
                        >
                            {notesExpanded ? <FiChevronDown className="w-3.5 h-3.5" /> : <FiChevronRight className="w-3.5 h-3.5" />}
                            Notizen-Chat
                            <button
                                onClick={(e) => { e.stopPropagation(); handleNewNotesSession(); }}
                                className="ml-auto p-1 hover:bg-dark-800 rounded"
                                title="Neuer Notizen-Chat"
                            >
                                <FiPlus className="w-3.5 h-3.5" />
                            </button>
                        </button>
                        {notesExpanded && (
                            <div className="space-y-0.5 mt-1">
                                {notesSessions.map((session) => (
                                    <div
                                        key={session.id}
                                        onClick={() => handleSelectSession(session, 'notes')}
                                        className="group flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-dark-400 hover:text-white hover:bg-dark-800 cursor-pointer transition-colors"
                                    >
                                        <FiFile className="w-3.5 h-3.5 flex-shrink-0 text-brain-400" />
                                        {renamingSession === session.id ? (
                                            <input
                                                type="text"
                                                value={renameValue}
                                                onChange={(e) => setRenameValue(e.target.value)}
                                                onKeyDown={(e) => {
                                                    if (e.key === 'Enter') handleRenameSession(session.id, 'notes');
                                                    if (e.key === 'Escape') { setRenamingSession(null); setRenameValue(''); }
                                                }}
                                                onBlur={() => handleRenameSession(session.id, 'notes')}
                                                onClick={(e) => e.stopPropagation()}
                                                className="flex-1 px-1 py-0 text-sm bg-dark-950 border border-brain-500 rounded text-white focus:outline-none min-w-0"
                                                autoFocus
                                            />
                                        ) : (
                                            <span className="truncate flex-1">{session.title}</span>
                                        )}
                                        <div className="opacity-0 group-hover:opacity-100 flex gap-0.5">
                                            <button
                                                onClick={(e) => startRenameSession(e, session.id, session.title)}
                                                className="p-1 hover:bg-dark-700 rounded transition-opacity"
                                            >
                                                <FiEdit2 className="w-3 h-3 text-dark-500 hover:text-blue-400" />
                                            </button>
                                            <button
                                                onClick={(e) => handleDeleteSession(e, session.id, 'notes')}
                                                className="p-1 hover:bg-dark-700 rounded transition-opacity"
                                            >
                                                <FiTrash2 className="w-3 h-3 text-dark-500 hover:text-red-400" />
                                            </button>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>

                    {/* QA Chat Sessions */}
                    <div className="mb-2">
                        <button
                            onClick={() => setQAExpanded(!qaExpanded)}
                            className="flex items-center gap-2 w-full text-left text-xs font-semibold text-dark-500 uppercase tracking-wider px-2 py-1.5 hover:text-dark-300"
                        >
                            {qaExpanded ? <FiChevronDown className="w-3.5 h-3.5" /> : <FiChevronRight className="w-3.5 h-3.5" />}
                            Fragen & Antworten
                            <button
                                onClick={(e) => { e.stopPropagation(); handleNewQASession(); }}
                                className="ml-auto p-1 hover:bg-dark-800 rounded"
                                title="Neue Frage"
                            >
                                <FiPlus className="w-3.5 h-3.5" />
                            </button>
                        </button>
                        {qaExpanded && (
                            <div className="space-y-0.5 mt-1">
                                {qaSessions.map((session) => (
                                    <div
                                        key={session.id}
                                        onClick={() => handleSelectSession(session, 'qa')}
                                        className="group flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-dark-400 hover:text-white hover:bg-dark-800 cursor-pointer transition-colors"
                                    >
                                        <FiMessageSquare className="w-3.5 h-3.5 flex-shrink-0 text-green-400" />
                                        {renamingSession === session.id ? (
                                            <input
                                                type="text"
                                                value={renameValue}
                                                onChange={(e) => setRenameValue(e.target.value)}
                                                onKeyDown={(e) => {
                                                    if (e.key === 'Enter') handleRenameSession(session.id, 'qa');
                                                    if (e.key === 'Escape') { setRenamingSession(null); setRenameValue(''); }
                                                }}
                                                onBlur={() => handleRenameSession(session.id, 'qa')}
                                                onClick={(e) => e.stopPropagation()}
                                                className="flex-1 px-1 py-0 text-sm bg-dark-950 border border-brain-500 rounded text-white focus:outline-none min-w-0"
                                                autoFocus
                                            />
                                        ) : (
                                            <span className="truncate flex-1">{session.title}</span>
                                        )}
                                        <div className="opacity-0 group-hover:opacity-100 flex gap-0.5">
                                            <button
                                                onClick={(e) => startRenameSession(e, session.id, session.title)}
                                                className="p-1 hover:bg-dark-700 rounded transition-opacity"
                                            >
                                                <FiEdit2 className="w-3 h-3 text-dark-500 hover:text-blue-400" />
                                            </button>
                                            <button
                                                onClick={(e) => handleDeleteSession(e, session.id, 'qa')}
                                                className="p-1 hover:bg-dark-700 rounded transition-opacity"
                                            >
                                                <FiTrash2 className="w-3 h-3 text-dark-500 hover:text-red-400" />
                                            </button>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>

                    {/* Folder Structure */}
                    <div>
                        <button
                            onClick={() => setFoldersExpanded(!foldersExpanded)}
                            className="flex items-center gap-2 w-full text-left text-xs font-semibold text-dark-500 uppercase tracking-wider px-2 py-1.5 hover:text-dark-300"
                        >
                            {foldersExpanded ? <FiChevronDown className="w-3.5 h-3.5" /> : <FiChevronRight className="w-3.5 h-3.5" />}
                            Ordner
                        </button>
                        {foldersExpanded && (
                            <div className="mt-1">
                                <FolderTreeComponent folders={folderTree} level={0} />
                            </div>
                        )}
                    </div>
                </div>

                {/* Footer */}
                <div className="p-3 border-t border-dark-800 space-y-1">
                    <button
                        onClick={() => setSettingsOpen(true)}
                        className="flex items-center gap-2 w-full px-3 py-2 text-sm text-dark-500 hover:text-white hover:bg-dark-800 rounded-lg transition-colors"
                    >
                        <FiSettings className="w-4 h-4" />
                        Einstellungen
                    </button>
                    <button
                        onClick={logout}
                        className="flex items-center gap-2 w-full px-3 py-2 text-sm text-dark-500 hover:text-white hover:bg-dark-800 rounded-lg transition-colors"
                    >
                        <FiLogOut className="w-4 h-4" />
                        Abmelden
                    </button>
                </div>
            </aside>

            {/* Resize handle */}
            <div
                onMouseDown={handleMouseDown}
                className="hidden lg:flex w-1 cursor-col-resize hover:bg-brain-500/50 active:bg-brain-500/70 transition-colors flex-shrink-0"
            />

            <SettingsModal isOpen={settingsOpen} onClose={() => setSettingsOpen(false)} />
        </>
    );
}
