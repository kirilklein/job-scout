import { test, expect } from "@playwright/test";

const headers = { "X-Scout-Client": "job-scout" };

async function reset(request) {
  const conversation = await (await request.get("/api/interview")).json();
  await request.delete(`/api/interview?revision=${conversation.revision}`, {
    headers,
  });
  await request.put("/api/profile", { headers, data: {} });
}

test("interview drafts become editable confirmed experience without requiring target roles", async ({
  page,
  request,
}) => {
  await reset(request);
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await page.getByRole("button", { name: "Your profile" }).click();
  const answer =
    "I built a Python survey dashboard for a volunteer group and taught three people to use it.";
  await page.getByLabel("Your answer", { exact: true }).fill(answer);
  await page.getByRole("button", { name: "Continue conversation" }).click();
  await expect(page.locator("#story-question")).toContainText(
    "What did you own",
  );
  await expect(page.locator("#story-suggestions")).toContainText(answer);
  expect(
    (await (await request.get("/api/state")).json()).profile.background,
  ).toEqual([]);
  await page.getByRole("button", { name: "Add to profile draft" }).click();
  await page.getByLabel("Detail 1 title").fill("Volunteer survey dashboard");
  expect(
    (await (await request.get("/api/state")).json()).profile.background,
  ).toEqual([]);
  await page.getByRole("button", { name: "Save my profile" }).click();
  await expect(page.getByText("Profile saved", { exact: true })).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "Your profile" }).click();
  await expect(page.getByLabel("Detail 1 title")).toHaveValue(
    "Volunteer survey dashboard",
  );
  await expect(page.getByLabel("Detail 1 description")).toHaveValue(answer);
  await expect(page.locator("#story-progress")).toContainText("1 answers");
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Clear conversation" }).click();
  await expect(page.locator("#story-progress")).toContainText("0 answers");
  await expect(page.getByLabel("Detail 1 description")).toHaveValue(answer);
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.screenshot({
    path: "test-results/experience-desktop.png",
    fullPage: true,
  });
  expect(errors).toEqual([]);
});

test("mobile CV retention is opt-in and rendered safely in the conversation", async ({
  page,
  request,
}) => {
  await reset(request);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await page.getByRole("button", { name: "Your profile" }).click();
  await expect(page.locator("#resume-file")).toBeEnabled();
  const cv =
    "Research volunteer using Python for surveys. <img src=x onerror=alert(1)>";
  const file = {
    name: "cv.txt",
    mimeType: "text/plain",
    buffer: Buffer.from(cv),
  };
  await page.locator("#resume-file").setInputFiles(file);
  await expect(page.locator("#upload-status")).toContainText("was not stored");
  expect((await (await request.get("/api/interview")).json()).messages).toEqual(
    [],
  );
  await page.getByLabel("Keep the extracted CV text").check();
  await page.locator("#resume-file").setInputFiles(file);
  await expect(page.locator("#upload-status")).toContainText(
    "Nothing was sent to a model",
  );
  await page.locator("#conversation-history > summary").click();
  await page.getByText("Imported CV · stored locally", { exact: true }).click();
  await expect(page.locator("#story-messages")).toContainText(cv);
  await expect(page.locator("#story-messages img")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Ask Brigade" }),
  ).toBeDisabled();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/experience-mobile.png",
    fullPage: true,
  });
});

test("model assistance requires consent and keeps answers after a provider error", async ({
  page,
  request,
}) => {
  await reset(request);
  await page.route("**/api/interview?*", async (route) => {
    const response = await route.fetch();
    await route.fulfill({
      response,
      json: { ...(await response.json()), brigade_available: true },
    });
  });
  let calls = 0;
  await page.route("**/api/interview/assist?*", async (route) => {
    calls++;
    expect(route.request().postDataJSON().share_with_model).toBe(true);
    await route.fulfill({
      status: 502,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Provider login needs attention" }),
    });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Your profile" }).click();
  await page
    .getByLabel("Your answer", { exact: true })
    .fill("I mentored three volunteers on a research project.");
  await page.getByRole("button", { name: "Continue conversation" }).click();
  await expect(page.locator("#story-progress")).toContainText("1 answers");
  const assist = page.getByRole("button", { name: "Ask Brigade" });
  await expect(assist).toBeDisabled();
  expect(calls).toBe(0);
  await page.getByLabel("Share this conversation").check();
  await assist.click();
  await expect(page.locator("#interview-status")).toContainText(
    "Provider login needs attention",
  );
  await expect(page.getByLabel("Share this conversation")).not.toBeChecked();
  await expect(assist).toBeDisabled();
  await expect(page.locator("#story-progress")).toContainText("1 answers");
  expect(calls).toBe(1);
});
