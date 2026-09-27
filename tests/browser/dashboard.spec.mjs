import { test, expect } from "@playwright/test";

test("onboarding, demo, save, dismiss, profile and persistence", async ({
  page,
}) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Your next chapter." }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Try the demo", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Your next chapter, Alex." }),
  ).toBeVisible();
  const save = page.getByRole("button", {
    name: "Save Senior Machine Learning Engineer at Northstar Health",
    exact: true,
  });
  await save.click();
  await page.getByRole("button", { name: "Saved jobs", exact: false }).click();
  await expect(
    page.getByRole("heading", {
      name: "Senior Machine Learning Engineer",
      exact: true,
    }),
  ).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "Saved jobs", exact: false }).click();
  await page.getByRole("button", { name: "View opportunity" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page
    .getByLabel("Optional feedback for future Brigade reviews")
    .fill("Prefer fully remote");
  await page.getByRole("button", { name: "Dismiss role" }).click();
  await page.getByRole("button", { name: "Dismissed", exact: true }).click();
  await expect(
    page.getByRole("heading", {
      name: "Senior Machine Learning Engineer",
      exact: true,
    }),
  ).toBeVisible();
  await page.getByRole("button", { name: "View opportunity" }).click();
  await expect(
    page.getByLabel("Optional feedback for future Brigade reviews"),
  ).toHaveValue("Prefer fully remote");
  await page.keyboard.press("Escape");
  await page
    .getByRole("button", { name: "Your profile", exact: false })
    .click();
  await page.getByLabel("Your name", { exact: true }).fill("Taylor");
  await page.getByRole("button", { name: "Save my profile" }).click();
  await expect(page.getByText("Profile saved", { exact: true })).toBeVisible();
  await page
    .getByRole("button", { name: "Go to my workspace →", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Your next chapter." }),
  ).toBeVisible();
  await expect(page.locator(".job-card")).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("mobile layout, resume draft and keyboard detail dismissal", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await page
    .getByRole("button", { name: "Your profile", exact: false })
    .click();
  await page.locator("#resume-file").setInputFiles({
    name: "resume.txt",
    mimeType: "text/plain",
    buffer: Buffer.from(
      "Data scientist experienced in Python, SQL and causal inference for healthcare research.",
    ),
  });
  await expect(page.locator('input[name="skills"]')).toHaveValue(/Python/);
  await expect(page.locator("#upload-status")).toContainText(
    "Review these suggested",
  );
  await page
    .getByRole("button", { name: "Discover", exact: false })
    .first()
    .click();
  await page.getByRole("button", { name: "Try the demo", exact: true }).click();
  await page
    .locator(".job-card")
    .first()
    .getByRole("button", { name: "View opportunity" })
    .click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).not.toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({ path: "test-results/mobile.png", fullPage: true });
});

test("desktop demo screenshot and source form", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.goto("/");
  await page.getByRole("button", { name: "Try the demo", exact: true }).click();
  await expect(page.locator(".job-card").first()).toBeVisible();
  await page.screenshot({ path: "test-results/desktop.png", fullPage: true });
  await page
    .getByRole("button", { name: "Go to my workspace →", exact: true })
    .click();
  await page.getByRole("button", { name: "Search sources" }).click();
  await page
    .getByRole("switch", { name: "Enable daily updates", exact: true })
    .check();
  await expect(
    page.getByRole("switch", { name: "Enable daily updates", exact: true }),
  ).toBeChecked();
  await page
    .getByRole("switch", { name: "Enable daily updates", exact: true })
    .uncheck();
  await page.getByLabel("Company name").fill("Example Employer");
  await page.getByLabel("Board identifier").fill("example-employer");
  await page.getByRole("button", { name: "Add source →" }).click();
  await expect(
    page.getByText("Example Employer", { exact: true }),
  ).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "Search sources" }).click();
  await expect(
    page.getByText("Example Employer", { exact: true }),
  ).toBeVisible();
});
