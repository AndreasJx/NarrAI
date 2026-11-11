import { expect, test } from "@playwright/test";

test("cadastro, roteiro, aprovação, render e publicação simulada", async ({ page }) => {
  const email = `smoke-${Date.now()}@example.com`;

  await page.goto("/");
  await expect(page).toHaveURL(/\/login/);

  await page.getByRole("link", { name: "Criar conta" }).click();
  await page.getByLabel("Seu nome").fill("Smoke Test");
  await page.getByLabel("E-mail").fill(email);
  await page.getByLabel("Senha").fill("senha-segura-123");
  await page.getByLabel("Nome do estúdio ou organização").fill("Estúdio Smoke");
  await page.getByRole("button", { name: "Criar conta" }).click();
  await expect(page).toHaveURL(/\/$/);

  await page.getByRole("button", { name: "Criar novo vídeo" }).click();
  await page.getByLabel("Tema").fill("Por que o céu é azul durante o dia");
  await page.getByRole("button", { name: /Criar briefing e roteiro/ }).click();
  await expect(page).toHaveURL(/tab=roteiro/, { timeout: 60_000 });

  await page.getByRole("button", { name: /Aprovar versão/ }).click();
  await page.getByRole("button", { name: "Render e prévia" }).click();
  await page.getByRole("button", { name: /Renderizar vídeo/ }).click();
  await expect(page.getByText("Concluído").first()).toBeVisible({ timeout: 110_000 });

  await page.getByRole("button", { name: /Aprovar publicação/ }).click();
  await page.getByRole("button", { name: "Publicação", exact: true }).click();
  await page.getByRole("button", { name: "Ativar" }).click();
  await page.getByRole("button", { name: /Publicar \(simulado\)/ }).click();
  await expect(page.getByRole("cell", { name: "Publicado" }).first()).toBeVisible();
});
