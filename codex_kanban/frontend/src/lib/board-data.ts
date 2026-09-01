export type Card = {
  id: string;
  title: string;
  details: string;
  dueDate?: string;
};

export type Column = {
  id: string;
  title: string;
  cards: Card[];
};

export type BoardState = Column[];

export const initialBoard: BoardState = [
  {
    id: "backlog",
    title: "Backlog",
    cards: [
      {
        id: "card-brief",
        title: "Shape MVP scope",
        details: "Confirm the five-column board, card fields, and no-persistence boundary.",
      },
      {
        id: "card-visual",
        title: "Polish visual direction",
        details: "Apply the navy, blue, purple, yellow, and gray palette with a crisp professional feel.",
      },
    ],
  },
  {
    id: "ready",
    title: "Ready",
    cards: [
      {
        id: "card-dummy",
        title: "Load dummy data",
        details: "Open the single board with realistic seeded work already visible.",
      },
    ],
  },
  {
    id: "in-progress",
    title: "In Progress",
    cards: [
      {
        id: "card-drag",
        title: "Drag cards between columns",
        details: "Use a smooth pointer and keyboard-friendly drag interaction.",
      },
      {
        id: "card-rename",
        title: "Rename columns",
        details: "Make each of the five fixed columns editable without changing their count.",
      },
    ],
  },
  {
    id: "review",
    title: "Review",
    cards: [
      {
        id: "card-tests",
        title: "Verify the happy path",
        details: "Cover add, delete, rename, and move behavior with automated checks.",
      },
    ],
  },
  {
    id: "done",
    title: "Done",
    cards: [
      {
        id: "card-scaffold",
        title: "Scaffold Next.js app",
        details: "Create the client-rendered frontend with current stable tooling.",
        dueDate: "2026-08-14",
      },
    ],
  },
];
