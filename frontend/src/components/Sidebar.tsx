'use client';

import { useEffect, useState } from 'react';
import { useStore } from '@/lib/store';
import { LuBrain } from 'react-icons/lu';
import {
    FiMessageSquare, FiBookOpen, FiPlus, FiTrash2,
    FiChevronRight, FiChevronDown, FiLogOut, FiMenu, FiFile, FiSettings,
} from 'react-icons/fi';
import { createChatSession, getChatSession, deleteChatSession } from '@/lib/api';
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
                    } lg:translate-x-0 fixed lg:relative z-40 h-full w-72 bg-dark-900 border-r border-dark-800 flex flex-col transition-transform duration-200`}
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
                                        <span className="truncate flex-1">{session.title}</span>
                                        <button
                                            onClick={(e) => handleDeleteSession(e, session.id, 'notes')}
                                            className="opacity-0 group-hover:opacity-100 p-1 hover:bg-dark-700 rounded transition-opacity"
                                        >
                                            <FiTrash2 className="w-3 h-3 text-dark-500 hover:text-red-400" />
                                        </button>
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
                                        <span className="truncate flex-1">{session.title}</span>
                                        <button
                                            onClick={(e) => handleDeleteSession(e, session.id, 'qa')}
                                            className="opacity-0 group-hover:opacity-100 p-1 hover:bg-dark-700 rounded transition-opacity"
                                        >
                                            <FiTrash2 className="w-3 h-3 text-dark-500 hover:text-red-400" />
                                        </button>
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

            <SettingsModal isOpen={settingsOpen} onClose={() => setSettingsOpen(false)} />
        </>
    );
}
