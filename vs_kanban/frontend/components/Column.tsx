'use client';

import { useMemo, useState } from 'react';
import { useDroppable } from '@dnd-kit/core';
import type { BoardCard, BoardColumn } from '@/lib/types';
import Card from './Card';

export type ColumnProps = {
  column: BoardColumn;
  cards: BoardCard[];
  onRename: (columnId: string, title: string) => void;
  onAddCard: (columnId: string, title: string, details: string, dueDate?: string) => void;
  onDeleteCard: (cardId: string) => void;
};

export default function Column({
  column,
  cards,
  onRename,
  onAddCard,
  onDeleteCard,
}: ColumnProps) {
  const [title, setTitle] = useState(column.title);
  const [isEditing, setIsEditing] = useState(false);
  const [cardTitle, setCardTitle] = useState('');
  const [cardDetails, setCardDetails] = useState('');
  const [cardDueDate, setCardDueDate] = useState('');

  const { setNodeRef, isOver } = useDroppable({
    id: column.id,
    data: { columnId: column.id },
  });

  const cardCount = useMemo(() => cards.length, [cards.length]);

  const handleRename = () => {
    if (title.trim() !== '') {
      onRename(column.id, title.trim());
    }
    setIsEditing(false);
  };

  const handleAdd = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!cardTitle.trim()) return;
    onAddCard(column.id, cardTitle.trim(), cardDetails.trim(), cardDueDate.trim() || undefined);
    setCardTitle('');
    setCardDetails('');
    setCardDueDate('');
  };

  return (
    <section className="column-card">
      <div className="column-header">
        {isEditing ? (
          <input
            className="title-input"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            onBlur={handleRename}
            onKeyDown={(event) => event.key === 'Enter' && handleRename()}
            autoFocus
          />
        ) : (
          <h2 className="column-title" onClick={() => setIsEditing(true)}>{column.title}</h2>
        )}
        <div className="column-controls">
          <span className="column-count">{cardCount} cards</span>
        </div>
      </div>
      <div className="card-list" ref={setNodeRef} style={{ background: isOver ? '#eef7ff' : undefined }}>
        {cards.length === 0 ? (
          <div className="empty-card-placeholder">Drop cards here</div>
        ) : (
          cards.map((card) => (
            <Card
              key={card.id}
              id={card.id}
              title={card.title}
              details={card.details}
              dueDate={card.dueDate}
              columnId={column.id}
              onDelete={onDeleteCard}
            />
          ))
        )}
      </div>
      <form className="add-card-form" onSubmit={handleAdd}>
        <input
          className="input"
          placeholder="Card title"
          value={cardTitle}
          onChange={(event) => setCardTitle(event.target.value)}
        />
        <textarea
          className="textarea"
          placeholder="Details"
          value={cardDetails}
          onChange={(event) => setCardDetails(event.target.value)}
        />
        <input
          className="input"
          type="date"
          value={cardDueDate}
          onChange={(event) => setCardDueDate(event.target.value)}
        />
        <button className="add-button" type="submit">
          Add card
        </button>
      </form>
    </section>
  );
}
