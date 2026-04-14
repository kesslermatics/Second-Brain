'use client';

import { useStore } from '@/lib/store';
import ChatPanel from './ChatPanel';
import { FiEdit3, FiHelpCircle } from 'react-icons/fi';

export default function ChatView() {
    const { activeNotesSession, activeQASession } = useStore();

    return (
        <div className="h-full flex">
            {/* Left - Notes Chat */}
            <div className="flex-1 flex flex-col border-r border-dark-800">
                <div className="flex items-center gap-2 px-4 py-3 border-b border-dark-800 bg-dark-900/50">
                    <FiEdit3 className="w-4 h-4 text-brain-400" />
                    <h2 className="text-sm font-semibold text-white">Notizen erstellen</h2>
                    <span className="text-xs text-dark-500 ml-2">
                        Gib deine Notizen ein — die KI strukturiert und speichert sie
                    </span>
                </div>
                <div className="flex-1 overflow-hidden">
                    <ChatPanel session={activeNotesSession} type="notes" />
                </div>
            </div>

            {/* Right - QA Chat */}
            <div className="flex-1 flex flex-col">
                <div className="flex items-center gap-2 px-4 py-3 border-b border-dark-800 bg-dark-900/50">
                    <FiHelpCircle className="w-4 h-4 text-green-400" />
                    <h2 className="text-sm font-semibold text-white">Fragen & Antworten</h2>
                    <span className="text-xs text-dark-500 ml-2">
                        Stelle Fragen — die KI durchsucht dein Second Brain
                    </span>
                </div>
                <div className="flex-1 overflow-hidden">
                    <ChatPanel session={activeQASession} type="qa" />
                </div>
            </div>
        </div>
    );
}
