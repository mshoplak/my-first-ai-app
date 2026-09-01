'use client';

import dynamic from 'next/dynamic';

const KanbanBoard = dynamic(
  () => import('@/components/KanbanBoard').then((mod) => mod.KanbanBoard),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-screen items-center justify-center bg-[#021124] text-white text-sm font-medium">
        <div className="flex items-center gap-3">
          <div className="h-5 w-5 animate-spin rounded-full border-2 border-[#209dd7] border-t-transparent"></div>
          <span>Loading Kanban Board...</span>
        </div>
      </div>
    ),
  }
);

export default function Home() {
  return <KanbanBoard />;
}
