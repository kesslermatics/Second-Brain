'use client';

import { useEffect, useState } from 'react';
import { useStore } from '@/lib/store';
import { FiBookOpen, FiFolderPlus, FiFilePlus } from 'react-icons/fi';
import NoteViewer from './NoteViewer';
import CreateFolderModal from './CreateFolderModal';
import { createNote, createFolder as createFolderApi } from '@/lib/api';

export default function NotesView() {
    const { selectedNote, folderTree, loadFolderTree, setSelectedNote, setActiveView, setPendingEdit } = useStore();
    const [showCreateFolder, setShowCreateFolder] = useState(false);

    useEffect(() => {
        loadFolderTree();
    }, [loadFolderTree]);

    const handleQuickCreateNote = async () => {
        // Create note in first available folder, or create a "Notizen" folder first
        let folderId: string;
        if (folderTree.length > 0) {
            folderId = folderTree[0].id;
        } else {
            const folder = await createFolderApi('Notizen');
            folderId = folder.id;
            await loadFolderTree();
        }
        try {
            const note = await createNote('Neue Notiz', '', folderId);
            setSelectedNote(note);
            setPendingEdit(true);
            await loadFolderTree();
        } catch (e) {
            console.error(e);
        }
    };

    if (!selectedNote) {
        return (
            <div className="h-full flex items-center justify-center">
                <div className="text-center">
                    <div className="inline-flex items-center justify-center w-20 h-20 rounded-2xl bg-dark-800 mb-6">
                        <FiBookOpen className="w-10 h-10 text-dark-600" />
                    </div>
                    <h3 className="text-xl font-semibold text-white mb-2">Keine Notiz ausgewählt</h3>
                    <p className="text-sm text-dark-500 max-w-sm mb-6">
                        Wähle eine Notiz aus der Ordnerstruktur in der Seitenleiste aus, oder erstelle eine neue.
                    </p>
                    <div className="flex gap-3 justify-center">
                        <button
                            onClick={handleQuickCreateNote}
                            className="flex items-center gap-2 px-4 py-2 text-sm bg-brain-600 hover:bg-brain-500 text-white rounded-lg transition-colors"
                        >
                            <FiFilePlus className="w-4 h-4" />
                            Neue Notiz
                        </button>
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
