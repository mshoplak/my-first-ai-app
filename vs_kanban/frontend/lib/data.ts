import type { KanbanData } from './types';

export const initialBoard: KanbanData = {
  columns: [
    { id: 'backlog', title: 'Backlog' },
    { id: 'planned', title: 'Planned' },
    { id: 'in-progress', title: 'In Progress' },
    { id: 'review', title: 'Review' },
    { id: 'done', title: 'Done' },
  ],
  cards: [
    {
      id: 'card-1',
      title: 'Define board structure',
      details: 'Create the layout and set fixed column names for the Kanban board.',
      columnId: 'backlog',
    },
    {
      id: 'card-2',
      title: 'Add drag and drop',
      details: 'Implement drag-and-drop motion so cards can move between columns.',
      columnId: 'planned',
    },
    {
      id: 'card-3',
      title: 'Build card form',
      details: 'Allow new cards to be added directly inside each column.',
      columnId: 'in-progress',
    },
    {
      id: 'card-4',
      title: 'Style board UI',
      details: 'Apply the brand colors and make the board look polished and professional.',
      columnId: 'review',
    },
    {
      id: 'card-5',
      title: 'Delete card action',
      details: 'Support removing cards without persistence or extra steps.',
      columnId: 'done',
      dueDate: '2026-09-01',
    },
  ],
};
