import type { Metadata } from 'next';
import 'katex/dist/katex.min.css';
import './globals.css';

export const metadata: Metadata = {
    title: 'Second Brain',
    description: 'Your intelligent second brain for managing knowledge',
    icons: {
        icon: '/brain.png',
        apple: '/brain.png',
    },
};

export default function RootLayout({
    children,
}: {
    children: React.ReactNode;
}) {
    return (
        <html lang="de">
            <head>
                <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover, interactive-widget=resizes-content" />
            </head>
            <body className="antialiased overflow-hidden overscroll-none">{children}</body>
        </html>
    );
}
