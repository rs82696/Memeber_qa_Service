# app/main.py
import os
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.qa_engine import QAEngine

# Default messages API URL (can be overridden with env var)
MESSAGES_URL = os.getenv(
    "MESSAGES_URL",
    "https://november7-730026606190.europe-west1.run.app/messages",
)

app = FastAPI(title="Member QA Service")

qa_engine: QAEngine | None = None


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    answer: str


@app.get("/", include_in_schema=False)
def root():
    """
    Redirect the root URL to the Swagger UI.
    So opening http://127.0.0.1:8000 goes straight to /docs.
    """
    return RedirectResponse(url="/docs")


@app.on_event("startup")
def startup_event():
    """
    Initialize the QA engine at app startup by loading the messages.
    """
    global qa_engine
    qa_engine = QAEngine(messages_url=MESSAGES_URL)


@app.get("/health")
def health():
    """
    Simple health check that also shows how many messages were loaded.
    """
    if qa_engine is None:
        raise HTTPException(status_code=500, detail="QA engine not initialized")
    return {"status": "ok", "messages_loaded": len(qa_engine.messages)}


@app.post("/ask", response_model=AskResponse)
def ask_post(req: AskRequest):
    """
    POST /ask
    Body: { "question": "..." }
    """
    if qa_engine is None:
        raise HTTPException(status_code=500, detail="QA engine not initialized")

    answer = qa_engine.answer(req.question)
    return AskResponse(answer=answer)


@app.get("/ask", response_model=AskResponse)
def ask_get(question: str = Query(..., description="Natural-language question")):
    """
    GET /ask?question=...
    """
    if qa_engine is None:
        raise HTTPException(status_code=500, detail="QA engine not initialized")

    answer = qa_engine.answer(question)
    return AskResponse(answer=answer)


if __name__ == "__main__":
    # Allows you to run: python app/main.py
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
