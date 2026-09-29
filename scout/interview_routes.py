from fastapi import APIRouter, HTTPException, Request

from .interview import (
    Answer,
    AssistRequest,
    InterviewResult,
    add_answer,
    question_at,
    read_interview,
    validate_quotes,
)


def interview_router(live, demo, assistant):
    from typing import Literal

    router = APIRouter(prefix="/api/interview")
    Mode = Literal["live", "demo"]

    def store(mode):
        return demo if mode == "demo" else live

    @router.get("")
    def read(mode: Mode = "live"):
        return {**read_interview(store(mode)), "brigade_available": assistant.available()}

    @router.post("/answer")
    def answer(value: Answer, mode: Mode = "live"):
        try:
            return add_answer(store(mode), value)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.delete("")
    def clear(revision: int, mode: Mode = "live"):
        try:
            return store(mode).save_interview(
                {
                    "step": 0,
                    "messages": [],
                    "suggestions": [],
                    "question": question_at(0),
                    "question_source": "guided",
                },
                revision,
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.delete("/suggestions/{sid}")
    def dismiss(sid: str, revision: int, mode: Mode = "live"):
        conversation = read_interview(store(mode))
        conversation["suggestions"] = [s for s in conversation["suggestions"] if s["id"] != sid]
        try:
            return store(mode).save_interview(conversation, revision)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post("/assist")
    async def assist(value: AssistRequest, request: Request, mode: Mode = "live"):
        if not assistant.available():
            raise HTTPException(
                422, "Set up Brigade with ./brigade.sh setup and ./brigade.sh onboard first."
            )
        try:
            return await assistant.assist(store(mode), value, str(request.base_url).rstrip("/"))
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except TimeoutError as exc:
            raise HTTPException(
                504, "Brigade took too long. Your conversation is safe; try again."
            ) from exc
        except (RuntimeError, OSError) as exc:
            raise HTTPException(502, str(exc)) from exc

    @router.get("/tasks/{task_id}")
    def context(task_id: str):
        task = assistant.tasks.get(task_id)
        if not task:
            raise HTTPException(404, "This interview request has expired")
        return task["context"]

    @router.post("/tasks/{task_id}")
    def submit(task_id: str, result: InterviewResult):
        task = assistant.tasks.get(task_id)
        if not task:
            raise HTTPException(404, "This interview request has expired")
        if result.revision != task["context"]["conversation"]["revision"]:
            raise HTTPException(409, "Conversation version does not match this request")
        # Validate grounding before acknowledging so Brigade can correct an invalid quote.
        try:
            validate_quotes(task["context"]["conversation"], result.suggestions)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if task["result"] is not None:
            raise HTTPException(409, "A response has already been submitted")
        task["result"] = result
        return {"ok": True, "message": "Draft submitted for user review. Stop now."}

    return router
