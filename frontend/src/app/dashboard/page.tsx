'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useStore } from '@/lib/store';
import { getMe } from '@/lib/api';
import Sidebar from '@/components/Sidebar';
import ChatView from '@/components/ChatView';
import NotesView from '@/components/NotesView';
import SearchView from '@/components/SearchView';
import DashboardView from '@/components/DashboardView';
import KnowledgeGraphView from '@/components/KnowledgeGraphView';
import SpacedRepView from '@/components/SpacedRepView';
import ExportView from '@/components/ExportView';
import SummaryView from '@/components/SummaryView';
import ImageGallery from '@/components/ImageGallery';
import BookPanel from '@/components/BookPanel';
import TeacherPanel from '@/components/TeacherPanel';

export default function DashboardPage() {
    const router = useRouter();
    const { token, user, setUser, activeView, isAuthenticated } = useStore();
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const checkAuth = async () => {
            if (!token) {
                router.push('/login');
                return;
            }
            try {
                const userData = await getMe();
                setUser(userData);
            } catch {
                router.push('/login');
            } finally {
                setLoading(false);
            }
        };
        checkAuth();
    }, [token, router, setUser]);

    if (loading) {
        return (
            <div className="min-h-screen flex items-center justify-center bg-dark-950">
                <div className="animate-spin w-8 h-8 border-2 border-brain-500 border-t-transparent rounded-full" />
            </div>
        );
    }

    if (!isAuthenticated) return null;

    const renderView = () => {
        switch (activeView) {
            case 'chat': return <ChatView />;
            case 'notes': return <NotesView />;
            case 'search': return <SearchView />;
            case 'dashboard': return <DashboardView />;
            case 'graph': return <KnowledgeGraphView />;
            case 'learn': return <SpacedRepView />;
            case 'export': return <ExportView />;
            case 'summary': return <SummaryView />;
            case 'images': return <ImageGallery />;
            case 'books': return <BookPanel />;
            case 'teacher': return <TeacherPanel />;
            default: return <ChatView />;
        }
    };

    return (
        <div className="h-screen flex overflow-hidden bg-dark-950">
            <Sidebar />
            <main className="flex-1 overflow-hidden pt-12 lg:pt-0">
                {renderView()}
            </main>
        </div>
    );
}
