import { test, expect } from '@playwright/test';

test.describe('Kanban Application E2E Tests', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  test('should load board with 5 default columns and initial dummy cards', async ({ page }) => {
    await expect(page.locator('h1')).toContainText('Kanban Workspace');
    
    // Verify 5 columns exist
    await expect(page.getByTestId('column-backlog')).toBeVisible();
    await expect(page.getByTestId('column-ready')).toBeVisible();
    await expect(page.getByTestId('column-in-progress')).toBeVisible();
    await expect(page.getByTestId('column-review')).toBeVisible();
    await expect(page.getByTestId('column-done')).toBeVisible();

    // Verify dummy card exists
    await expect(page.getByTestId('card-card-1')).toBeVisible();
    await expect(page.getByText('Design System Architecture')).toBeVisible();
  });

  test('should allow inline column renaming', async ({ page }) => {
    const columnHeader = page.getByTestId('column-title-backlog');
    await columnHeader.click();

    const titleInput = page.getByTestId('column-title-input-backlog');
    await titleInput.fill('Feature Backlog');
    await titleInput.press('Enter');

    await expect(page.getByTestId('column-title-backlog')).toHaveText('Feature Backlog');
  });

  test('should toggle column due date requirement and display requirement badges', async ({ page }) => {
    const toggleBtn = page.getByTestId('toggle-duedate-req-backlog');
    await expect(toggleBtn).toContainText('Optional Due Date');

    await toggleBtn.click();
    await expect(toggleBtn).toContainText('Due Date Required');

    // Card-1 in backlog does not have a due date, so it should show requirement badge
    const card1 = page.getByTestId('card-card-1');
    await expect(card1.getByText('Due Date Required')).toBeVisible();
  });

  test('should add a new card to a column', async ({ page }) => {
    await page.getByTestId('add-card-button-ready').click();

    await expect(page.getByTestId('add-card-modal')).toBeVisible();

    await page.getByTestId('card-title-input').fill('Playwright Test Card');
    await page.getByTestId('card-details-input').fill('Details for automated integration test.');
    await page.getByTestId('card-duedate-input').fill('2026-12-31');

    await page.getByTestId('submit-card-button').click();

    await expect(page.getByTestId('add-card-modal')).not.toBeVisible();
    await expect(page.getByText('Playwright Test Card')).toBeVisible();
    await expect(page.getByText('Details for automated integration test.')).toBeVisible();
  });

  test('should delete a card with particle explosion trigger', async ({ page }) => {
    const card1 = page.getByTestId('card-card-1');
    await expect(card1).toBeVisible();

    const deleteBtn = page.getByTestId('delete-card-card-1');
    await deleteBtn.click();

    // Verify card is removed from board
    await expect(page.getByTestId('card-card-1')).not.toBeVisible();
  });
});
