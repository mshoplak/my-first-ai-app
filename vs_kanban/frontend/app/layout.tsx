import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Kanban Project',
  description: 'A clean single-board Kanban application',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
