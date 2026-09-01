export interface KanbanCard {
  id: string;
  columnId: string;
  title: string;
  details: string;
  dueDate?: string;
  createdAt: string;
}

export interface KanbanColumn {
  id: string;
  title: string;
  requiresDueDate: boolean;
  order: number;
}

export interface KanbanBoardState {
  columns: KanbanColumn[];
  cards: KanbanCard[];
}
