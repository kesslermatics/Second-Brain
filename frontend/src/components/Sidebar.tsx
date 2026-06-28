'use client';

import { useEffect, useState, useRef, useCallback } from 'react';
import { useStore } from '@/lib/store';
import { LuBrain } from 'react-icons/lu';
import {
    FiMessageSquare, FiBookOpen, FiPlus, FiTrash2,
    FiChevronRight, FiChevronDown, FiLogOut, FiMenu, FiFile, FiSettings,
    FiSearch, FiGrid, FiShare2, FiRepeat, FiDownload, FiFileText, FiImage, FiEdit2, FiBook,
    FiCpu, FiHardDrive,
} from 'react-icons/fi';
import { LuGraduationCap } from 'react-icons/lu';
import { createChatSession, getChatSession, deleteChatSession, updateChatSession } from '@/lib/api';
import FolderTreeComponent from './FolderTree';
import SettingsModal from './SettingsModal';
import BackupModal from './BackupModal';
import type { ChatSession } from '@/lib/types';

export default function Sidebar() {
    const {
        activeView, setActiveView, sidebarOpen, setSidebarOpen,
        agentSessions, loadAgentSessions,
        setActiveAgentSession, activeAgentSession,
        loadFolderTree, folderTree, logout,
    } = useStore();

    const [agentExpanded, setAgentExpanded] = useState(true);
    const [foldersExpanded, setFoldersExpanded] = useState(true);
    const [settingsOpen, setSettingsOpen] = useState(false);
    const [backupOpen, setBackupOpen] = useState(false);
    const [sidebarWidth, setSidebarWidth] = useState(288);
    const [isDesktop, setIsDesktop] = useState(true);
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
        loadAgentSessions();
        loadFolderTree();

        const mq = window.matchMedia('(min-width: 1024px)');
        setIsDesktop(mq.matches);
        if (!mq.matches) setSidebarOpen(false);
        const handler = (e: MediaQueryListEvent) => {
            setIsDesktop(e.matches);
            if (!e.matches) setSidebarOpen(false);
        };
        mq.addEventListener('change', handler);
        return () => mq.removeEventListener('change', handler);
    }, [loadAgentSessions, loadFolderTree, setSidebarOpen]);

    const handleNewAgentSession = async () => {
        try {
            const session = await createChatSession('agent', 'Neuer Agent-Chat');
            const detail = await getChatSession(session.id);
            setActiveAgentSession(detail);
            setActiveView('agent');
            await loadAgentSessions();
        } catch (e) {
            console.error(e);
        }
    };

    const closeSidebarOnMobile = () => {
        if (window.innerWidth < 1024) setSidebarOpen(false);
    };

    const handleSelectSession = async (session: ChatSession, type: 'agent') => {
        try {
            const detail = await getChatSession(session.id);
            setActiveAgentSession(detail);
            setActiveView('agent');
            closeSidebarOnMobile();
        } catch (e) {
            console.error(e);
        }
    };

    const handleDeleteSession = async (e: React.MouseEvent, sessionId: string, type: 'agent') => {
        e.stopPropagation();
        try {
            await deleteChatSession(sessionId);
            await loadAgentSessions();
            setActiveAgentSession(null);
        } catch (e) {
            console.error(e);
        }
    };

    const handleRenameSession = async (sessionId: string, type: 'agent') => {
        if (!renameValue.trim()) { setRenamingSession(null); return; }
        try {
            await updateChatSession(sessionId, renameValue.trim());
            setRenamingSession(null);
            setRenameValue('');
            await loadAgentSessions();
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
                    } lg:translate-x-0 fixed lg:relative z-40 h-full w-72 lg:w-auto bg-dark-900 border-r border-dark-800 flex flex-col transition-transform duration-200`}
                style={isDesktop ? { width: `${sidebarWidth}px`, minWidth: `${sidebarWidth}px` } : undefined}
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
                        onClick={() => { setActiveView('agent'); closeSidebarOnMobile(); }}
                        className={`flex-1 flex items-center justify-center gap-2 py-3 text-sm font-medium transition-colors ${activeView === 'agent'
                            ? 'text-rose-400 border-b-2 border-rose-400'
                            : 'text-dark-500 hover:text-dark-300'
                            }`}
                    >
                        <FiCpu className="w-4 h-4" />
                        Agent
                    </button>
                    <button
                        onClick={() => { setActiveView('notes'); closeSidebarOnMobile(); }}
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
                        onClick={() => { setActiveView('search'); closeSidebarOnMobile(); }}
                        className={`flex flex-col items-center gap-1 py-2 px-1 rounded-lg text-[10px] font-medium transition-colors ${activeView === 'search' ? 'bg-brain-600/20 text-brain-400' : 'text-dark-500 hover:text-white hover:bg-dark-800'
                            }`}
                    >
                        <FiSearch className="w-3.5 h-3.5" />
                        Suche
                    </button>
                    <button
                        onClick={() => { setActiveView('dashboard'); closeSidebarOnMobile(); }}
                        className={`flex flex-col items-center gap-1 py-2 px-1 rounded-lg text-[10px] font-medium transition-colors ${activeView === 'dashboard' ? 'bg-brain-600/20 text-brain-400' : 'text-dark-500 hover:text-white hover:bg-dark-800'
                            }`}
                    >
                        <FiGrid className="w-3.5 h-3.5" />
                        Dashboard
                    </button>
                    <button
                        onClick={() => { setActiveView('graph'); closeSidebarOnMobile(); }}
                        className={`flex flex-col items-center gap-1 py-2 px-1 rounded-lg text-[10px] font-medium transition-colors ${activeView === 'graph' ? 'bg-brain-600/20 text-brain-400' : 'text-dark-500 hover:text-white hover:bg-dark-800'
                            }`}
                    >
                        <FiShare2 className="w-3.5 h-3.5" />
                        Graph
                    </button>
                    <button
                        onClick={() => { setActiveView('learn'); closeSidebarOnMobile(); }}
                        className={`flex flex-col items-center gap-1 py-2 px-1 rounded-lg text-[10px] font-medium transition-colors ${activeView === 'learn' ? 'bg-green-600/20 text-green-400' : 'text-dark-500 hover:text-white hover:bg-dark-800'
                            }`}
                    >
                        <FiRepeat className="w-3.5 h-3.5" />
                        Lernen
                    </button>
                    <button
                        onClick={() => { setActiveView('export'); closeSidebarOnMobile(); }}
                        className={`flex flex-col items-center gap-1 py-2 px-1 rounded-lg text-[10px] font-medium transition-colors ${activeView === 'export' ? 'bg-brain-600/20 text-brain-400' : 'text-dark-500 hover:text-white hover:bg-dark-800'
                            }`}
                    >
                        <FiDownload className="w-3.5 h-3.5" />
                        Export
                    </button>
                    <button
                        onClick={() => { setActiveView('summary'); closeSidebarOnMobile(); }}
                        className={`flex flex-col items-center gap-1 py-2 px-1 rounded-lg text-[10px] font-medium transition-colors ${activeView === 'summary' ? 'bg-purple-600/20 text-purple-400' : 'text-dark-500 hover:text-white hover:bg-dark-800'
                            }`}
                    >
                        <FiFileText className="w-3.5 h-3.5" />
                        Zusammen.
                    </button>
                    <button
                        onClick={() => { setActiveView('images'); closeSidebarOnMobile(); }}
                        className={`flex flex-col items-center gap-1 py-2 px-1 rounded-lg text-[10px] font-medium transition-colors ${activeView === 'images' ? 'bg-indigo-600/20 text-indigo-400' : 'text-dark-500 hover:text-white hover:bg-dark-800'
                            }`}
                    >
                        <FiImage className="w-3.5 h-3.5" />
                        Bilder
                    </button>
                    <button
                        onClick={() => { setActiveView('books'); closeSidebarOnMobile(); }}
                        className={`flex flex-col items-center gap-1 py-2 px-1 rounded-lg text-[10px] font-medium transition-colors ${activeView === 'books' ? 'bg-amber-600/20 text-amber-400' : 'text-dark-500 hover:text-white hover:bg-dark-800'
                            }`}
                    >
                        <FiBook className="w-3.5 h-3.5" />
                        Bücher
                    </button>
                    <button
                        onClick={() => { setActiveView('teacher'); closeSidebarOnMobile(); }}
                        className={`flex flex-col items-center gap-1 py-2 px-1 rounded-lg text-[10px] font-medium transition-colors ${activeView === 'teacher' ? 'bg-teal-600/20 text-teal-400' : 'text-dark-500 hover:text-white hover:bg-dark-800'
                            }`}
                    >
                        <LuGraduationCap className="w-3.5 h-3.5" />
                        Lehrer
                    </button>
                    <button
                        onClick={() => { setActiveView('agent'); closeSidebarOnMobile(); }}
                        className={`flex flex-col items-center gap-1 py-2 px-1 rounded-lg text-[10px] font-medium transition-colors ${activeView === 'agent' ? 'bg-rose-600/20 text-rose-400' : 'text-dark-500 hover:text-white hover:bg-dark-800'
                            }`}
                    >
                        <FiCpu className="w-3.5 h-3.5" />
                        Agent
                    </button>
                </div>

                {/* Content */}
                <div className="flex-1 overflow-y-auto p-3 space-y-1">
                    {/* Agent Sessions */}
                    <div>
                        <button
                            onClick={() => setAgentExpanded(!agentExpanded)}
                            className="flex items-center gap-2 w-full text-left text-xs font-semibold text-dark-500 uppercase tracking-wider px-2 py-1.5 hover:text-dark-300"
                        >
                            {agentExpanded ? <FiChevronDown className="w-3.5 h-3.5" /> : <FiChevronRight className="w-3.5 h-3.5" />}
                            <FiCpu className="w-3.5 h-3.5 text-rose-400" />
                            Agent
                            <button
                                onClick={(e) => { e.stopPropagation(); handleNewAgentSession(); }}
                                className="ml-auto p-1 hover:bg-dark-800 rounded"
                                title="Neuer Agent-Chat"
                            >
                                <FiPlus className="w-3.5 h-3.5" />
                            </button>
                        </button>
                        {agentExpanded && (
                            <div className="space-y-0.5 mt-1">
                                {agentSessions.map((session) => (
                                    <div
                                        key={session.id}
                                        onClick={() => handleSelectSession(session, 'agent')}
                                        className={`group flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-dark-400 hover:text-white hover:bg-dark-800 cursor-pointer transition-colors ${activeAgentSession?.id === session.id && activeView === 'agent' ? 'bg-rose-600/10 text-rose-300 border border-rose-600/20' : ''}`}
                                    >
                                        <FiCpu className="w-3.5 h-3.5 flex-shrink-0 text-rose-400" />
                                        {renamingSession === session.id ? (
                                            <input
                                                type="text"
                                                value={renameValue}
                                                onChange={(e) => setRenameValue(e.target.value)}
                                                onKeyDown={(e) => {
                                                    if (e.key === 'Enter') handleRenameSession(session.id, 'agent');
                                                    if (e.key === 'Escape') { setRenamingSession(null); setRenameValue(''); }
                                                }}
                                                onBlur={() => handleRenameSession(session.id, 'agent')}
                                                onClick={(e) => e.stopPropagation()}
                                                className="flex-1 px-1 py-0 text-sm bg-dark-950 border border-rose-500 rounded text-white focus:outline-none min-w-0"
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
                                                onClick={(e) => handleDeleteSession(e, session.id, 'agent')}
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
                        onClick={() => setBackupOpen(true)}
                        className="flex items-center gap-2 w-full px-3 py-2 text-sm text-dark-500 hover:text-white hover:bg-dark-800 rounded-lg transition-colors"
                    >
                        <FiHardDrive className="w-4 h-4" />
                        Backups
                    </button>
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
            <BackupModal open={backupOpen} onClose={() => setBackupOpen(false)} />
        </>
    );
}
