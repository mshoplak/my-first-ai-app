"use client";

import {
  closestCorners,
  DndContext,
  DragEndEvent,
  DragOverlay,
  DragStartEvent,
  KeyboardSensor,
  PointerSensor,
  useDroppable,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { CalendarDays, GripVertical, Pencil, Plus, Trash2 } from "lucide-react";
import { CSSProperties, FormEvent, useMemo, useState } from "react";

import {
  addCard,
  deleteCard,
  findCardLocation,
  moveCard,
  renameColumn,
} from "@/lib/board-actions";
import { BoardState, Card, Column, initialBoard } from "@/lib/board-data";

type Burst = {
  id: string;
  x: number;
  y: number;
};

function createCard(title: string, details: string, dueDate?: string): Card {
  return {
    id: `card-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    title: title.trim(),
    details: details.trim(),
    dueDate: dueDate || undefined,
  };
}

function formatDueDate(dueDate: string) {
  const [year, month, day] = dueDate.split("-");

  return `${month}/${day}/${year}`;
}

export function KanbanBoard() {
  const [board, setBoard] = useState<BoardState>(initialBoard);
  const [activeCardId, setActiveCardId] = useState<string | null>(null);
  const [bursts, setBursts] = useState<Burst[]>([]);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const activeCard = useMemo(() => {
    if (!activeCardId) {
      return null;
    }

    const location = findCardLocation(board, activeCardId);
    const column = board.find((item) => item.id === location?.columnId);

    return location ? column?.cards[location.cardIndex] ?? null : null;
  }, [activeCardId, board]);

  function handleDragStart(event: DragStartEvent) {
    setActiveCardId(String(event.active.id));
  }

  function handleDragEnd(event: DragEndEvent) {
    const cardId = String(event.active.id);
    const overId = event.over?.id ? String(event.over.id) : null;

    setActiveCardId(null);

    if (!overId || overId === cardId) {
      return;
    }

    const overCardLocation = findCardLocation(board, overId);
    const destinationColumnId = overCardLocation?.columnId ?? overId;
    const destinationIndex = overCardLocation?.cardIndex ?? 0;

    setBoard((current) =>
      moveCard(current, cardId, destinationColumnId, destinationIndex),
    );
  }

  function handleRenameColumn(columnId: string, title: string) {
    setBoard((current) => renameColumn(current, columnId, title));
  }

  function handleAddCard(
    columnId: string,
    title: string,
    details: string,
    dueDate?: string,
  ) {
    setBoard((current) =>
      addCard(current, columnId, createCard(title, details, dueDate)),
    );
  }

  function handleDeleteCard(cardId: string, origin?: { x: number; y: number }) {
    if (origin) {
      const burst = {
        id: `burst-${Date.now()}-${Math.random().toString(16).slice(2)}`,
        x: origin.x,
        y: origin.y,
      };

      setBursts((current) => [...current, burst]);
      window.setTimeout(() => {
        setBursts((current) => current.filter((item) => item.id !== burst.id));
      }, 760);
    }

    setBoard((current) => deleteCard(current, cardId));
  }

  return (
    <main className="min-h-screen overflow-hidden bg-[#edf7fc] text-[#032147]">
      <div className="mx-auto flex min-h-screen w-full max-w-[1800px] flex-col px-4 py-5 sm:px-6 lg:px-8">
        <header className="mb-5 flex flex-col gap-3 border-b border-[#b8dff2] pb-5 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="mb-1 text-sm font-semibold uppercase text-[#209dd7]">
              Project Board
            </p>
            <h1 className="text-3xl font-bold tracking-normal text-[#032147] sm:text-4xl">
              Launch Kanban
            </h1>
          </div>
          <div className="flex items-center gap-3 text-sm font-medium text-[#888888]">
            <span className="h-2.5 w-2.5 rounded-full bg-[#ecad0a]" />
            <span>{board.reduce((sum, column) => sum + column.cards.length, 0)} cards</span>
          </div>
        </header>

        <DndContext
          collisionDetection={closestCorners}
          id="launch-kanban-board"
          onDragEnd={handleDragEnd}
          onDragStart={handleDragStart}
          sensors={sensors}
        >
          <section
            aria-label="Kanban columns"
            className="grid flex-1 grid-cols-[repeat(5,minmax(250px,1fr))] gap-4 overflow-x-auto pb-4"
          >
            {board.map((column) => (
              <KanbanColumn
                column={column}
                key={column.id}
                onAddCard={handleAddCard}
                onDeleteCard={handleDeleteCard}
                onRenameColumn={handleRenameColumn}
              />
            ))}
          </section>

          <DragOverlay>{activeCard ? <TaskCard card={activeCard} overlay /> : null}</DragOverlay>
        </DndContext>
      </div>
      {bursts.map((burst) => (
        <DeleteBurst burst={burst} key={burst.id} />
      ))}
    </main>
  );
}

type KanbanColumnProps = {
  column: Column;
  onAddCard: (
    columnId: string,
    title: string,
    details: string,
    dueDate?: string,
  ) => void;
  onDeleteCard: (cardId: string, origin?: { x: number; y: number }) => void;
  onRenameColumn: (columnId: string, title: string) => void;
};

function KanbanColumn({
  column,
  onAddCard,
  onDeleteCard,
  onRenameColumn,
}: KanbanColumnProps) {
  const { isOver, setNodeRef } = useDroppable({
    id: column.id,
    data: { type: "column" },
  });

  return (
    <article
      className={`flex min-h-[620px] flex-col rounded-lg border border-[#b8dff2] border-t-4 bg-white shadow-[0_22px_55px_rgba(3,33,71,0.08)] ${
        isOver
          ? "border-t-[#ecad0a] ring-2 ring-[#ecad0a]/40"
          : "border-t-[#209dd7]"
      }`}
      data-testid={`column-${column.id}`}
      ref={setNodeRef}
    >
      <ColumnHeader
        cardCount={column.cards.length}
        columnId={column.id}
        title={column.title}
        onRenameColumn={onRenameColumn}
      />
      <AddCardForm
        columnId={column.id}
        onAddCard={onAddCard}
      />
      <SortableContext
        items={column.cards.map((card) => card.id)}
        strategy={verticalListSortingStrategy}
      >
        <div className="flex flex-1 flex-col gap-3 overflow-y-auto px-3 pb-3">
          {column.cards.map((card) => (
            <SortableTaskCard
              card={card}
              key={card.id}
              onDeleteCard={onDeleteCard}
            />
          ))}
        </div>
      </SortableContext>
    </article>
  );
}

type ColumnHeaderProps = {
  cardCount: number;
  columnId: string;
  title: string;
  onRenameColumn: (columnId: string, title: string) => void;
};

function ColumnHeader({
  cardCount,
  columnId,
  title,
  onRenameColumn,
}: ColumnHeaderProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [draft, setDraft] = useState(title);

  function commitRename() {
    onRenameColumn(columnId, draft);
    setIsEditing(false);
  }

  return (
    <div className="flex min-h-20 items-center justify-between gap-2 border-b border-[#e2e8f0] px-3">
      <div className="min-w-0 flex-1">
        {isEditing ? (
          <input
            aria-label={`Rename ${title}`}
            autoFocus
            className="h-10 w-full border-b-2 border-[#753991] bg-transparent text-lg font-bold outline-none"
            onBlur={commitRename}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                commitRename();
              }
            }}
            value={draft}
          />
        ) : (
          <h2 className="truncate text-lg font-bold tracking-normal text-[#032147]">
            {title}
          </h2>
        )}
        <p className="text-xs font-semibold uppercase text-[#888888]">
          {cardCount} {cardCount === 1 ? "card" : "cards"}
        </p>
      </div>
      <button
        aria-label={`Edit ${title}`}
        className="grid h-9 w-9 shrink-0 place-items-center border border-[#d9e2ec] text-[#753991] transition hover:border-[#753991] hover:bg-[#753991] hover:text-white"
        onClick={() => {
          setDraft(title);
          setIsEditing(true);
        }}
        title="Rename column"
        type="button"
      >
        <Pencil aria-hidden="true" size={16} strokeWidth={2.3} />
      </button>
    </div>
  );
}

type AddCardFormProps = {
  columnId: string;
  onAddCard: (
    columnId: string,
    title: string,
    details: string,
    dueDate?: string,
  ) => void;
};

function AddCardForm({ columnId, onAddCard }: AddCardFormProps) {
  const [title, setTitle] = useState("");
  const [details, setDetails] = useState("");
  const [dueDate, setDueDate] = useState("");

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!title.trim()) {
      return;
    }

    onAddCard(columnId, title, details, dueDate);
    setTitle("");
    setDetails("");
    setDueDate("");
  }

  return (
    <form
      className="grid gap-2 border-b border-[#e2e8f0] bg-[#f8fafc] p-3"
      onSubmit={handleSubmit}
    >
      <input
        aria-label={`New card title for ${columnId}`}
        className="h-10 border border-[#b8dff2] bg-white px-3 text-sm font-semibold text-[#032147] outline-none transition placeholder:text-[#888888] focus:border-[#209dd7]"
        onChange={(event) => setTitle(event.target.value)}
        placeholder="Card title"
        value={title}
      />
      <div className="flex items-stretch gap-2">
        <textarea
          aria-label={`New card details for ${columnId}`}
          className="min-h-16 flex-1 resize-none border border-[#b8dff2] bg-white px-3 py-2 text-sm text-[#032147] outline-none transition placeholder:text-[#888888] focus:border-[#209dd7]"
          onChange={(event) => setDetails(event.target.value)}
          placeholder="Details"
          value={details}
        />
        <button
          aria-label={`Add card to ${columnId}`}
          className="grid w-11 place-items-center bg-[#209dd7] text-white transition hover:bg-[#167fb2]"
          title="Add card"
          type="submit"
        >
          <Plus aria-hidden="true" size={19} strokeWidth={2.5} />
        </button>
      </div>
      <label className="flex items-center gap-2 text-xs font-semibold uppercase text-[#209dd7]">
        <CalendarDays aria-hidden="true" size={15} />
        <input
          aria-label={`New card due date for ${columnId}`}
          className="h-9 min-w-0 flex-1 border border-[#b8dff2] bg-white px-2 text-sm font-medium text-[#032147] outline-none focus:border-[#209dd7]"
          onChange={(event) => setDueDate(event.target.value)}
          type="date"
          value={dueDate}
        />
      </label>
    </form>
  );
}

type TaskCardProps = {
  attributes?: ReturnType<typeof useSortable>["attributes"];
  card: Card;
  listeners?: ReturnType<typeof useSortable>["listeners"];
  overlay?: boolean;
  setActivatorNodeRef?: ReturnType<typeof useSortable>["setActivatorNodeRef"];
  onDeleteCard?: (cardId: string, origin?: { x: number; y: number }) => void;
};

function SortableTaskCard({
  card,
  onDeleteCard,
}: {
  card: Card;
  onDeleteCard: (cardId: string, origin?: { x: number; y: number }) => void;
}) {
  const {
    attributes,
    isDragging,
    listeners,
    setActivatorNodeRef,
    setNodeRef,
    transform,
    transition,
  } = useSortable({
    id: card.id,
    data: { type: "card" },
  });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };

  return (
    <div
      className={isDragging ? "opacity-30" : undefined}
      data-testid={`card-${card.id}`}
      ref={setNodeRef}
      style={style}
    >
      <TaskCard
        attributes={attributes}
        card={card}
        listeners={listeners}
        onDeleteCard={onDeleteCard}
        setActivatorNodeRef={setActivatorNodeRef}
      />
    </div>
  );
}

function TaskCard({
  attributes,
  card,
  listeners,
  overlay = false,
  setActivatorNodeRef,
  onDeleteCard,
}: TaskCardProps) {
  return (
    <div
      className={`group rounded-lg border border-[#d9e2ec] bg-white p-3 shadow-[0_12px_30px_rgba(3,33,71,0.08)] ${
        overlay ? "w-[260px] rotate-1 ring-2 ring-[#ecad0a]" : ""
      }`}
    >
      <div className="mb-2 flex items-start justify-between gap-2">
        <button
          aria-label={`Drag ${card.title}`}
          className="mt-0.5 grid h-7 w-7 shrink-0 cursor-grab place-items-center border border-[#b8dff2] bg-[#eef8fd] text-[#209dd7] transition hover:border-[#209dd7] hover:bg-[#dff2fb]"
          ref={setActivatorNodeRef}
          title="Drag card"
          type="button"
          {...attributes}
          {...listeners}
        >
          <GripVertical aria-hidden="true" size={16} />
        </button>
        <h3 className="min-w-0 flex-1 text-pretty text-sm font-bold leading-5 text-[#032147]">
          {card.title}
        </h3>
        {onDeleteCard ? (
          <button
            aria-label={`Delete ${card.title}`}
            className="grid h-7 w-7 shrink-0 place-items-center border border-[#b8dff2] text-[#209dd7] transition hover:border-[#753991] hover:bg-[#753991] hover:text-white"
            onClick={(event) => {
              const rect = event.currentTarget.getBoundingClientRect();
              onDeleteCard(card.id, {
                x: rect.left + rect.width / 2,
                y: rect.top + rect.height / 2,
              });
            }}
            title="Delete card"
            type="button"
          >
            <Trash2 aria-hidden="true" size={15} />
          </button>
        ) : null}
      </div>
      <p className="text-sm leading-5 text-[#5f6f82]">{card.details}</p>
      {card.dueDate ? (
        <div
          aria-label={`Due date for ${card.title}: ${formatDueDate(card.dueDate)}`}
          className="mt-3 flex items-center gap-2 border-t border-[#d9edf7] pt-3 text-xs font-semibold uppercase text-[#209dd7]"
        >
          <CalendarDays aria-hidden="true" size={15} />
          <span className="rounded-lg border border-[#b8dff2] bg-[#f8fcff] px-2 py-1.5 text-sm font-medium normal-case text-[#032147]">
            {formatDueDate(card.dueDate)}
          </span>
        </div>
      ) : null}
    </div>
  );
}

function DeleteBurst({ burst }: { burst: Burst }) {
  const pieces = Array.from({ length: 12 }, (_, index) => index);

  return (
    <div
      aria-hidden="true"
      className="pointer-events-none fixed z-50"
      style={{ left: burst.x, top: burst.y }}
    >
      {pieces.map((piece) => (
        <span
          className="delete-burst-piece"
          key={piece}
          style={
            {
              "--burst-rotation": `${piece * 31}deg`,
              "--burst-distance": `${64 + (piece % 4) * 14}px`,
              "--burst-delay": `${piece * 14}ms`,
            } as CSSProperties
          }
        />
      ))}
    </div>
  );
}
