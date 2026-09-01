import { expect, test } from "@playwright/test";

test("single-board MVP happy path", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Launch Kanban" })).toBeVisible();
  await expect(page.locator("[data-testid^='column-']")).toHaveCount(5);
  await expect(page.getByText("Shape MVP scope")).toBeVisible();

  await page.getByRole("button", { name: "Edit Backlog" }).click();
  await page.getByLabel("Rename Backlog").fill("Ideas");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Ideas" })).toBeVisible();

  const ideas = page.getByTestId("column-backlog");
  await ideas.getByLabel("New card title for backlog").fill("Prepare status note");
  await ideas.getByLabel("New card details for backlog").fill("Share the MVP state.");
  await ideas.getByLabel("New card due date for backlog").fill("2026-09-04");
  await ideas.getByRole("button", { name: "Add card to backlog" }).click();
  await expect(page.getByText("Prepare status note")).toBeVisible();
  await expect(
    ideas.getByLabel("Due date for Prepare status note: 09/04/2026"),
  ).toBeVisible();

  await page.getByRole("button", { name: "Delete Prepare status note" }).click();
  await expect(page.getByText("Prepare status note")).toHaveCount(0);

  const done = page.getByTestId("column-done");
  await done.getByLabel("New card title for done").fill("Ship final note");
  await done.getByLabel("New card details for done").fill("Add a date to the final column.");
  await done.getByLabel("New card due date for done").fill("2026-09-04");
  await done.getByRole("button", { name: "Add card to done" }).click();
  await expect(done.getByLabel("Due date for Ship final note")).toHaveValue("2026-09-04");
});

test("moves a card between columns with drag and drop", async ({ page }) => {
  await page.goto("/");

  const dragHandle = page.getByRole("button", { name: "Drag Shape MVP scope" });
  const reviewColumn = page.getByTestId("column-review");
  const start = await dragHandle.boundingBox();
  const target = await reviewColumn.boundingBox();

  expect(start).not.toBeNull();
  expect(target).not.toBeNull();

  await page.mouse.move(start!.x + start!.width / 2, start!.y + start!.height / 2);
  await page.mouse.down();
  await page.mouse.move(target!.x + target!.width / 2, target!.y + 160, { steps: 8 });
  await page.mouse.up();

  await expect(reviewColumn.getByText("Shape MVP scope")).toBeVisible();
});
