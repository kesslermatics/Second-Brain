// Canonical content categories — keep in sync with backend/app/categories.py.
// Each category maps to a colour used for badges/filters in the Teacher & Book UIs.

export interface CategoryStyle {
    label: string;
    // Tailwind classes (explicit so Tailwind can see them at build time)
    text: string;
    bg: string;
    border: string;
    dot: string;
}

export const CATEGORY_ORDER: string[] = [
    'Produktivität',
    'Persönliche Finanzen',
    'Business & Unternehmertum',
    'Selbstentwicklung',
    'Kritisches Denken',
    'Beziehungen',
    'Menschliches Verhalten',
    'Philosophie',
    'Disziplin & Gewohnheiten',
    'Kommunikation',
    'Psychologie',
    'Führung',
    'Gesundheit & Fitness',
    'Achtsamkeit & Spiritualität',
    'Kreativität',
    'Lernen & Gedächtnis',
    'Wissenschaft & Technik',
    'Geschichte',
    'Wirtschaft & Gesellschaft',
    'Marketing & Verkauf',
    'Sonstiges',
];

const C = (text: string, bg: string, border: string, dot: string): Omit<CategoryStyle, 'label'> =>
    ({ text, bg, border, dot });

const STYLES: Record<string, Omit<CategoryStyle, 'label'>> = {
    'Produktivität': C('text-sky-300', 'bg-sky-500/15', 'border-sky-500/30', 'bg-sky-400'),
    'Persönliche Finanzen': C('text-emerald-300', 'bg-emerald-500/15', 'border-emerald-500/30', 'bg-emerald-400'),
    'Business & Unternehmertum': C('text-amber-300', 'bg-amber-500/15', 'border-amber-500/30', 'bg-amber-400'),
    'Selbstentwicklung': C('text-teal-300', 'bg-teal-500/15', 'border-teal-500/30', 'bg-teal-400'),
    'Kritisches Denken': C('text-indigo-300', 'bg-indigo-500/15', 'border-indigo-500/30', 'bg-indigo-400'),
    'Beziehungen': C('text-rose-300', 'bg-rose-500/15', 'border-rose-500/30', 'bg-rose-400'),
    'Menschliches Verhalten': C('text-orange-300', 'bg-orange-500/15', 'border-orange-500/30', 'bg-orange-400'),
    'Philosophie': C('text-violet-300', 'bg-violet-500/15', 'border-violet-500/30', 'bg-violet-400'),
    'Disziplin & Gewohnheiten': C('text-red-300', 'bg-red-500/15', 'border-red-500/30', 'bg-red-400'),
    'Kommunikation': C('text-cyan-300', 'bg-cyan-500/15', 'border-cyan-500/30', 'bg-cyan-400'),
    'Psychologie': C('text-fuchsia-300', 'bg-fuchsia-500/15', 'border-fuchsia-500/30', 'bg-fuchsia-400'),
    'Führung': C('text-yellow-300', 'bg-yellow-500/15', 'border-yellow-500/30', 'bg-yellow-400'),
    'Gesundheit & Fitness': C('text-lime-300', 'bg-lime-500/15', 'border-lime-500/30', 'bg-lime-400'),
    'Achtsamkeit & Spiritualität': C('text-purple-300', 'bg-purple-500/15', 'border-purple-500/30', 'bg-purple-400'),
    'Kreativität': C('text-pink-300', 'bg-pink-500/15', 'border-pink-500/30', 'bg-pink-400'),
    'Lernen & Gedächtnis': C('text-blue-300', 'bg-blue-500/15', 'border-blue-500/30', 'bg-blue-400'),
    'Wissenschaft & Technik': C('text-green-300', 'bg-green-500/15', 'border-green-500/30', 'bg-green-400'),
    'Geschichte': C('text-stone-300', 'bg-stone-500/15', 'border-stone-500/30', 'bg-stone-400'),
    'Wirtschaft & Gesellschaft': C('text-emerald-300', 'bg-emerald-500/15', 'border-emerald-500/30', 'bg-emerald-400'),
    'Marketing & Verkauf': C('text-orange-300', 'bg-orange-500/15', 'border-orange-500/30', 'bg-orange-400'),
    'Sonstiges': C('text-dark-300', 'bg-dark-700/60', 'border-dark-600', 'bg-dark-400'),
};

const FALLBACK = STYLES['Sonstiges'];

export function categoryStyle(category?: string | null): CategoryStyle {
    const label = category || 'Sonstiges';
    const style = STYLES[label] || FALLBACK;
    return { label, ...style };
}
