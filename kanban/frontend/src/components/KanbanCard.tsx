'use client';

import React, { useRef } from 'react';
import { Draggable } from '@hello-pangea/dnd';
import { KanbanCard as KanbanCardType } from '../types/kanban';
import { Trash2, Calendar, AlertCircle } from 'lucide-react';
import { triggerCardExplosion } from '../utils/explosion';

interface KanbanCardProps {
  card: KanbanCardType;
  index: number;
  requiresDueDate: boolean;
  onDeleteCard: (cardId: string) => void;
}

export const KanbanCard: React.FC<KanbanCardProps> = ({
  card,
  index,
  requiresDueDate,
  onDeleteCard,
}) => {
  const cardRef = useRef<HTMLDivElement>(null);

  const isDueDateMissing = requiresDueDate && !card.dueDate;
  const isPastDue =
    card.dueDate && new Date(card.dueDate) < new Date(new Date().setHours(0, 0, 0, 0));

  const handleDelete = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (cardRef.current) {
      triggerCardExplosion(cardRef.current);
    }
    // Short delay to allow confetti burst to trigger visibly before element unmount
    setTimeout(() => {
      onDeleteCard(card.id);
    }, 150);
  };

  return (
    <Draggable draggableId={card.id} index={index}>
      {(provided, snapshot) => (
        <div
          ref={(node) => {
            provided.innerRef(node);
            cardRef.current = node;
          }}
          {...provided.draggableProps}
          {...provided.dragHandleProps}
          data-testid={`card-${card.id}`}
          className={`kanban-card group relative mb-3 rounded-lg border p-4 shadow-md transition-all ${
            snapshot.isDragging
              ? 'border-[#ecad0a] bg-[#0c2f5a] shadow-xl ring-2 ring-[#ecad0a]'
              : 'border-[#1b3d6c] bg-[#0a2548] hover:border-[#209dd7]'
          }`}
        >
          {/* Card Header & Delete Button */}
          <div className="mb-2 flex items-start justify-between gap-2">
            <h4 className="font-semibold text-white text-base leading-snug break-words">
              {card.title}
            </h4>
            <button
              type="button"
              data-testid={`delete-card-${card.id}`}
              onClick={handleDelete}
              title="Delete Card"
              className="rounded p-1 text-[#888888] hover:bg-red-500/20 hover:text-red-400 transition-colors"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </div>

          {/* Card Details */}
          {card.details && (
            <p className="mb-3 text-xs text-[#888888] leading-relaxed break-words">
              {card.details}
            </p>
          )}

          {/* Due Date & Requirement Indicators */}
          <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-[#133563]">
            {card.dueDate ? (
              <div
                className={`flex items-center gap-1 text-xs px-2 py-0.5 rounded font-medium ${
                  isPastDue
                    ? 'bg-red-950/80 text-red-300 border border-red-800'
                    : 'bg-[#032147] text-[#209dd7] border border-[#209dd7]/40'
                }`}
              >
                <Calendar className="h-3.5 w-3.5" />
                <span>{card.dueDate}</span>
              </div>
            ) : (
              <div className="text-[11px] text-[#888888]">No due date</div>
            )}

            {isDueDateMissing && (
              <div
                className="flex items-center gap-1 text-[11px] px-2 py-0.5 rounded font-medium bg-[#ecad0a]/20 text-[#ecad0a] border border-[#ecad0a]/50"
                title="This column requires a due date"
              >
                <AlertCircle className="h-3 w-3" />
                <span>Due Date Required</span>
              </div>
            )}
          </div>
        </div>
      )}
    </Draggable>
  );
};
