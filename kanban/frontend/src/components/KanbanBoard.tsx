'use client';

import React, { useState, useEffect } from 'react';
import { DragDropContext, DropResult } from '@hello-pangea/dnd';
import { KanbanBoardState, KanbanCard, KanbanColumn } from '../types/kanban';
import { INITIAL_BOARD_DATA } from '../data/initialData';
import { ColumnContainer } from './ColumnContainer';
import { KanbanHeader } from './KanbanHeader';

export const KanbanBoard: React.FC = () => {
  const [boardState, setBoardState] = useState<KanbanBoardState>(INITIAL_BOARD_DATA);
  const [isMounted, setIsMounted] = useState(false);

  useEffect(() => {
    setIsMounted(true);
  }, []);

  // Drag and Drop Handler
  const handleDragEnd = (result: DropResult) => {
    const { destination, source, draggableId } = result;

    if (!destination) return;

    if (
      destination.droppableId === source.droppableId &&
      destination.index === source.index
    ) {
      return;
    }

    setBoardState((prevState) => {
      const updatedCards = [...prevState.cards];
      const movedCardIndex = updatedCards.findIndex((c) => c.id === draggableId);
      if (movedCardIndex === -1) return prevState;

      const [movedCard] = updatedCards.splice(movedCardIndex, 1);
      const updatedMovedCard = {
        ...movedCard,
        columnId: destination.droppableId,
      };

      // Get target column cards sorted by order
      const targetColumnCards = updatedCards.filter(
        (c) => c.columnId === destination.droppableId
      );

      // Determine insert index
      if (targetColumnCards.length === 0) {
        updatedCards.push(updatedMovedCard);
      } else {
        const targetCardAtDest = targetColumnCards[destination.index];
        if (targetCardAtDest) {
          const insertGlobalIndex = updatedCards.findIndex(
            (c) => c.id === targetCardAtDest.id
          );
          updatedCards.splice(insertGlobalIndex, 0, updatedMovedCard);
        } else {
          updatedCards.push(updatedMovedCard);
        }
      }

      return {
        ...prevState,
        cards: updatedCards,
      };
    });
  };

  // Column Actions
  const handleRenameColumn = (columnId: string, newTitle: string) => {
    setBoardState((prevState) => ({
      ...prevState,
      columns: prevState.columns.map((col) =>
        col.id === columnId ? { ...col, title: newTitle } : col
      ),
    }));
  };

  const handleToggleDueDateRequirement = (columnId: string) => {
    setBoardState((prevState) => ({
      ...prevState,
      columns: prevState.columns.map((col) =>
        col.id === columnId ? { ...col, requiresDueDate: !col.requiresDueDate } : col
      ),
    }));
  };

  // Card Actions
  const handleAddCard = (
    columnId: string,
    title: string,
    details: string,
    dueDate?: string
  ) => {
    const newCard: KanbanCard = {
      id: `card-${Date.now()}`,
      columnId,
      title,
      details,
      dueDate,
      createdAt: new Date().toISOString().split('T')[0],
    };

    setBoardState((prevState) => ({
      ...prevState,
      cards: [...prevState.cards, newCard],
    }));
  };

  const handleDeleteCard = (cardId: string) => {
    setBoardState((prevState) => ({
      ...prevState,
      cards: prevState.cards.filter((c) => c.id !== cardId),
    }));
  };

  if (!isMounted) {
    return (
      <div className="flex h-screen items-center justify-center bg-[#021124] text-white text-sm font-medium">
        <div className="flex items-center gap-3">
          <div className="h-5 w-5 animate-spin rounded-full border-2 border-[#209dd7] border-t-transparent"></div>
          <span>Loading Kanban Board...</span>
        </div>
      </div>
    );
  }

  const dueSoonCount = boardState.cards.filter((c) => c.dueDate).length;

  return (
    <div className="flex flex-col min-h-screen bg-[#021124]">
      {/* Header Bar */}
      <KanbanHeader
        totalCards={boardState.cards.length}
        totalColumns={boardState.columns.length}
        dueSoonCount={dueSoonCount}
      />

      {/* Main Board Workspace - Centered layout with safe scroll behavior */}
      <main className="flex-1 p-6 overflow-x-auto">
        <DragDropContext onDragEnd={handleDragEnd}>
          <div className="flex gap-4 xl:gap-5 pb-6 items-start m-auto w-fit">
            {boardState.columns.map((column) => {
              const columnCards = boardState.cards.filter(
                (card) => card.columnId === column.id
              );
              return (
                <ColumnContainer
                  key={column.id}
                  column={column}
                  cards={columnCards}
                  onRenameColumn={handleRenameColumn}
                  onToggleDueDateRequirement={handleToggleDueDateRequirement}
                  onAddCard={handleAddCard}
                  onDeleteCard={handleDeleteCard}
                />
              );
            })}
          </div>
        </DragDropContext>
      </main>
    </div>
  );
};
