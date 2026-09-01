import { CSS } from '@dnd-kit/utilities';
import { useSortable } from '@dnd-kit/sortable';
import type { UniqueIdentifier } from '@dnd-kit/core';

export type CardProps = {
  id: UniqueIdentifier;
  title: string;
  details: string;
  columnId: string;
  dueDate?: string;
  onDelete: (id: string) => void;
};

export default function Card({ id, title, details, columnId, dueDate, onDelete }: CardProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id,
    data: { columnId },
  });

  const style = {
    transform: transform ? CSS.Translate.toString(transform) : undefined,
    transition: transition || undefined,
    opacity: isDragging ? 0.85 : 1,
  };

  return (
    <div className="card" ref={setNodeRef} style={style} {...attributes} {...listeners}>
      <div>
        <h3 className="card-title">{title}</h3>
        <p className="card-details">{details}</p>
        {dueDate ? <p className="card-meta">Due {new Date(dueDate).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}</p> : null}
      </div>
      <button className="delete-button" type="button" onClick={() => onDelete(String(id))}>
        Delete
      </button>
    </div>
  );
}
