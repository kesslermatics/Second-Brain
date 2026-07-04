'use client';

import { categoryStyle } from '@/lib/categories';

// Category colours are applied as inline hex styles (not Tailwind classes) so
// every category renders correctly regardless of the JIT content scan.
function hexBg(hex: string, alpha = '26') {
    // alpha as 2-digit hex (26 ≈ 15%)
    return `${hex}${alpha}`;
}

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
        <span
            className={`inline-flex items-center gap-1.5 rounded-full border font-medium ${pad}`}
            style={{
                backgroundColor: hexBg(s.hex),
                borderColor: `${s.hex}55`,
                color: s.hex,
            }}
        >
            <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: s.hex }} />
            {s.label}
        </span>
    );
}

// ── Status badge (Aktiv / Entwurf / Abgeschlossen / Vertiefung) ──────
type StatusKind = 'active' | 'draft' | 'completed' | 'deepening';

const STATUS_STYLE: Record<StatusKind, { label: string; hex: string }> = {
    active: { label: 'Aktiv', hex: '#2dd4bf' },
    draft: { label: 'Entwurf', hex: '#60a5fa' },
    completed: { label: 'Abgeschlossen', hex: '#4ade80' },
    deepening: { label: 'Vertiefung', hex: '#c084fc' },
};

export function StatusBadge({ kind }: { kind: StatusKind }) {
    const s = STATUS_STYLE[kind];
    return (
        <span
            className="inline-flex items-center gap-1.5 px-2 py-0.5 text-[10px] font-medium rounded-full border"
            style={{
                backgroundColor: hexBg(s.hex),
                borderColor: `${s.hex}55`,
                color: s.hex,
            }}
        >
            <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: s.hex }} />
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
}: {
    categories: string[];
    active: string | null;
    onSelect: (category: string | null) => void;
    // kept for backwards compat; no longer used (accent comes from the category)
    accentActive?: string;
}) {
    if (categories.length <= 1) return null;
    return (
        <div className="flex flex-wrap gap-1.5">
            <button
                onClick={() => onSelect(null)}
                className={`px-3 py-1 text-[11px] font-medium rounded-full border transition-colors ${active === null
                    ? 'bg-white/10 text-white border-white/20'
                    : 'bg-dark-800 text-dark-400 border-dark-700 hover:text-white hover:border-dark-600'}`}
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
                        className="inline-flex items-center gap-1.5 px-3 py-1 text-[11px] font-medium rounded-full border transition-colors"
                        style={
                            isActive
                                ? { backgroundColor: hexBg(s.hex), borderColor: `${s.hex}66`, color: s.hex }
                                : { backgroundColor: 'rgba(52,58,64,0.4)', borderColor: '#343a40', color: '#adb5bd' }
                        }
                    >
                        <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: s.hex }} />
                        {s.label}
                    </button>
                );
            })}
        </div>
    );
}
