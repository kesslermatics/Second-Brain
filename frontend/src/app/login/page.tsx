'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { login as apiLogin, getMe } from '@/lib/api';
import { useStore } from '@/lib/store';
import { FiMail, FiLock, FiLogIn } from 'react-icons/fi';
import { LuBrain } from 'react-icons/lu';

export default function LoginPage() {
    const router = useRouter();
    const { setToken, setUser } = useStore();
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError('');
        setLoading(true);

        try {
            const { access_token } = await apiLogin(email, password);
            setToken(access_token);
            const user = await getMe();
            setUser(user);
            router.push('/dashboard');
        } catch (err: any) {
            setError(err.response?.data?.detail || 'Login fehlgeschlagen');
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="min-h-screen flex items-center justify-center bg-dark-950 px-4">
            <div className="w-full max-w-md">
                <div className="text-center mb-8">
                    <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-brain-600/20 mb-4">
                        <LuBrain className="w-8 h-8 text-brain-400" />
                    </div>
                    <h1 className="text-3xl font-bold text-white">Brain</h1>
                    <p className="text-dark-500 mt-2">Dein intelligentes Second Brain</p>
                </div>

                <form onSubmit={handleSubmit} className="bg-dark-900 rounded-2xl border border-dark-800 p-8 shadow-xl">
                    {error && (
                        <div className="mb-4 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
                            {error}
                        </div>
                    )}

                    <div className="mb-5">
                        <label className="block text-sm font-medium text-dark-400 mb-2">E-Mail</label>
                        <div className="relative">
                            <FiMail className="absolute left-3 top-1/2 -translate-y-1/2 text-dark-500 w-5 h-5" />
                            <input
                                type="email"
                                value={email}
                                onChange={(e) => setEmail(e.target.value)}
                                placeholder="deine@email.com"
                                className="w-full pl-11 pr-4 py-3 bg-dark-950 border border-dark-700 rounded-xl text-white placeholder-dark-600 focus:outline-none focus:border-brain-500 focus:ring-1 focus:ring-brain-500 transition-colors"
                                required
                            />
                        </div>
                    </div>

                    <div className="mb-6">
                        <label className="block text-sm font-medium text-dark-400 mb-2">Passwort</label>
                        <div className="relative">
                            <FiLock className="absolute left-3 top-1/2 -translate-y-1/2 text-dark-500 w-5 h-5" />
                            <input
                                type="password"
                                value={password}
                                onChange={(e) => setPassword(e.target.value)}
                                placeholder="••••••••"
                                className="w-full pl-11 pr-4 py-3 bg-dark-950 border border-dark-700 rounded-xl text-white placeholder-dark-600 focus:outline-none focus:border-brain-500 focus:ring-1 focus:ring-brain-500 transition-colors"
                                required
                            />
                        </div>
                    </div>

                    <button
                        type="submit"
                        disabled={loading}
                        className="w-full flex items-center justify-center gap-2 py-3 px-4 bg-brain-600 hover:bg-brain-500 text-white font-medium rounded-xl transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                        {loading ? (
                            <div className="animate-spin w-5 h-5 border-2 border-white border-t-transparent rounded-full" />
                        ) : (
                            <>
                                <FiLogIn className="w-5 h-5" />
                                Anmelden
                            </>
                        )}
                    </button>
                </form>
            </div>
        </div>
    );
}
