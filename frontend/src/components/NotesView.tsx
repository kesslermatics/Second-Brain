'use client';

import { useEffect, useState } from 'react';
import { useStore } from '@/lib/store';
import { FiBookOpen, FiFolderPlus } from 'react-icons/fi';
import NoteViewer from './NoteViewer';
import CreateFolderModal from './CreateFolderModal';

export default function NotesView() {
    const { selectedNote, folderTree, loadFolderTree } = useStore();
    const [showCreateFolder, setShowCreateFolder] = useState(false);

    useEffect(() => {
        loadFolderTree();
    }, [loadFolderTree]);

    if (!selectedNote) {
        return (
            <div className="h-full flex items-center justify-center">
                <div className="text-center">
                    <div className="inline-flex items-center justify-center w-20 h-20 rounded-2xl bg-dark-800 mb-6">
                        <FiBookOpen className="w-10 h-10 text-dark-600" />
                    </div>
                    <h3 className="text-xl font-semibold text-white mb-2">Keine Notiz ausgewählt</h3>
                    <p className="text-sm text-dark-500 max-w-sm mb-6">
                        Wähle eine Notiz aus der Ordnerstruktur in der Seitenleiste aus, oder erstelle eine neue über den Notizen-Chat.
                    </p>
                    <div className="flex gap-3 justify-center">
                        <button
                            onClick={() => setShowCreateFolder(true)}
                            className="flex items-center gap-2 px-4 py-2 text-sm bg-dark-800 hover:bg-dark-700 border border-dark-700 text-white rounded-lg transition-colors"
                        >
                            <FiFolderPlus className="w-4 h-4" />
                            Ordner erstellen
                        </button>
                    </div>
                    {showCreateFolder && (
                        <CreateFolderModal onClose={() => setShowCreateFolder(false)} />
                    )}
                </div>
            </div>
        );
    }

    return <NoteViewer />;
}
