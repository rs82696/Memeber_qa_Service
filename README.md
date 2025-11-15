# Memeber_qa_Service
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
