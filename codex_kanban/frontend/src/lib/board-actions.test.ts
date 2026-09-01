import { describe, expect, it } from "vitest";

import {
  addCard,
  deleteCard,
  findCardLocation,
  moveCard,
  renameColumn,
} from "./board-actions";
import type { BoardState } from "./board-data";

const board: BoardState = [
  {
    id: "one",
    title: "One",
    cards: [
      { id: "a", title: "A", details: "Alpha" },
      { id: "b", title: "B", details: "Beta" },
    ],
  },
  {
    id: "two",
    title: "Two",
    cards: [{ id: "c", title: "C", details: "Gamma" }],
  },
];

describe("board actions", () => {
  it("renames one fixed column", () => {
    const next = renameColumn(board, "one", "Discovery");

    expect(next[0].title).toBe("Discovery");
    expect(next[1].title).toBe("Two");
  });

  it("adds a new card to the top of a column", () => {
    const next = addCard(board, "two", { id: "d", title: "D", details: "Delta" });

    expect(next[1].cards.map((card) => card.id)).toEqual(["d", "c"]);
  });

  it("deletes an existing card", () => {
    const next = deleteCard(board, "b");

    expect(next[0].cards.map((card) => card.id)).toEqual(["a"]);
  });

  it("finds a card location", () => {
    expect(findCardLocation(board, "c")).toEqual({ columnId: "two", cardIndex: 0 });
  });

  it("moves a card between columns", () => {
    const next = moveCard(board, "b", "two", 1);

    expect(next[0].cards.map((card) => card.id)).toEqual(["a"]);
    expect(next[1].cards.map((card) => card.id)).toEqual(["c", "b"]);
  });

});
