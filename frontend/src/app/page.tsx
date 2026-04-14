'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useStore } from '@/lib/store';
import { getMe } from '@/lib/api';

export default function Home() {
    const router = useRouter();
    const { token, setUser } = useStore();

    useEffect(() => {
        const checkAuth = async () => {
            if (!token) {
                router.push('/login');
                return;
            }
            try {
                const user = await getMe();
                setUser(user);
                router.push('/dashboard');
            } catch {
                router.push('/login');
            }
        };
        checkAuth();
    }, [token, router, setUser]);

    return (
        <div className="min-h-screen flex items-center justify-center bg-dark-950">
            <div className="text-center">
                <div className="animate-spin w-8 h-8 border-2 border-brain-500 border-t-transparent rounded-full mx-auto mb-4" />
                <p className="text-dark-500">Loading...</p>
            </div>
        </div>
    );
}
