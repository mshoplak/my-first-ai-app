import { KanbanBoardState } from '../types/kanban';

export const INITIAL_BOARD_DATA: KanbanBoardState = {
  columns: [
    { id: 'backlog', title: 'Backlog', requiresDueDate: false, order: 0 },
    { id: 'ready', title: 'Ready', requiresDueDate: false, order: 1 },
    { id: 'in-progress', title: 'In Progress', requiresDueDate: true, order: 2 },
    { id: 'review', title: 'In Review', requiresDueDate: true, order: 3 },
    { id: 'done', title: 'Done', requiresDueDate: false, order: 4 },
  ],
  cards: [
    {
      id: 'card-1',
      columnId: 'backlog',
      title: 'Design System Architecture',
      details: 'Establish design tokens and reusable visual guidelines for app components.',
      createdAt: '2026-08-01',
    },
    {
      id: 'card-2',
      columnId: 'ready',
      title: 'Setup CI/CD Pipeline',
      details: 'Configure automated test workflows and bundle verification.',
      dueDate: '2026-08-15',
      createdAt: '2026-08-02',
    },
    {
      id: 'card-3',
      columnId: 'in-progress',
      title: 'Implement Explosion FX',
      details: 'Integrate particle bursts on card deletion action using canvas-confetti.',
      dueDate: '2026-08-12',
      createdAt: '2026-08-03',
    },
    {
      id: 'card-4',
      columnId: 'review',
      title: 'Drag and Drop Reordering',
      details: 'Verify smooth column-to-column drag and drop transitions across all 5 columns.',
      dueDate: '2026-08-11',
      createdAt: '2026-08-04',
    },
    {
      id: 'card-5',
      columnId: 'done',
      title: 'Initial Project Scaffolding',
      details: 'Setup Next.js, Tailwind styling system, Vitest unit runner, and Playwright.',
      dueDate: '2026-08-08',
      createdAt: '2026-08-01',
    },
  ],
};
