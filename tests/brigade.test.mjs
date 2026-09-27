import assert from "node:assert/strict";
import test from "node:test";
import extension, { createTools } from "../brigade/extension/index.mjs";

test("registers owner tools without application-sending capabilities", () => {
  const registered = [];
  extension.register({ tool: (tool) => registered.push(tool) });
  assert.deepEqual(
    registered.map((t) => t.name),
    [
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
