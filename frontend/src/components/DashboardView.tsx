'use client';

import { useState, useEffect, useCallback } from 'react';
import {
    FiFileText, FiFolder, FiTag, FiBookOpen, FiEdit3,
    FiTrendingUp, FiCalendar, FiRefreshCw,
} from 'react-icons/fi';
import { LuBrain } from 'react-icons/lu';
import { getDashboard } from '@/lib/api';
import type { DashboardData } from '@/lib/types';
import {
    BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
    AreaChart, Area,
} from 'recharts';

export default function DashboardView() {
    const [data, setData] = useState<DashboardData | null>(null);
    const [loading, setLoading] = useState(true);

    const loadDashboard = useCallback(async () => {
        setLoading(true);
        try {
            const d = await getDashboard();
            setData(d);
        } catch (e) {
            console.error(e);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        loadDashboard();
    }, [loadDashboard]);

    if (loading || !data) {
        return (
            <div className="h-full flex items-center justify-center">
                <div className="animate-spin w-8 h-8 border-2 border-brain-500 border-t-transparent rounded-full" />
            </div>
        );
    }

    const statCards = [
        { label: 'Notizen', value: data.total_notes, icon: FiFileText, color: 'text-brain-400', bg: 'bg-brain-600/20' },
        { label: 'Ordner', value: data.total_folders, icon: FiFolder, color: 'text-blue-400', bg: 'bg-blue-600/20' },
        { label: 'Tags', value: data.total_tags, icon: FiTag, color: 'text-green-400', bg: 'bg-green-600/20' },
        { label: 'Karteikarten', value: data.total_flashcards, icon: FiBookOpen, color: 'text-orange-400', bg: 'bg-orange-600/20' },
        { label: 'Wörter', value: data.total_words.toLocaleString('de-DE'), icon: FiEdit3, color: 'text-purple-400', bg: 'bg-purple-600/20' },
        { label: 'Diese Woche', value: data.notes_this_week, icon: FiTrendingUp, color: 'text-cyan-400', bg: 'bg-cyan-600/20' },
    ];

    // Last 30 days from heatmap
    const last30 = data.activity_heatmap.slice(-30).map(d => ({
        date: new Date(d.date).toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit' }),
        count: d.count,
    }));

    return (
        <div className="h-full flex flex-col">
            {/* Header */}
            <div className="flex items-center justify-between px-4 sm:px-6 py-4 border-b border-dark-800 bg-dark-900/50">
                <div className="flex items-center gap-3">
                    <div className="p-2 bg-brain-600/20 rounded-xl">
                        <LuBrain className="w-5 h-5 text-brain-400" />
                    </div>
                    <div>
                        <h1 className="text-lg font-semibold text-white">Dashboard</h1>
                        <p className="text-xs text-dark-500">Übersicht deines Second Brain</p>
                    </div>
                </div>
                <button
                    onClick={loadDashboard}
                    className="p-2 hover:bg-dark-800 rounded-lg transition-colors text-dark-400 hover:text-white"
                >
                    <FiRefreshCw className="w-4 h-4" />
                </button>
            </div>

            <div className="flex-1 overflow-y-auto p-4 sm:p-6">
                <div className="max-w-6xl mx-auto space-y-6">
                    {/* Stat cards */}
                    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
                        {statCards.map((s) => (
                            <div key={s.label} className="bg-dark-800/50 border border-dark-700 rounded-xl p-4">
                                <div className={`inline-flex p-2 ${s.bg} rounded-lg mb-3`}>
                                    <s.icon className={`w-4 h-4 ${s.color}`} />
                                </div>
                                <p className="text-2xl font-bold text-white">{s.value}</p>
                                <p className="text-xs text-dark-500 mt-0.5">{s.label}</p>
                            </div>
                        ))}
                    </div>

                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                        {/* Activity */}
                        <div className="bg-dark-800/50 border border-dark-700 rounded-xl p-5">
                            <div className="flex items-center gap-2 mb-4">
                                <FiCalendar className="w-4 h-4 text-brain-400" />
                                <h2 className="text-sm font-semibold text-white">Aktivität (letzte 30 Tage)</h2>
                            </div>
                            <div className="h-48">
                                <ResponsiveContainer width="100%" height="100%">
                                    <AreaChart data={last30}>
                                        <defs>
                                            <linearGradient id="gradient" x1="0" y1="0" x2="0" y2="1">
                                                <stop offset="0%" stopColor="#8b5cf6" stopOpacity={0.3} />
                                                <stop offset="100%" stopColor="#8b5cf6" stopOpacity={0} />
                                            </linearGradient>
                                        </defs>
                                        <XAxis
                                            dataKey="date"
                                            tick={{ fill: '#6b7280', fontSize: 10 }}
                                            axisLine={false}
                                            tickLine={false}
                                            interval={4}
                                        />
                                        <YAxis
                                            tick={{ fill: '#6b7280', fontSize: 10 }}
                                            axisLine={false}
                                            tickLine={false}
                                            allowDecimals={false}
                                        />
                                        <Tooltip
                                            contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: '8px', fontSize: 12 }}
                                            labelStyle={{ color: '#9ca3af' }}
                                            itemStyle={{ color: '#a78bfa' }}
                                        />
                                        <Area
                                            type="monotone"
                                            dataKey="count"
                                            stroke="#8b5cf6"
                                            strokeWidth={2}
                                            fill="url(#gradient)"
                                            name="Notizen"
                                        />
                                    </AreaChart>
                                </ResponsiveContainer>
                            </div>
                        </div>

                        {/* Top folders */}
                        <div className="bg-dark-800/50 border border-dark-700 rounded-xl p-5">
                            <div className="flex items-center gap-2 mb-4">
                                <FiFolder className="w-4 h-4 text-blue-400" />
                                <h2 className="text-sm font-semibold text-white">Top Ordner</h2>
                            </div>
                            <div className="h-48">
                                <ResponsiveContainer width="100%" height="100%">
                                    <BarChart data={data.top_folders.slice(0, 6)} layout="vertical">
                                        <XAxis
                                            type="number"
                                            tick={{ fill: '#6b7280', fontSize: 10 }}
                                            axisLine={false}
                                            tickLine={false}
                                            allowDecimals={false}
                                        />
                                        <YAxis
                                            type="category"
                                            dataKey="name"
                                            tick={{ fill: '#9ca3af', fontSize: 11 }}
                                            axisLine={false}
                                            tickLine={false}
                                            width={120}
                                        />
                                        <Tooltip
                                            contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: '8px', fontSize: 12 }}
                                            labelStyle={{ color: '#9ca3af' }}
                                            itemStyle={{ color: '#60a5fa' }}
                                        />
                                        <Bar dataKey="count" fill="#3b82f6" radius={[0, 4, 4, 0]} name="Notizen" />
                                    </BarChart>
                                </ResponsiveContainer>
                            </div>
                        </div>

                        {/* Top tags */}
                        <div className="bg-dark-800/50 border border-dark-700 rounded-xl p-5">
                            <div className="flex items-center gap-2 mb-4">
                                <FiTag className="w-4 h-4 text-green-400" />
                                <h2 className="text-sm font-semibold text-white">Top Tags</h2>
                            </div>
                            {data.top_tags.length === 0 ? (
                                <p className="text-sm text-dark-500 py-8 text-center">Noch keine Tags vorhanden</p>
                            ) : (
                                <div className="h-48">
                                    <ResponsiveContainer width="100%" height="100%">
                                        <BarChart data={data.top_tags.slice(0, 6)} layout="vertical">
                                            <XAxis
                                                type="number"
                                                tick={{ fill: '#6b7280', fontSize: 10 }}
                                                axisLine={false}
                                                tickLine={false}
                                                allowDecimals={false}
                                            />
                                            <YAxis
                                                type="category"
                                                dataKey="name"
                                                tick={{ fill: '#9ca3af', fontSize: 11 }}
                                                axisLine={false}
                                                tickLine={false}
                                                width={120}
                                            />
                                            <Tooltip
                                                contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: '8px', fontSize: 12 }}
                                                labelStyle={{ color: '#9ca3af' }}
                                                itemStyle={{ color: '#34d399' }}
                                            />
                                            <Bar dataKey="count" fill="#10b981" radius={[0, 4, 4, 0]} name="Notizen" />
                                        </BarChart>
                                    </ResponsiveContainer>
                                </div>
                            )}
                        </div>

                        {/* SR stats */}
                        <div className="bg-dark-800/50 border border-dark-700 rounded-xl p-5">
                            <div className="flex items-center gap-2 mb-4">
                                <FiBookOpen className="w-4 h-4 text-orange-400" />
                                <h2 className="text-sm font-semibold text-white">Lernfortschritt</h2>
                            </div>
                            <div className="grid grid-cols-2 gap-4">
                                <div className="bg-dark-900 rounded-xl p-4 text-center">
                                    <p className="text-3xl font-bold text-white">{data.sr_stats.total}</p>
                                    <p className="text-xs text-dark-500">Gesamt</p>
                                </div>
                                <div className="bg-dark-900 rounded-xl p-4 text-center">
                                    <p className="text-3xl font-bold text-orange-400">{data.sr_stats.due}</p>
                                    <p className="text-xs text-dark-500">Fällig</p>
                                </div>
                                <div className="bg-dark-900 rounded-xl p-4 text-center">
                                    <p className="text-3xl font-bold text-green-400">{data.sr_stats.mastered}</p>
                                    <p className="text-xs text-dark-500">Gemeistert</p>
                                </div>
                                <div className="bg-dark-900 rounded-xl p-4 text-center">
                                    <p className="text-3xl font-bold text-blue-400">{data.sr_stats.learning}</p>
                                    <p className="text-xs text-dark-500">Lernend</p>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
