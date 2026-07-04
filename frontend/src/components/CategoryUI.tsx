'use client';

import { categoryStyle } from '@/lib/categories';

// ── Category badge ───────────────────────────────────────────────────
export function CategoryBadge({
    category,
    size = 'sm',
}: {
    category?: string | null;
    size?: 'xs' | 'sm';
}) {
    if (!category) return null;
    const s = categoryStyle(category);
    const pad = size === 'xs' ? 'px-1.5 py-0.5 text-[9px]' : 'px-2 py-0.5 text-[10px]';
    return (
        <span className={`inline-flex items-center gap-1 rounded-full border font-medium ${pad} ${s.bg} ${s.text} ${s.border}`}>
            <span className={`w-1.5 h-1.5 rounded-full ${s.dot}`} />
            {s.label}
        </span>
    );
}

// ── Category filter pills ────────────────────────────────────────────
// Shows only the categories that actually occur, plus "Alle". Controlled.
export function CategoryFilter({
    categories,
    active,
    onSelect,
    accentActive = 'bg-teal-600 text-white border-teal-500',
}: {
    categories: string[];
    active: string | null;
    onSelect: (category: string | null) => void;
    accentActive?: string;
}) {
    if (categories.length <= 1) return null;
    return (
        <div className="flex flex-wrap gap-1.5">
            <button
                onClick={() => onSelect(null)}
                className={`px-2.5 py-1 text-[11px] font-medium rounded-full border transition-colors ${active === null ? accentActive : 'bg-dark-800 text-dark-400 border-dark-700 hover:text-white hover:border-dark-600'}`}
            >
                Alle
            </button>
            {categories.map((cat) => {
                const s = categoryStyle(cat);
                const isActive = active === cat;
                return (
                    <button
                        key={cat}
                        onClick={() => onSelect(isActive ? null : cat)}
                        className={`inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-medium rounded-full border transition-colors ${isActive ? `${s.bg} ${s.text} ${s.border}` : 'bg-dark-800 text-dark-400 border-dark-700 hover:text-white hover:border-dark-600'}`}
                    >
                        <span className={`w-1.5 h-1.5 rounded-full ${s.dot}`} />
                        {s.label}
                    </button>
                );
            })}
        </div>
    );
}
