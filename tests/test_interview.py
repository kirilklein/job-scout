import httpx
import pytest
from fastapi.testclient import TestClient

from scout.app import create_app
from scout.interview import Answer, InterviewResult, add_answer, apply_result, read_interview


@pytest.fixture
def client(tmp_path):
    with TestClient(
        create_app(tmp_path, schedule=False), headers={"X-Scout-Client": "job-scout"}
    ) as client:
        yield client


def answer(client, text="I built a survey dashboard for a volunteer group using Python."):
    revision = client.get("/api/interview").json()["revision"]
    response = client.post("/api/interview/answer", json={"revision": revision, "text": text})
    assert response.status_code == 200
    return response.json()


def test_conversation_persists_drafts_without_changing_confirmed_profile(client):
    original = client.get("/api/state").json()["profile"]
    conversation = answer(client)
    assert conversation["suggestions"][0]["category"] == "project"
    assert conversation["suggestions"][0]["detail"] == conversation["messages"][1]["text"]
    assert conversation["question"]["title"] == "Your responsibilities"
    assert client.get("/api/interview").json()["revision"] == 1
    assert client.get("/api/state").json()["profile"] == original
    assert client.get("/api/interview?mode=demo").json()["messages"] == []


def test_accepting_background_preserves_preferences_after_clearing_conversation(client):
    draft = answer(client)["suggestions"][0]
    profile = client.get("/api/state").json()["profile"]
    profile.update(roles=["Data scientist"], remote="remote", notes="Prefer research")
    profile["background"] = [{k: draft[k] for k in ["id", "category", "title", "detail", "quote"]}]
    assert client.put("/api/profile", json=profile).status_code == 200
    saved = client.get("/api/state").json()
    assert saved["profile"]["background"][0]["detail"] == draft["detail"]
    assert saved["profile"]["remote"] == "remote"
    revision = client.get("/api/interview").json()["revision"]
    assert client.delete(f"/api/interview?revision={revision}").status_code == 200
    assert client.get("/api/state").json()["profile"] == saved["profile"]
    assert client.get("/api/interview").json()["messages"] == []


def test_resume_requires_explicit_local_retention_and_is_replaceable(client):
    files = {
        "file": (
            "cv.txt",
            b"I worked on a community research project and analyzed survey responses.",
        )
    }
    assert client.post("/api/resume", files=files).status_code == 200
    assert client.get("/api/interview").json()["messages"] == []
    response = client.post("/api/resume?remember=true&revision=0", files=files)
    assert response.status_code == 200
    conversation = client.get("/api/interview").json()
    assert conversation["messages"][0]["role"] == "resume"
    assert "Nothing was sent to a model" in response.json()["message"]
    assert client.post("/api/resume?remember=true&revision=1", files=files).status_code == 200
    assert len(client.get("/api/interview").json()["messages"]) == 1
    assert client.get("/api/state").json()["profile"]["background"] == []


def test_stale_writes_and_deleted_source_quotes_are_rejected(client):
    conversation = answer(client)
    assert (
        client.post(
            "/api/interview/answer", json={"revision": 0, "text": "A concurrent answer"}
        ).status_code
        == 409
    )
    assert client.delete("/api/interview?revision=0").status_code == 409
    source_id = conversation["messages"][1]["id"]
    result = InterviewResult(
        revision=1,
        question="What changed as a result?",
        category="achievement",
        title="Impact",
        suggestions=[
            {
                "category": "project",
                "title": "Survey dashboard",
                "detail": "Built a dashboard",
                "source_id": source_id,
                "quote": "I built a survey dashboard",
            }
        ],
    )
    assert client.delete("/api/interview?revision=1").status_code == 200
    with pytest.raises(ValueError, match="no matching quote"):
        apply_result(client.app.state.live, result)


def test_model_assistance_requires_explicit_sharing_and_setup(client):
    answer(client)
    assert client.post("/api/interview/assist", json={"revision": 1}).status_code == 422
    assert (
        client.post(
            "/api/interview/assist", json={"revision": 1, "share_with_model": False}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/interview/assist", json={"revision": 1, "share_with_model": True}
        ).status_code
        == 422
    )
    assert client.app.state.interviewer.tasks == {}


def test_model_roundtrip_validates_quotes_returns_followup_and_keeps_profile_unchanged(
    client, monkeypatch
):
    answer(client)
    assistant = client.app.state.interviewer
    monkeypatch.setattr(assistant, "available", lambda: True)
    captured = []

    async def runner(root, task_id, url):
        captured.append(task_id)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=client.app),
            base_url="http://testserver",
            headers={"X-Scout-Client": "job-scout"},
        ) as bridge:
            context = (await bridge.get(f"/api/interview/tasks/{task_id}")).json()
            assert context["profile"]["background"] == []
            source_id = context["conversation"]["messages"][1]["id"]
            result = {
                "revision": 1,
                "question": "How did the volunteer group use your dashboard?",
                "category": "achievement",
                "title": "How the dashboard helped",
                "suggestions": [
                    {
                        "category": "project",
                        "title": "Volunteer survey dashboard",
                        "detail": "Built a Python survey dashboard for a volunteer group.",
                        "source_id": source_id,
                        "quote": "Invented a revolutionary survey tool",
                    }
                ],
            }
            assert (
                await bridge.post(f"/api/interview/tasks/{task_id}", json=result)
            ).status_code == 422
            result["suggestions"][0]["quote"] = (
                "I built a survey dashboard for a volunteer group using Python."
            )
            assert (
                await bridge.post(f"/api/interview/tasks/{task_id}", json=result)
            ).status_code == 200

    assistant.runner = runner
    response = client.post("/api/interview/assist", json={"revision": 1, "share_with_model": True})
    assert response.status_code == 200
    assert response.json()["question_source"] == "brigade"
    assert len(response.json()["suggestions"]) == 2
    assert client.get("/api/state").json()["profile"]["background"] == []
    assert client.get(f"/api/interview/tasks/{captured[0]}").status_code == 404


def test_model_failure_and_timeout_preserve_conversation(client, monkeypatch):
    before = answer(client)
    assistant = client.app.state.interviewer
    monkeypatch.setattr(assistant, "available", lambda: True)

    async def runner(*args):
        raise TimeoutError()

    assistant.runner = runner
    assert (
        client.post(
            "/api/interview/assist", json={"revision": 1, "share_with_model": True}
        ).status_code
        == 504
    )
    assert read_interview(client.app.state.live) == before
    assert assistant.tasks == {}


def test_model_result_cannot_overwrite_a_newer_answer(client, monkeypatch):
    answer(client)
    assistant = client.app.state.interviewer
    monkeypatch.setattr(assistant, "available", lambda: True)

    async def runner(root, task_id, url):
        task = assistant.tasks[task_id]
        task["result"] = InterviewResult(
            revision=1,
            question="What would you do next?",
            category="preference",
            title="Next step",
            suggestions=[],
        )
        add_answer(
            client.app.state.live,
            Answer(revision=1, text="I owned the analysis and worked with three volunteers."),
        )

    assistant.runner = runner
    assert (
        client.post(
            "/api/interview/assist", json={"revision": 1, "share_with_model": True}
        ).status_code
        == 409
    )
    assert client.get("/api/interview").json()["step"] == 2


def test_legacy_profiles_load_with_empty_background(client):
    client.app.state.live.set_setting("profile", {"roles": ["Researcher"], "skills": ["Python"]})
    profile = client.get("/api/state").json()["profile"]
    assert profile["background"] == []
    assert profile["roles"] == ["Researcher"]


@pytest.mark.parametrize("text", [" " * 20, "short", "x" * 3001])
def test_invalid_answers_do_not_advance_the_conversation(client, text):
    assert (
        client.post("/api/interview/answer", json={"revision": 0, "text": text}).status_code == 422
    )
    assert client.get("/api/interview").json()["revision"] == 0


def test_blank_quotes_and_unknown_source_ids_are_rejected(client):
    from pydantic import ValidationError

    from scout.interview import Suggestion, validate_quotes

    fields = {
        "category": "project",
        "title": "Project",
        "detail": "A project",
        "source_id": "missing",
    }
    with pytest.raises(ValidationError):
        Suggestion(**fields, quote=" " * 10)
    conversation = answer(client)
    with pytest.raises(ValueError, match="no matching quote"):
        validate_quotes(conversation, [Suggestion(**fields, quote="I built a survey dashboard")])


def test_model_missing_result_preserves_conversation(client, monkeypatch):
    before = answer(client)
    assistant = client.app.state.interviewer
    monkeypatch.setattr(assistant, "available", lambda: True)

    async def runner(*args):
        return

    assistant.runner = runner
    response = client.post("/api/interview/assist", json={"revision": 1, "share_with_model": True})
    assert response.status_code == 502
    assert "no structured answer" in response.json()["detail"]
    assert read_interview(client.app.state.live) == before
    assert assistant.tasks == {}


def test_brigade_runner_invokes_isolated_local_cli(tmp_path):
    import asyncio
    import shutil

    from scout.interview import run_brigade

    if not shutil.which("node"):
        pytest.skip("Node is needed to exercise the Brigade subprocess")
    binary = tmp_path / ".brigade-runtime/node_modules/@spinabot/brigade/brigade.mjs"
    binary.parent.mkdir(parents=True)
    binary.write_text("""
import assert from 'node:assert/strict';
const args = process.argv.slice(2);
assert.equal(args[0], 'agent');
assert.equal(args[2], 'scout-interview-test-task');
assert.ok(args[4].endsWith('/.brigade/workspace'));
assert.ok(args[6].includes('scout_interview_context with task_id test-task'));
assert.equal(process.env.SCOUT_URL, 'http://127.0.0.1:8092');
assert.ok(process.env.BRIGADE_CONFIG_PATH.endsWith('/.brigade/brigade.json'));
""")
    asyncio.run(run_brigade(tmp_path, "test-task", "http://127.0.0.1:8092"))


def test_brigade_runner_terminates_a_timed_out_process(tmp_path, monkeypatch):
    import asyncio
    import signal

    from scout import interview

    class Process:
        pid = 12345
        returncode = None

        async def wait(self):
            if self.returncode is None:
                raise TimeoutError()
            return self.returncode

    process = Process()
    signals = []

    async def create(*args, **kwargs):
        return process

    def kill(pid, sig):
        assert pid == process.pid
        signals.append(sig)
        process.returncode = -sig

    monkeypatch.setattr(interview.asyncio, "create_subprocess_exec", create)
    monkeypatch.setattr(interview.os, "killpg", kill)
    with pytest.raises(TimeoutError):
        asyncio.run(interview.run_brigade(tmp_path, "test-task", "http://127.0.0.1:8092"))
    assert signals == [signal.SIGTERM]
