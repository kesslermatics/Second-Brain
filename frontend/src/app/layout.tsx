import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
    title: 'Brain - Second Brain',
    description: 'Your intelligent second brain for managing knowledge',
};

export default function RootLayout({
    children,
}: {
    children: React.ReactNode;
}) {
    return (
        <html lang="de">
            <body className="antialiased">{children}</body>
        </html>
    );
}
