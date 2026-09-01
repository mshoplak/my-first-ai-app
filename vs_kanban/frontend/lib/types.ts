export type BoardColumn = {
  id: string;
  title: string;
};

export type BoardCard = {
  id: string;
  title: string;
  details: string;
  columnId: string;
  dueDate?: string;
};

export type KanbanData = {
  columns: BoardColumn[];
  cards: BoardCard[];
};
