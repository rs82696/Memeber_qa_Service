# Member Question-Answering Service

This repo contains a small API service that answers natural-language questions
about members using data from the public `GET /messages` endpoint
(see the provided Swagger UI).

**Example questions:**

- “When is Layla planning her trip to London?”
- “How many cars does Vikram Desai have?”
- “What are Amira’s favorite restaurants?”

**API Contract**

- Endpoint: `POST /ask` (also supports `GET /ask?question=...`)
- Request body:

  ```json
  { "question": "When is Layla planning her trip to London?" }

# My Approach (Implemented Solution)

The goal was to build a small, production-style question–answering API that can answer natural-language questions about members based on their messages.

Here’s the approach I implemented end-to-end:

1. **Data loading from the public API**
   - On startup, the service calls the provided endpoint:
     ```text
     GET /messages
     ```
   - The response is parsed into an in-memory list of `Message` objects:
     - `id`
     - `user_id`
     - `user_name`
     - `timestamp`
     - `message` (free-text)
   - I keep both the full list of messages and the unique set of member names in memory for fast lookup.

2. **Member detection from the question**
   - When a question comes in to `/ask`, I first try to infer which member it’s about.
   - I fuzzy-match the question text against:
     - The full `user_name` (e.g., `"Layla Kawaguchi"`)
     - The first name (e.g., `"Layla"`)
   - I use `rapidfuzz.partial_ratio` and pick the best match above a threshold (70). If a member is detected, I restrict retrieval to only that member’s messages; otherwise, I search across all messages.

3. **Lightweight retrieval (lexical scoring)**
   - I tokenize the question and each message, filter out basic English stopwords, and compute a simple score:
     - **Overlap score** = number of shared tokens between question and message.
     - **Bonus** if the message’s `user_name` matches the detected member.
   - I sort messages by this score and keep the **top 10** as the “context window” for answering.
   - If no messages score > 0 for the detected member, I fall back to scoring all messages.

4. **LLM-based answer generation (RAG-style)**
   - With the top-k messages selected, I construct a prompt for an OpenAI chat model (e.g., `gpt-4o-mini`):
     - System prompt: explains that the model must **only** use the provided messages and must answer “I can’t tell from the available messages.” if the answer isn’t clearly stated.
     - User prompt: includes the natural-language question and a numbered list of messages, each with:
       - `user_name`
       - `timestamp`
       - `text`
   - The model returns a short answer, which I return as:
     ```json
     { "answer": "..." }
     ```

5. **Handling relative dates**
   - Many messages use phrases like “this Friday” or “next month”.
   - I include the original `timestamp` for each message in the context, so the model can interpret relative time expressions relative to when the message was sent, not relative to “now”.

6. **API surface**
   - `GET /health` – health check plus number of messages loaded.
   - `POST /ask` – main endpoint that accepts `{"question": "..."}` and returns `{"answer": "..."}`.
   - `GET /ask?question=...` – convenience GET version of the same.
   - `GET /` – redirects to `/docs` (Swagger UI) for easy manual testing.

This gives a simple but realistic retrieval-augmented QA system:
- No external database or vector store required.
- Still flexible enough to handle a variety of natural-language questions over the member data.

