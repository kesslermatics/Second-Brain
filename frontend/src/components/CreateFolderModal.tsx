'use client';

import { useState } from 'react';
import { FiX } from 'react-icons/fi';
import { createFolder } from '@/lib/api';
import { useStore } from '@/lib/store';

interface Props {
    onClose: () => void;
}

export default function CreateFolderModal({ onClose }: Props) {
    const [name, setName] = useState('');
    const [loading, setLoading] = useState(false);
    const { loadFolderTree } = useStore();

    const handleCreate = async () => {
        if (!name.trim()) return;
        setLoading(true);
        try {
            await createFolder(name.trim());
            await loadFolderTree();
            onClose();
        } catch (e) {
            console.error(e);
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={onClose}>
            <div className="bg-dark-900 rounded-2xl border border-dark-800 p-6 w-full max-w-sm" onClick={(e) => e.stopPropagation()}>
                <div className="flex items-center justify-between mb-4">
                    <h3 className="text-lg font-semibold text-white">Neuer Ordner</h3>
                    <button onClick={onClose} className="p-1 hover:bg-dark-800 rounded-lg">
                        <FiX className="w-5 h-5 text-dark-500" />
                    </button>
                </div>
                <input
                    type="text"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
                    placeholder="Ordnername..."
                    className="w-full px-4 py-3 bg-dark-950 border border-dark-700 rounded-xl text-white placeholder-dark-600 focus:outline-none focus:border-brain-500 mb-4"
                    autoFocus
                />
                <div className="flex justify-end gap-2">
                    <button onClick={onClose} className="px-4 py-2 text-sm text-dark-400 hover:text-white transition-colors">
                        Abbrechen
                    </button>
                    <button
                        onClick={handleCreate}
                        disabled={!name.trim() || loading}
                        className="px-4 py-2 text-sm bg-brain-600 hover:bg-brain-500 text-white rounded-lg transition-colors disabled:opacity-50"
                    >
                        {loading ? 'Erstellt...' : 'Erstellen'}
                    </button>
                </div>
            </div>
        </div>
    );
}
