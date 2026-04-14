'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useStore } from '@/lib/store';
import { getMe } from '@/lib/api';
import Sidebar from '@/components/Sidebar';
import ChatView from '@/components/ChatView';
import NotesView from '@/components/NotesView';

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

    return (
        <div className="h-screen flex overflow-hidden bg-dark-950">
            <Sidebar />
            <main className="flex-1 overflow-hidden">
                {activeView === 'chat' ? <ChatView /> : <NotesView />}
            </main>
        </div>
    );
}
