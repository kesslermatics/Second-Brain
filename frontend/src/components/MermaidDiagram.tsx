'use client';

import { useEffect, useRef, useState } from 'react';

// ── Mermaid diagram with a silent fallback ───────────────────────────
// The tutor only draws diagrams for clearly structural topics, but LLM-generated
// Mermaid can still occasionally be malformed. If it doesn't parse/render, we
// render nothing (no broken image, no error text) — the surrounding prose stands
// on its own.

let mermaidLoaded = false;

async function getMermaid() {
    const mod = await import('mermaid');
    const mermaid = mod.default;
    if (!mermaidLoaded) {
        mermaid.initialize({
            startOnLoad: false,
            theme: 'dark',
            securityLevel: 'strict',
            fontFamily: 'inherit',
        });
        mermaidLoaded = true;
    }
    return mermaid;
}

export default function MermaidDiagram({ code, caption }: { code: string; caption?: string }) {
    const [svg, setSvg] = useState<string | null>(null);
    const [failed, setFailed] = useState(false);
    const idRef = useRef(`mmd-${Math.random().toString(36).slice(2)}`);

    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                const mermaid = await getMermaid();
                // Validate first so a parse error doesn't throw uncaught.
                await mermaid.parse(code);
                const { svg } = await mermaid.render(idRef.current, code);
                if (!cancelled) setSvg(svg);
            } catch {
                if (!cancelled) setFailed(true);
            }
        })();
        return () => { cancelled = true; };
    }, [code]);

    if (failed) return null;
    if (!svg) {
        return (
            <div className="my-3 h-24 rounded-xl bg-dark-800/60 border border-dark-700 animate-pulse" />
        );
    }

    return (
        <figure className="my-3 rounded-xl bg-dark-800/60 border border-dark-700 p-3 overflow-x-auto animate-[fadeIn_0.3s_ease-out]">
            <div className="flex justify-center [&_svg]:max-w-full [&_svg]:h-auto" dangerouslySetInnerHTML={{ __html: svg }} />
            {caption && <figcaption className="mt-2 text-center text-[11px] text-dark-500">{caption}</figcaption>}
        </figure>
    );
}
