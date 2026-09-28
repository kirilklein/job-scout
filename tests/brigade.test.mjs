import assert from "node:assert/strict";
import test from "node:test";
import extension, { createTools } from "../brigade/extension/index.mjs";

test("registers owner tools without application-sending capabilities", () => {
  const registered = [];
  extension.register({ tool: (tool) => registered.push(tool) });
  assert.deepEqual(
    registered.map((t) => t.name),
    [
      "scout_interview_context",
      "scout_interview_submit",
      "scout_profile",
      "scout_add_source",
      "scout_refresh",
      "scout_candidates",
      "scout_review",
    ],
  );
  assert.ok(
    registered.every((t) => t.ownerOnly && t.parameters.type === "object"),
  );
});

test("interview tools use only the selected task and submit a draft", async (t) => {
  const taskId = "a".repeat(32);
  t.mock.method(globalThis, "fetch", async (url, options) => {
    assert.equal(new URL(url).pathname, `/api/interview/tasks/${taskId}`);
    const body = JSON.parse(options.body);
    assert.equal(body.revision, 4);
    assert.equal(body.task_id, undefined);
    return Response.json({ ok: true });
  });
  await createTools()
    .find((tool) => tool.name === "scout_interview_submit")
    .execute("1", {
      task_id: taskId,
      revision: 4,
      question: "What did you personally contribute?",
      title: "Your role",
      category: "experience",
      suggestions: [],
    });
});

test("job search receives confirmed background, not interview drafts", async (t) => {
  const background = [
    {
      category: "project",
      title: "Community data project",
      detail: "Analyzed survey data",
    },
  ];
  t.mock.method(globalThis, "fetch", async () =>
    Response.json({
      profile: { background },
      profile_version: "p",
      sources: [],
      jobs: [],
      interview: { messages: ["private draft"] },
    }),
  );
  const result = JSON.parse(
    (
      await createTools()
        .find((tool) => tool.name === "scout_profile")
        .execute("1", {})
    ).content[0].text,
  );
  assert.deepEqual(result.profile.background, background);
  assert.equal(result.interview, undefined);
});

test("limits candidates, excludes dismissed/closed jobs and preserves versions", async (t) => {
  t.mock.method(globalThis, "fetch", async () =>
    Response.json({
      profile_version: "p1",
      jobs: [
        {
          id: "a",
          version: "j1",
          active: true,
          enabled: true,
          status: "new",
          match: { eligible: true },
          description: "Python required",
        },
        {
          id: "b",
          active: true,
          enabled: true,
          status: "dismissed",
          match: { eligible: true },
          description: "Hidden",
        },
      ],
    }),
  );
  const tool = createTools().find((t) => t.name === "scout_candidates");
  const result = JSON.parse(
    (await tool.execute("1", { limit: 1 })).content[0].text,
  );
  assert.equal(result.jobs.length, 1);
  assert.equal(result.jobs[0].version, "j1");
  assert.equal(result.profile_version, "p1");
});

test("surfaces API errors and uses local client header", async (t) => {
  t.mock.method(globalThis, "fetch", async (url, options) => {
    assert.equal(new URL(url).hostname, "127.0.0.1");
    assert.equal(options.headers["X-Scout-Client"], "job-scout");
    return Response.json({ detail: "Profile changed" }, { status: 409 });
  });
  await assert.rejects(
    createTools()
      .find((t) => t.name === "scout_refresh")
      .execute("1", {}),
    /409.*Profile changed/,
  );
});
