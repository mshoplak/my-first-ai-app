'use client';

import React from 'react';
import { Layout, CheckSquare, Clock } from 'lucide-react';

interface KanbanHeaderProps {
  totalCards: number;
  totalColumns: number;
  dueSoonCount: number;
}

export const KanbanHeader: React.FC<KanbanHeaderProps> = ({
  totalCards,
  totalColumns,
  dueSoonCount,
}) => {
  return (
    <header className="border-b border-[#1b3d6c] bg-[#032147] px-6 py-4 shadow-xl">
      <div className="mx-auto flex flex-col sm:flex-row items-center justify-between gap-4">
        {/* Title & Brand */}
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-[#209dd7] to-[#753991] shadow-md">
            <Layout className="h-5 w-5 text-white" />
          </div>
          <div>
            <h1 className="text-xl font-extrabold text-white tracking-wide flex items-center gap-2">
              Kanban <span className="text-[#ecad0a]">Workspace</span>
            </h1>
            <p className="text-xs text-[#888888]">
              Single Board Project Management & Task Organizer
            </p>
          </div>
        </div>

        {/* Board Stats */}
        <div className="flex items-center gap-4 text-xs">
          <div className="flex items-center gap-2 rounded-lg bg-[#061933] border border-[#1b3d6c] px-3 py-1.5 text-white">
            <CheckSquare className="h-4 w-4 text-[#209dd7]" />
            <span>
              <strong className="text-[#209dd7] font-bold">{totalCards}</strong> Cards
            </span>
          </div>

          <div className="flex items-center gap-2 rounded-lg bg-[#061933] border border-[#1b3d6c] px-3 py-1.5 text-white">
            <Layout className="h-4 w-4 text-[#753991]" />
            <span>
              <strong className="text-[#753991] font-bold">{totalColumns}</strong> Columns
            </span>
          </div>

          {dueSoonCount > 0 && (
            <div className="flex items-center gap-2 rounded-lg bg-[#ecad0a]/10 border border-[#ecad0a]/30 px-3 py-1.5 text-[#ecad0a]">
              <Clock className="h-4 w-4" />
              <span>
                <strong>{dueSoonCount}</strong> Due Dates
              </span>
            </div>
          )}
        </div>
      </div>
    </header>
  );
};
