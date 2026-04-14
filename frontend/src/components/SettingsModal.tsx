'use client';

import { useState, useEffect } from 'react';
import { FiX, FiRefreshCw, FiSave, FiInfo } from 'react-icons/fi';
import { getSettings, updateSettings, resetSettings } from '@/lib/api';
import type { UserSettings } from '@/lib/types';

interface SettingsModalProps {
    isOpen: boolean;
    onClose: () => void;
}

const PROMPT_INFO = {
    note: {
        label: 'Notizen-Prompt',
        description: 'Wird verwendet, wenn du Notizen einreichst. Platzhalter: {{ORDNERSTRUKTUR}}, {{BENUTZEREINGABE}}',
    },
    qa: {
        label: 'Fragen & Antworten-Prompt',
        description: 'Wird für RAG-basierte Fragen verwendet. Platzhalter: {{KONTEXT}}, {{CHATVERLAUF}}, {{FRAGE}}',
    },
    edit: {
        label: 'Notiz-Bearbeitung-Prompt',
        description: 'Wird für KI-gestützte Notizbearbeitung verwendet. Platzhalter: {{AKTUELLE_NOTIZ}}, {{ANWEISUNG}}',
    },
};

export default function SettingsModal({ isOpen, onClose }: SettingsModalProps) {
    const [settings, setSettings] = useState<UserSettings | null>(null);
    const [notePrompt, setNotePrompt] = useState('');
    const [qaPrompt, setQaPrompt] = useState('');
    const [editPrompt, setEditPrompt] = useState('');
    const [loading, setLoading] = useState(false);
    const [saving, setSaving] = useState(false);
    const [saved, setSaved] = useState(false);
    const [activeTab, setActiveTab] = useState<'note' | 'qa' | 'edit'>('note');

    useEffect(() => {
        if (isOpen) {
            loadSettings();
        }
    }, [isOpen]);

    const loadSettings = async () => {
        setLoading(true);
        try {
            const data = await getSettings();
            setSettings(data);
            setNotePrompt(data.note_prompt || data.note_prompt_default);
            setQaPrompt(data.qa_prompt || data.qa_prompt_default);
            setEditPrompt(data.edit_prompt || data.edit_prompt_default);
        } catch (e) {
            console.error('Failed to load settings:', e);
        } finally {
            setLoading(false);
        }
    };

    const handleSave = async () => {
        if (!settings) return;
        setSaving(true);
        try {
            const payload: Record<string, string | null> = {};

            // Only send custom prompt if different from default, otherwise send empty string to clear
            if (notePrompt !== settings.note_prompt_default) {
                payload.note_prompt = notePrompt;
            } else {
                payload.note_prompt = '';
            }
            if (qaPrompt !== settings.qa_prompt_default) {
                payload.qa_prompt = qaPrompt;
            } else {
                payload.qa_prompt = '';
            }
            if (editPrompt !== settings.edit_prompt_default) {
                payload.edit_prompt = editPrompt;
            } else {
                payload.edit_prompt = '';
            }

            const data = await updateSettings(payload);
            setSettings(data);
            setSaved(true);
            setTimeout(() => setSaved(false), 2000);
        } catch (e) {
            console.error('Failed to save settings:', e);
        } finally {
            setSaving(false);
        }
    };

    const handleResetAll = async () => {
        try {
            const data = await resetSettings();
            setSettings(data);
            setNotePrompt(data.note_prompt_default);
            setQaPrompt(data.qa_prompt_default);
            setEditPrompt(data.edit_prompt_default);
            setSaved(true);
            setTimeout(() => setSaved(false), 2000);
        } catch (e) {
            console.error('Failed to reset settings:', e);
        }
    };

    const handleResetCurrent = () => {
        if (!settings) return;
        switch (activeTab) {
            case 'note':
                setNotePrompt(settings.note_prompt_default);
                break;
            case 'qa':
                setQaPrompt(settings.qa_prompt_default);
                break;
            case 'edit':
                setEditPrompt(settings.edit_prompt_default);
                break;
        }
    };

    const getCurrentPrompt = () => {
        switch (activeTab) {
            case 'note': return notePrompt;
            case 'qa': return qaPrompt;
            case 'edit': return editPrompt;
        }
    };

    const setCurrentPrompt = (value: string) => {
        switch (activeTab) {
            case 'note': setNotePrompt(value); break;
            case 'qa': setQaPrompt(value); break;
            case 'edit': setEditPrompt(value); break;
        }
    };

    const isCurrentModified = () => {
        if (!settings) return false;
        switch (activeTab) {
            case 'note': return notePrompt !== settings.note_prompt_default;
            case 'qa': return qaPrompt !== settings.qa_prompt_default;
            case 'edit': return editPrompt !== settings.edit_prompt_default;
        }
    };

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
            {/* Backdrop */}
            <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />

            {/* Modal */}
            <div className="relative w-full max-w-4xl max-h-[90vh] bg-dark-900 border border-dark-700 rounded-2xl shadow-2xl flex flex-col mx-4">
                {/* Header */}
                <div className="flex items-center justify-between px-6 py-4 border-b border-dark-700">
                    <h2 className="text-lg font-semibold text-white">Einstellungen — KI-Prompts</h2>
                    <div className="flex items-center gap-2">
                        {saved && (
                            <span className="text-sm text-green-400 animate-pulse">Gespeichert!</span>
                        )}
                        <button
                            onClick={onClose}
                            className="p-2 text-dark-400 hover:text-white hover:bg-dark-800 rounded-lg transition-colors"
                        >
                            <FiX className="w-5 h-5" />
                        </button>
                    </div>
                </div>

                {loading ? (
                    <div className="flex items-center justify-center py-20">
                        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-brain-400" />
                    </div>
                ) : (
                    <>
                        {/* Tabs */}
                        <div className="flex border-b border-dark-700">
                            {(['note', 'qa', 'edit'] as const).map((tab) => (
                                <button
                                    key={tab}
                                    onClick={() => setActiveTab(tab)}
                                    className={`flex-1 py-3 text-sm font-medium transition-colors ${
                                        activeTab === tab
                                            ? 'text-brain-400 border-b-2 border-brain-400'
                                            : 'text-dark-500 hover:text-dark-300'
                                    }`}
                                >
                                    {PROMPT_INFO[tab].label}
                                    {(() => {
                                        if (!settings) return null;
                                        const isModified = tab === 'note'
                                            ? notePrompt !== settings.note_prompt_default
                                            : tab === 'qa'
                                                ? qaPrompt !== settings.qa_prompt_default
                                                : editPrompt !== settings.edit_prompt_default;
                                        return isModified ? (
                                            <span className="ml-1.5 inline-block w-1.5 h-1.5 bg-brain-400 rounded-full" />
                                        ) : null;
                                    })()}
                                </button>
                            ))}
                        </div>

                        {/* Content */}
                        <div className="flex-1 overflow-y-auto p-6 space-y-4">
                            {/* Info */}
                            <div className="flex items-start gap-2 p-3 bg-dark-800/50 border border-dark-700 rounded-lg">
                                <FiInfo className="w-4 h-4 text-brain-400 mt-0.5 flex-shrink-0" />
                                <p className="text-sm text-dark-400">
                                    {PROMPT_INFO[activeTab].description}
                                </p>
                            </div>

                            {/* Textarea */}
                            <textarea
                                value={getCurrentPrompt()}
                                onChange={(e) => setCurrentPrompt(e.target.value)}
                                className="w-full h-[45vh] bg-dark-800 border border-dark-700 rounded-lg px-4 py-3 text-sm text-dark-200 font-mono resize-none focus:outline-none focus:border-brain-500 focus:ring-1 focus:ring-brain-500/30 transition-colors"
                                spellCheck={false}
                            />

                            {isCurrentModified() && (
                                <p className="text-xs text-brain-400">
                                    ● Angepasst — weicht vom Standard ab
                                </p>
                            )}
                        </div>

                        {/* Footer */}
                        <div className="flex items-center justify-between px-6 py-4 border-t border-dark-700">
                            <div className="flex items-center gap-2">
                                <button
                                    onClick={handleResetCurrent}
                                    className="flex items-center gap-1.5 px-3 py-2 text-sm text-dark-400 hover:text-white hover:bg-dark-800 rounded-lg transition-colors"
                                    title="Diesen Prompt zurücksetzen"
                                >
                                    <FiRefreshCw className="w-3.5 h-3.5" />
                                    Zurücksetzen
                                </button>
                                <button
                                    onClick={handleResetAll}
                                    className="flex items-center gap-1.5 px-3 py-2 text-sm text-red-400/70 hover:text-red-400 hover:bg-dark-800 rounded-lg transition-colors"
                                    title="Alle Prompts zurücksetzen"
                                >
                                    <FiRefreshCw className="w-3.5 h-3.5" />
                                    Alle zurücksetzen
                                </button>
                            </div>
                            <button
                                onClick={handleSave}
                                disabled={saving}
                                className="flex items-center gap-2 px-5 py-2 bg-brain-600 hover:bg-brain-500 text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-50"
                            >
                                <FiSave className="w-4 h-4" />
                                {saving ? 'Speichern...' : 'Speichern'}
                            </button>
                        </div>
                    </>
                )}
            </div>
        </div>
    );
}
