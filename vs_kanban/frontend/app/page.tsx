import Board from '@/components/Board';

export default function Home() {
  return (
    <main className="page-shell">
      <header className="page-header">
        <div>
          <p className="eyebrow">Kanban Project</p>
          <h1>One board, five columns, polished workflow.</h1>
          <p className="intro">Create, move, and manage cards with a simple drag-and-drop dashboard.</p>
        </div>
      </header>
      <Board />
    </main>
  );
}
