from __future__ import annotations

import os
import re
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

import requests
from rapidfuzz import fuzz
from openai import OpenAI
import dateparser

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Default OpenAI model (can be overridden with env var)
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Basic English stopwords for simple bag-of-words scoring
STOPWORDS = {
    "the", "a", "an", "to", "for", "on", "in", "and", "of",
    "my", "is", "are", "was", "were", "be", "have", "has",
    "this", "that", "next", "last", "with", "at", "please",
    "can", "you", "me", "it", "i", "we", "our", "from",
}


@dataclass
class Message:
    id: str
    user_id: str
    user_name: str
    timestamp: datetime
    text: str


class QAEngine:
    """
    Loads messages from the public API and answers natural-language questions
    based on those messages using a simple retrieval + LLM generation pipeline.
    """

    def __init__(self, messages_url: str):
        self.messages_url = messages_url
        self.messages: List[Message] = []
        self.user_names: List[str] = []

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            logger.warning("OPENAI_API_KEY is not set. LLM calls will fail.")
        self.client = OpenAI(api_key=api_key) if api_key else None

        self._load_messages()

    # ------------------- Data loading -------------------

    def _load_messages(self):
        logger.info(f"Fetching messages from {self.messages_url}")
        resp = requests.get(self.messages_url, timeout=20)
        resp.raise_for_status()

        data = resp.json()
        # API appears to return { "total": ..., "items": [...] }
        items = data.get("items", data)

        parsed: List[Message] = []
        for item in items:
            raw_ts = item.get("timestamp")
            ts: datetime
            try:
                ts = datetime.fromisoformat(raw_ts)
            except Exception:
                # Fallback parsing for non-standard or synthetic timestamps
                parsed_ts = dateparser.parse(raw_ts)
                if not parsed_ts:
                    logger.warning("Failed to parse timestamp: %s", raw_ts)
                    parsed_ts = datetime.utcnow()
                ts = parsed_ts

            parsed.append(
                Message(
                    id=item["id"],
                    user_id=item["user_id"],
                    user_name=item["user_name"],
                    timestamp=ts,
                    text=item["message"],
                )
            )

        self.messages = parsed
        self.user_names = sorted({m.user_name for m in parsed})

        logger.info(
            "Loaded %d messages for %d members",
            len(self.messages),
            len(self.user_names),
        )

    # ------------------- Public API -------------------

    def answer(self, question: str) -> str:
        question = (question or "").strip()
        if not question:
            return "Please provide a non-empty question."

        if not self.messages:
            return "I don't have any messages loaded, so I can't answer yet."

        # 1. Guess which member the question is about (if any)
        member = self._guess_member(question)

        # 2. Retrieve candidate messages
        candidates = (
            [m for m in self.messages if m.user_name == member]
            if member
            else self.messages
        )

        # 3. Rank messages lexically by overlap with question
        q_tokens = self._tokenize(question)
        scored = []
        for m in candidates:
            score = self._score_message(q_tokens, m, member)
            if score > 0:
                scored.append((score, m))

        # Fallback: if nothing matched, consider all messages
        if not scored:
            for m in self.messages:
                score = self._score_message(q_tokens, m, None)
                if score > 0:
                    scored.append((score, m))

        if not scored:
            return "I couldn't find any messages related to that question."

        scored.sort(key=lambda x: x[0], reverse=True)
        top_messages = [m for _, m in scored[:10]]

        # 4. Use LLM to synthesize an answer from the top messages
        return self._llm_answer(question, top_messages, member)

    # ------------------- Member & retrieval helpers -------------------

    def _guess_member(self, question: str) -> Optional[str]:
        """
        Fuzzy-match the question text against known member names.
        Supports both full name and first name.
        """
        q = question.lower()
        best_name = None
        best_score = 0.0

        for name in self.user_names:
            full_score = fuzz.partial_ratio(name.lower(), q)
            first = name.split()[0]
            first_score = fuzz.partial_ratio(first.lower(), q)
            score = max(full_score, first_score)
            if score > best_score:
                best_score = score
                best_name = name

        # Threshold keeps us from making wild guesses on generic questions
        if best_score >= 70:
            logger.debug("Detected member '%s' with score %.1f", best_name, best_score)
            return best_name
        return None

    def _tokenize(self, text: str) -> List[str]:
        return [
            tok
            for tok in re.findall(r"\w+", text.lower())
            if tok not in STOPWORDS
        ]

    def _score_message(
        self, q_tokens: List[str], message: Message, member: Optional[str]
    ) -> float:
        """
        Very simple lexical scoring:
        - overlap of question tokens with message tokens
        - small bonus if member is explicitly named in the message sender
        """
        m_tokens = self._tokenize(message.text)
        overlap = len(set(q_tokens) & set(m_tokens))

        bonus = 0.0
        if member and member.lower() in message.user_name.lower():
            bonus += 0.5

        return overlap + bonus

    # ------------------- LLM answer generation -------------------

    def _llm_answer(
        self,
        question: str,
        messages: List[Message],
        member: Optional[str],
    ) -> str:
        if self.client is None:
            # Graceful failure if no API key
            return (
                "The QA service is not fully configured (missing LLM API key), "
                "so I can't answer this question."
            )

        # Format context
        # We include timestamps so the model can resolve things like "this Friday"
        context_chunks = []
        for i, m in enumerate(messages, start=1):
            context_chunks.append(
                f"[{i}] user={m.user_name} "
                f"timestamp={m.timestamp.isoformat()} "
                f"text={m.text}"
            )
        context = "\n".join(context_chunks)

        system = (
            "You are a precise assistant that answers questions about member messages.\n"
            "You are given a list of messages with timestamps.\n"
            "- Only use the information in those messages.\n"
            "- If the answer is not clearly stated, respond with:\n"
            '  "I can\'t tell from the available messages."\n'
            "- If a message uses relative dates like \"this Friday\" or "
            "\"next month\", interpret them relative to the message timestamp.\n"
            "- Answer in one or two short sentences."
        )

        user_prompt = (
            f"Question: {question}\n\n"
            f"Messages:\n{context}\n\n"
            "Answer the question using only the messages above."
        )

        try:
            completion = self.client.chat.completions.create(
                model=DEFAULT_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0,
            )
        except Exception as e:
            logger.exception("LLM call failed")
            return f"I ran into an error while generating the answer: {e}"

        answer = completion.choices[0].message.content.strip()
        return answer or "I can't tell from the available messages."
