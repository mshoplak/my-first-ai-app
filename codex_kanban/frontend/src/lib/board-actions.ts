import type { BoardState, Card } from "./board-data";

export function renameColumn(
  board: BoardState,
  columnId: string,
  title: string,
): BoardState {
  const nextTitle = title.trim() || "Untitled";

  return board.map((column) =>
    column.id === columnId ? { ...column, title: nextTitle } : column,
  );
}

export function addCard(
  board: BoardState,
  columnId: string,
  card: Card,
): BoardState {
  return board.map((column) =>
    column.id === columnId ? { ...column, cards: [card, ...column.cards] } : column,
  );
}

export function deleteCard(board: BoardState, cardId: string): BoardState {
  return board.map((column) => ({
    ...column,
    cards: column.cards.filter((card) => card.id !== cardId),
  }));
}

export function findCardLocation(board: BoardState, cardId: string) {
  for (const column of board) {
    const cardIndex = column.cards.findIndex((card) => card.id === cardId);

    if (cardIndex >= 0) {
      return { columnId: column.id, cardIndex };
    }
  }

  return null;
}

export function moveCard(
  board: BoardState,
  cardId: string,
  destinationColumnId: string,
  destinationIndex = 0,
): BoardState {
  const source = findCardLocation(board, cardId);

  if (!source) {
    return board;
  }

  const sourceColumn = board.find((column) => column.id === source.columnId);
  const card = sourceColumn?.cards[source.cardIndex];

  if (!card) {
    return board;
  }

  const withoutCard = board.map((column) =>
    column.id === source.columnId
      ? { ...column, cards: column.cards.filter((item) => item.id !== cardId) }
      : column,
  );

  return withoutCard.map((column) => {
    if (column.id !== destinationColumnId) {
      return column;
    }

    const nextCards = [...column.cards];
    const boundedIndex = Math.max(0, Math.min(destinationIndex, nextCards.length));
    nextCards.splice(boundedIndex, 0, card);

    return { ...column, cards: nextCards };
  });
}
