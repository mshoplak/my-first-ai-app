import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { KanbanBoard } from "./kanban-board";

describe("KanbanBoard", () => {
  it("opens with five populated columns", () => {
    render(<KanbanBoard />);

    expect(screen.getAllByTestId(/^column-/)).toHaveLength(5);
    expect(screen.getByText("Shape MVP scope")).toBeInTheDocument();
    expect(screen.getByText("Scaffold Next.js app")).toBeInTheDocument();
  });

  it("renames a column", async () => {
    const user = userEvent.setup();
    render(<KanbanBoard />);

    await user.click(screen.getByRole("button", { name: "Edit Backlog" }));
    await user.clear(screen.getByLabelText("Rename Backlog"));
    await user.type(screen.getByLabelText("Rename Backlog"), "Ideas{Enter}");

    expect(screen.getByRole("heading", { name: "Ideas" })).toBeInTheDocument();
  });

  it("adds and deletes a card", async () => {
    const user = userEvent.setup();
    render(<KanbanBoard />);

    const backlog = screen.getByTestId("column-backlog");

    await user.type(
      within(backlog).getByLabelText("New card title for backlog"),
      "Write launch note",
    );
    await user.type(
      within(backlog).getByLabelText("New card details for backlog"),
      "Keep it short and precise.",
    );
    await user.click(within(backlog).getByRole("button", { name: "Add card to backlog" }));

    expect(screen.getByText("Write launch note")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Delete Write launch note" }));

    expect(screen.queryByText("Write launch note")).not.toBeInTheDocument();
    expect(document.querySelectorAll(".delete-burst-piece")).toHaveLength(12);
  });

  it("adds due dates in any column", async () => {
    const user = userEvent.setup();
    render(<KanbanBoard />);

    const backlog = screen.getByTestId("column-backlog");
    const dueDate = within(backlog).getByLabelText("New card due date for backlog");

    await user.type(within(backlog).getByLabelText("New card title for backlog"), "Send wrap-up");
    await user.type(
      within(backlog).getByLabelText("New card details for backlog"),
      "Close the project loop.",
    );
    await user.type(dueDate, "2026-09-04");
    await user.click(within(backlog).getByRole("button", { name: "Add card to backlog" }));

    expect(
      within(backlog).getByLabelText("Due date for Send wrap-up: 09/04/2026"),
    ).toBeInTheDocument();
    expect(
      within(backlog).queryByLabelText("Due date for Send wrap-up"),
    ).not.toBeInTheDocument();
  });
});
