'use client';

import React, { ReactNode } from 'react';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import remarkGfm from 'remark-gfm';

// Re-export plugin arrays for shared use across all ReactMarkdown instances
export const remarkPlugins = [remarkGfm, remarkMath];
export const rehypePlugins = [rehypeKatex];

const ADMONITION_TYPES: Record<string, { label: string; cssClass: string }> = {
    MERKSATZ: { label: '📌 Merksatz', cssClass: 'admonition-merksatz' },
    TIPP: { label: '💡 Tipp', cssClass: 'admonition-tipp' },
    WICHTIG: { label: '⚠️ Wichtig', cssClass: 'admonition-wichtig' },
    DEFINITION: { label: '📖 Definition', cssClass: 'admonition-definition' },
    BEISPIEL: { label: '📝 Beispiel', cssClass: 'admonition-beispiel' },
    WARNUNG: { label: '🔴 Warnung', cssClass: 'admonition-warnung' },
};

function getTextContent(node: ReactNode): string {
    if (typeof node === 'string') return node;
    if (typeof node === 'number') return String(node);
    if (Array.isArray(node)) return node.map(getTextContent).join('');
    if (React.isValidElement(node) && node.props.children) {
        return getTextContent(node.props.children);
    }
    return '';
}

function removeMarker(children: ReactNode, marker: string): ReactNode {
    return React.Children.map(children, (child) => {
        if (typeof child === 'string') {
            return child.replace(`[!${marker}]`, '').replace(/^\n/, '');
        }
        if (React.isValidElement(child) && child.props.children) {
            return React.cloneElement(child as React.ReactElement<any>, {
                ...child.props,
                children: removeMarker(child.props.children, marker),
            });
        }
        return child;
    });
}

export const markdownComponents = {
    blockquote: ({ children, node, ...props }: any) => {
        const text = getTextContent(children);
        const match = text.match(/\[!(MERKSATZ|TIPP|WICHTIG|DEFINITION|BEISPIEL|WARNUNG)\]/);

        if (match) {
            const type = match[1];
            const config = ADMONITION_TYPES[type];
            const cleanedChildren = removeMarker(children, type);

            return (
                <div className={`admonition ${config.cssClass}`}>
                    <div className="admonition-title">{config.label}</div>
                    <div className="admonition-content">{cleanedChildren}</div>
                </div>
            );
        }

        return <blockquote {...props}>{children}</blockquote>;
    },
};
