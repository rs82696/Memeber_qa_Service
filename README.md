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

# Design Notes – Alternative Approaches Considered

While building this question-answering system, I considered several different designs.  
The one implemented in this repo is a lightweight retrieval + LLM approach, but I evaluated a few alternatives:

**1. Simple Retrieval + LLM (Chosen Approach)**

**Idea:**  
- Fetch all messages from the `/messages` API and keep them in memory.
- Use fuzzy matching to detect which member the question is about.
- Use simple lexical scoring (token overlap) to select the top-k relevant messages.
- Call an LLM (OpenAI) with the question + selected messages and let it generate the answer, or say it cannot tell.

**Pros:**
- Very small amount of code and infrastructure.
- Easy to debug: I can log exactly which messages were sent to the LLM.
- Flexible: adding support for new question types usually requires no code changes.

**Cons:**
- Retrieval is bag-of-words, so it can miss semantic matches or synonyms.
- Depends on an external LLM API and network latency.

This is the approach I implemented because it’s simple, realistic, and enough for the scope of the assignment.

---

**2. Embeddings + Vector Search**

**Idea:**  
- Instead of lexical overlap, encode each message using embeddings (e.g., OpenAI embeddings or sentence-transformers).
- Store them in a vector index (FAISS, Chroma, or similar).
- For each question, embed the query, perform k-nearest-neighbor search over the message embeddings, and then call the LLM with those top results.

**Pros:**
- Much better semantic retrieval: handles paraphrases and synonyms well.
- Scales better if the number of messages grows a lot.

**Cons:**
- More moving parts: embedding pipeline + vector store.
- Slightly more complex deployment and operational overhead.

I decided this was overkill for a small take-home but would be a natural next step if the dataset or usage grew.

---

**3. Pure Rule-Based / Template System (No LLM)**

**Idea:**  
- Write patterns/regexes to detect specific types of facts in messages:
  - Travel bookings (destinations, dates).
  - Vehicle counts.
  - Restaurant names and favorites.
- Extract these into a structured store per member (e.g., `member_profile` dict).
- Answer questions by mapping question templates to fields in that profile.

**Pros:**
- No dependency on external LLMs or APIs.
- Fully deterministic and very fast at runtime.

**Cons:**
- Very brittle: every new question type or phrasing needs new rules.
- Hard to maintain and extend to more open-ended questions.

I considered this but rejected it because the assignment is explicitly about natural-language Q&A, and rule-based parsing would be fragile against varied phrasing.

---

**4. Pre-Computed Member Profiles (ETL + Hybrid)**

**Idea:**  
- Periodically run a batch job that:
  - Pulls messages from the API.
  - Uses an LLM (or rules) to extract structured facts into a “member profile” table (e.g., number of cars, favorite restaurants, upcoming trips).
- At query time:
  - First answer from the structured profile.
  - Fall back to the raw messages + LLM if needed.

**Pros:**
- Very fast at query time for common questions (simple DB lookups).
- Good foundation if this data is also needed for analytics or dashboards.

**Cons:**
- More complex architecture (scheduled ETL, storage, schema design).
- Overkill for a small demo service that only needs live Q&A.

I treated this as a longer-term evolution option if this were a real product.

---

**5. Fine-Tuning or Domain-Specific Model**

**Idea:**  
- Collect a labeled dataset of (question, answer, supporting messages) pairs.
- Fine-tune a smaller model to directly produce answers from the messages, or to rank messages more accurately.

**Pros:**
- Potentially lower latency and cost at scale.
- Model can learn domain-specific patterns from the member data.

**Cons:**
- Requires labeled training data and an MLOps pipeline.
- Much more work than needed for this assignment.

For a take-home task, I preferred to focus on a transparent retrieval + LLM design instead of training custom models.

## Data Insights & Anomalies

While exploring the `/messages` dataset, a few quirks and potential data-quality issues show up:

- **Consistent member identities, but some shared identifiers**  
  Each of the 10 members has a stable `user_id`–`user_name` mapping, which is good. However, some personal identifiers are reused:
  - The phone number `987-654-3210` appears as Layla Kawaguchi’s mobile number and later as Thiago Monteiro’s “new number”.
  - The passport number `987654321` is used for both Sophia Al-Farsi and Vikram Desai.
  These patterns look more like test/synthetic data than realistic production records, but they’re worth noting.

- **Synthetic-looking numbers and addresses**  
  Several values are clearly placeholder-ish, e.g.:
  - Highly patterned numbers like `123456789`, `1122334455`, `001-235-789`, and `876543210` for membership/rewards numbers.
  - An office address at `742 Evergreen Terrace` (a well-known fictional address) for Vikram Desai.  
  This suggests the dataset is anonymized or semi-simulated.

- **Multiple overlapping contact details per member**  
  Many members provide several contact channels over time: new phone numbers, fax numbers, emergency contacts, and email addresses. This is realistic behavior, but it means a production system must:
  - Treat some fields as **“latest value wins”** (e.g., phone, email).
  - Track historical values carefully if they’re needed for audit or compliance.

- **Operational anomalies in billing and payments**  
  Several members report overcharges, duplicate charges, or unexplained transactions (e.g., $500, $950, $1,200 discrepancies). These are not schema errors, but examples of **business anomalies** in the underlying financial data that a real system might want to surface or route to support workflows.

- **Rich but sometimes indirect preference data**  
  Member preferences (seat type, room style, view, amenities, wellness, eco-friendly travel, etc.) are scattered across many free-text messages. They are generally consistent per member (e.g., Layla prefers aisle seats, Lily prefers window seats), but they are:
  - Stored redundantly in multiple messages.
  - Mixed with one-off requests.  
  A downstream profile-building or QA system needs to distinguish stable preferences from single events.

# Deployed Service

The Member QA Service is deployed on Render.
- **Base URL:** https://memeber-qa-service-2.onrender.com  
- **API Docs (Swagger):** https://memeber-qa-service-2.onrender.com/docs  
- **Health Check:** https://memeber-qa-service-2.onrender.com/health
  
# How It’s Deployed (Render)
Platform: Render Web Service (Python)

**Build command:**
pip install -r requirements.txt

**Start command:**
uvicorn app.main:app --host 0.0.0.0 --port 8000

**Environment variables:**
OPENAI_API_KEY – OpenAI API key used for LLM calls
MESSAGES_URL (optional; defaults to the provided public API) –
https://november7-730026606190.europe-west1.run.app/messages


# Example Query (POST /ask)

```bash
curl -X POST "https://memeber-qa-service-2.onrender.com/ask" \
     -H "Content-Type: application/json" \
     -d '{"question": "What seat does Layla Kawaguchi prefer?"}'
     -d '{ "answer": "Layla Kawaguchi prefers aisle seats during her flights." }'
