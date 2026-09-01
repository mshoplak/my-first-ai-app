'use client';

import { useState } from 'react';
import {
  DndContext,
  DragEndEvent,
  DragOverlay,
  DragStartEvent,
  closestCorners,
  PointerSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import {
  SortableContext,
  verticalListSortingStrategy,
  arrayMove,
} from '@dnd-kit/sortable';
import type { BoardCard } from '@/lib/types';
import { initialBoard } from '@/lib/data';
import Column from './Column';

function getColumnCards(cards: BoardCard[], columnId: string) {
  return cards.filter((card) => card.columnId === columnId);
}

export default function Board() {
  const [columns, setColumns] = useState(initialBoard.columns);
  const [cards, setCards] = useState(initialBoard.cards);
  const [activeCardId, setActiveCardId] = useState<string | null>(null);

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 8 } }));

  const handleRename = (columnId: string, title: string) => {
    setColumns((current) => current.map((column) => (column.id === columnId ? { ...column, title } : column)));
  };

  const handleAddCard = (columnId: string, title: string, details: string, dueDate?: string) => {
    setCards((current) => [
      ...current,
      {
        id: `card-${Date.now()}`,
        title,
        details,
        columnId,
        dueDate: dueDate?.trim() || undefined,
      },
    ]);
  };

  const handleDeleteCard = (cardId: string) => {
    setCards((current) => current.filter((card) => card.id !== cardId));
  };

  const handleDragStart = (event: DragStartEvent) => {
    setActiveCardId(String(event.active.id));
  };

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    setActiveCardId(null);

    if (!over || active.id === over.id) {
      return;
    }

    const activeCard = cards.find((card) => card.id === active.id);
    const overCard = cards.find((card) => card.id === over.id);
    if (!activeCard) {
      return;
    }

    const overColumnId = over.data.current?.columnId as string | undefined;
    const destinationColumnId = overColumnId ?? overCard?.columnId ?? String(over.id);

    if (destinationColumnId === activeCard.columnId) {
      const columnCards = getColumnCards(cards, destinationColumnId);
      const activeIndex = columnCards.findIndex((card) => card.id === active.id);
      const overIndex = columnCards.findIndex((card) => card.id === over.id);
      if (activeIndex !== -1 && overIndex !== -1 && activeIndex !== overIndex) {
        const ordered = arrayMove(columnCards, activeIndex, overIndex);
        let nextPosition = 0;
        const reordered = cards.map((card) =>
          card.columnId === destinationColumnId ? ordered[nextPosition++] : card,
        );
        setCards(reordered);
      }
      return;
    }

    setCards((current) =>
      current.map((card) =>
        card.id === active.id ? { ...card, columnId: destinationColumnId } : card,
      ),
    );
  };

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCorners}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
    >
      <div className="board-grid">
        {columns.map((column) => {
          const columnCards = getColumnCards(cards, column.id);
          return (
            <SortableContext key={column.id} items={columnCards.map((card) => card.id)} strategy={verticalListSortingStrategy}>
              <Column
                key={column.id}
                column={column}
                cards={columnCards}
                onRename={handleRename}
                onAddCard={handleAddCard}
                onDeleteCard={handleDeleteCard}
              />
            </SortableContext>
          );
        })}
      </div>
      <DragOverlay>{activeCardId ? <div className="card card-dragging">Moving card</div> : null}</DragOverlay>
    </DndContext>
  );
}
