import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { KanbanBoard } from '../KanbanBoard';

// Mock canvas-confetti
vi.mock('canvas-confetti', () => ({
  default: vi.fn(),
}));

describe('KanbanBoard Unit Tests', () => {
  it('renders initial 5 columns and board header', async () => {
    render(<KanbanBoard />);

    await waitFor(() => {
      expect(screen.getByText('Backlog')).toBeInTheDocument();
      expect(screen.getByText('Ready')).toBeInTheDocument();
      expect(screen.getByText('In Progress')).toBeInTheDocument();
      expect(screen.getByText('In Review')).toBeInTheDocument();
      expect(screen.getByText('Done')).toBeInTheDocument();
    });
  });

  it('allows renaming a column', async () => {
    render(<KanbanBoard />);

    await waitFor(() => {
      expect(screen.getByText('Backlog')).toBeInTheDocument();
    });

    const backlogHeader = screen.getByTestId('column-title-backlog');
    fireEvent.click(backlogHeader);

    const titleInput = screen.getByTestId('column-title-input-backlog');
    fireEvent.change(titleInput, { target: { value: 'New Backlog Title' } });
    fireEvent.keyDown(titleInput, { key: 'Enter', code: 'Enter' });

    await waitFor(() => {
      expect(screen.getByText('New Backlog Title')).toBeInTheDocument();
    });
  });

  it('toggles column due date requirement', async () => {
    render(<KanbanBoard />);

    await waitFor(() => {
      const toggleButton = screen.getByTestId('toggle-duedate-req-backlog');
      expect(toggleButton).toHaveTextContent('Optional Due Date');
      fireEvent.click(toggleButton);
      expect(toggleButton).toHaveTextContent('Due Date Required');
    });
  });

  it('adds a new card to a column', async () => {
    render(<KanbanBoard />);

    await waitFor(() => {
      expect(screen.getByTestId('add-card-button-backlog')).toBeInTheDocument();
    });

    const addButton = screen.getByTestId('add-card-button-backlog');
    fireEvent.click(addButton);

    expect(screen.getByTestId('add-card-modal')).toBeInTheDocument();

    const titleInput = screen.getByTestId('card-title-input');
    const detailsInput = screen.getByTestId('card-details-input');
    const submitButton = screen.getByTestId('submit-card-button');

    fireEvent.change(titleInput, { target: { value: 'Automated Test Card' } });
    fireEvent.change(detailsInput, { target: { value: 'Card description detail' } });
    fireEvent.click(submitButton);

    await waitFor(() => {
      expect(screen.getByText('Automated Test Card')).toBeInTheDocument();
      expect(screen.getByText('Card description detail')).toBeInTheDocument();
    });
  });

  it('deletes a card when delete button is clicked', async () => {
    render(<KanbanBoard />);

    await waitFor(() => {
      expect(screen.getByTestId('delete-card-card-1')).toBeInTheDocument();
    });

    const deleteButton = screen.getByTestId('delete-card-card-1');
    fireEvent.click(deleteButton);

    await waitFor(
      () => {
        expect(screen.queryByTestId('card-card-1')).not.toBeInTheDocument();
      },
      { timeout: 500 }
    );
  });
});
