'use client';

import React, { useState } from 'react';
import { Droppable } from '@hello-pangea/dnd';
import { KanbanColumn, KanbanCard as KanbanCardType } from '../types/kanban';
import { KanbanCard } from './KanbanCard';
import { AddCardModal } from './AddCardModal';
import { Plus, Edit2, Check, Clock, Calendar } from 'lucide-react';

interface ColumnContainerProps {
  column: KanbanColumn;
  cards: KanbanCardType[];
  onRenameColumn: (columnId: string, newTitle: string) => void;
  onToggleDueDateRequirement: (columnId: string) => void;
  onAddCard: (columnId: string, title: string, details: string, dueDate?: string) => void;
  onDeleteCard: (cardId: string) => void;
}

export const ColumnContainer: React.FC<ColumnContainerProps> = ({
  column,
  cards,
  onRenameColumn,
  onToggleDueDateRequirement,
  onAddCard,
  onDeleteCard,
}) => {
  const [isEditingTitle, setIsEditingTitle] = useState(false);
  const [titleInput, setTitleInput] = useState(column.title);
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);

  const handleTitleSubmit = () => {
    if (titleInput.trim() && titleInput.trim() !== column.title) {
      onRenameColumn(column.id, titleInput.trim());
    } else {
      setTitleInput(column.title);
    }
    setIsEditingTitle(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleTitleSubmit();
    } else if (e.key === 'Escape') {
      setTitleInput(column.title);
      setIsEditingTitle(false);
    }
  };

  return (
    <div
      data-testid={`column-${column.id}`}
      className="flex flex-col w-80 shrink-0 rounded-xl border border-[#1b3d6c] bg-[#061933] shadow-lg max-h-[calc(100vh-160px)]"
    >
      {/* Column Header */}
      <div className="p-4 border-b border-[#133563] bg-[#032147]/80 rounded-t-xl">
        <div className="flex items-center justify-between gap-2 mb-2">
          {isEditingTitle ? (
            <div className="flex items-center gap-1 w-full">
              <input
                type="text"
                data-testid={`column-title-input-${column.id}`}
                value={titleInput}
                onChange={(e) => setTitleInput(e.target.value)}
                onBlur={handleTitleSubmit}
                onKeyDown={handleKeyDown}
                className="w-full rounded bg-[#061933] px-2 py-1 text-sm font-bold text-white border border-[#209dd7] focus:outline-none"
                autoFocus
              />
              <button
                type="button"
                onClick={handleTitleSubmit}
                className="rounded p-1 text-[#ecad0a] hover:bg-white/10"
              >
                <Check className="h-4 w-4" />
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-2 group cursor-pointer" onClick={() => setIsEditingTitle(true)}>
              <h3
                data-testid={`column-title-${column.id}`}
                className="font-bold text-white text-base tracking-wide"
              >
                {column.title}
              </h3>
              <button
                type="button"
                title="Rename Column"
                className="opacity-0 group-hover:opacity-100 transition-opacity text-[#888888] hover:text-[#209dd7]"
              >
                <Edit2 className="h-3.5 w-3.5" />
              </button>
            </div>
          )}

          <span className="rounded-full bg-[#209dd7]/20 px-2.5 py-0.5 text-xs font-bold text-[#209dd7] border border-[#209dd7]/30">
            {cards.length}
          </span>
        </div>

        {/* Column Settings Bar: Due Date Requirement Toggle */}
        <div className="flex items-center justify-between text-xs text-[#888888]">
          <button
            type="button"
            data-testid={`toggle-duedate-req-${column.id}`}
            onClick={() => onToggleDueDateRequirement(column.id)}
            className={`flex items-center gap-1.5 px-2 py-1 rounded transition-colors ${
              column.requiresDueDate
                ? 'bg-[#ecad0a]/20 text-[#ecad0a] border border-[#ecad0a]/40 font-medium'
                : 'bg-[#03152c] text-[#888888] hover:text-white border border-[#1b3d6c]'
            }`}
            title="Toggle Due Date requirement for cards in this column"
          >
            <Clock className="h-3.5 w-3.5" />
            <span>{column.requiresDueDate ? 'Due Date Required' : 'Optional Due Date'}</span>
          </button>

          <button
            type="button"
            data-testid={`add-card-button-${column.id}`}
            onClick={() => setIsAddModalOpen(true)}
            className="flex items-center gap-1 rounded bg-[#753991] hover:bg-[#8846a8] px-2.5 py-1 text-xs font-semibold text-white transition-all shadow-md"
          >
            <Plus className="h-3.5 w-3.5" />
            <span>Add</span>
          </button>
        </div>
      </div>

      {/* Droppable Card List */}
      <Droppable droppableId={column.id} ignoreContainerClipping={true}>
        {(provided, snapshot) => (
          <div
            ref={provided.innerRef}
            {...provided.droppableProps}
            data-testid={`droppable-${column.id}`}
            className={`flex-1 p-3 overflow-y-auto transition-colors min-h-[150px] ${
              snapshot.isDraggingOver ? 'bg-[#0a2f5e]/40 ring-1 ring-inset ring-[#209dd7]' : ''
            }`}
          >
            {cards.map((card, index) => (
              <KanbanCard
                key={card.id}
                card={card}
                index={index}
                requiresDueDate={column.requiresDueDate}
                onDeleteCard={onDeleteCard}
              />
            ))}
            {provided.placeholder}
            {cards.length === 0 && (
              <div className="flex h-24 items-center justify-center rounded-lg border border-dashed border-[#1b3d6c] text-xs text-[#888888]">
                No cards in this column
              </div>
            )}
          </div>
        )}
      </Droppable>

      {/* Add Card Modal */}
      <AddCardModal
        isOpen={isAddModalOpen}
        columnTitle={column.title}
        requiresDueDate={column.requiresDueDate}
        onClose={() => setIsAddModalOpen(false)}
        onAddCard={(title, details, dueDate) => onAddCard(column.id, title, details, dueDate)}
      />
    </div>
  );
};
