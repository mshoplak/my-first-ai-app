'use client';

import React, { useState } from 'react';
import { X, Calendar, AlertCircle } from 'lucide-react';

interface AddCardModalProps {
  isOpen: boolean;
  columnTitle: string;
  requiresDueDate: boolean;
  onClose: () => void;
  onAddCard: (title: string, details: string, dueDate?: string) => void;
}

export const AddCardModal: React.FC<AddCardModalProps> = ({
  isOpen,
  columnTitle,
  requiresDueDate,
  onClose,
  onAddCard,
}) => {
  const [title, setTitle] = useState('');
  const [details, setDetails] = useState('');
  const [dueDate, setDueDate] = useState('');
  const [error, setError] = useState('');

  if (!isOpen) return null;

  const handleSubmit = (e?: React.FormEvent | React.MouseEvent | React.KeyboardEvent) => {
    if (e) {
      e.preventDefault();
      e.stopPropagation();
    }
    if (!title.trim()) {
      setError('Card title is required');
      return;
    }
    if (requiresDueDate && !dueDate) {
      setError('Due date is required for cards in this column');
      return;
    }

    onAddCard(title.trim(), details.trim(), dueDate || undefined);
    setTitle('');
    setDetails('');
    setDueDate('');
    setError('');
    onClose();
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      e.stopPropagation();
      handleSubmit(e);
    }
  };

  return (
    <div
      data-testid="add-card-modal"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
      onClick={(e) => e.stopPropagation()}
    >
      <div
        className="w-full max-w-md rounded-xl border border-[#209dd7]/40 bg-[#061933] p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal Header */}
        <div className="mb-4 flex items-center justify-between border-b border-[#133563] pb-3">
          <h3 className="text-lg font-bold text-white">
            Add Card to <span className="text-[#209dd7]">{columnTitle}</span>
          </h3>
          <button
            onClick={onClose}
            type="button"
            className="rounded p-1 text-[#888888] hover:bg-white/10 hover:text-white transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Error Notification */}
        {error && (
          <div className="mb-4 flex items-center gap-2 rounded bg-red-950/80 p-3 text-xs text-red-300 border border-red-800">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {/* Form Body */}
        <form
          action="javascript:void(0)"
          onSubmit={handleSubmit}
          className="space-y-4"
        >
          <div>
            <label className="mb-1 block text-xs font-semibold text-[#888888]">
              Card Title <span className="text-[#ecad0a]">*</span>
            </label>
            <input
              type="text"
              data-testid="card-title-input"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Enter card title..."
              className="w-full rounded-lg border border-[#1b3d6c] bg-[#032147] p-2.5 text-sm text-white placeholder-[#888888] focus:border-[#209dd7] focus:outline-none focus:ring-1 focus:ring-[#209dd7]"
              autoFocus
            />
          </div>

          <div>
            <label className="mb-1 block text-xs font-semibold text-[#888888]">
              Card Details
            </label>
            <textarea
              rows={3}
              data-testid="card-details-input"
              value={details}
              onChange={(e) => setDetails(e.target.value)}
              placeholder="Enter card details or description..."
              className="w-full rounded-lg border border-[#1b3d6c] bg-[#032147] p-2.5 text-sm text-white placeholder-[#888888] focus:border-[#209dd7] focus:outline-none focus:ring-1 focus:ring-[#209dd7]"
            />
          </div>

          <div>
            <label className="mb-1 flex items-center justify-between text-xs font-semibold text-[#888888]">
              <span className="flex items-center gap-1">
                <Calendar className="h-3.5 w-3.5 text-[#209dd7]" />
                Due Date
              </span>
              {requiresDueDate && (
                <span className="text-[#ecad0a] text-[11px] font-bold">Required for Column</span>
              )}
            </label>
            <input
              type="date"
              data-testid="card-duedate-input"
              value={dueDate}
              onChange={(e) => setDueDate(e.target.value)}
              onKeyDown={handleKeyDown}
              className="w-full rounded-lg border border-[#1b3d6c] bg-[#032147] p-2.5 text-sm text-white focus:border-[#209dd7] focus:outline-none focus:ring-1 focus:ring-[#209dd7]"
            />
          </div>

          {/* Action Buttons */}
          <div className="flex items-center justify-end gap-3 pt-3 border-t border-[#133563]">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-[#1b3d6c] px-4 py-2 text-xs font-medium text-[#888888] hover:bg-white/5 hover:text-white transition-colors"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSubmit}
              data-testid="submit-card-button"
              className="rounded-lg bg-[#753991] hover:bg-[#8846a8] px-5 py-2 text-xs font-semibold text-white shadow-lg transition-all"
            >
              Add Card
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
