from __future__ import annotations

import re
from dataclasses import dataclass


UNSAFE = re.compile(
    r"\b(fuck|shit|bitch|cunt|сука|бля\w*|хуй\w*|наркот\w*|кокаин\w*|героин\w*|"
    r"meth|cocaine|heroin|drug\w*|alcohol|vodka|beer|пиво|водк\w*)\b",
    re.IGNORECASE,
)
WORD = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")


@dataclass(frozen=True)
class Check:
    accepted: bool
    reason: str = ""


def check_answer(text: str, age: int, bad_answer_count: int = 0) -> Check:
    clean = text.strip()
    if UNSAFE.search(clean):
        return Check(False, "unsafe")
    words = WORD.findall(clean)
    if not words:
        return Check(False, "nonsense")
    letters = re.sub(r"[^A-Za-z]", "", clean).lower()
    if len(letters) >= 5 and not re.search(r"[aeiouy]", letters):
        return Check(False, "nonsense")
    if re.search(r"(.)\1{4,}", letters):
        return Check(False, "nonsense")
    if age >= 10 and len(words) < 2:
        return Check(False, "short")
    return Check(True)


def retry_message(reason: str, question: str, age: int) -> str:
    if reason == "short":
        return (
            "Please answer with a full sentence. For example: “I like it because …”\n\n"
            f"Let’s try again: {question}"
        )
    if reason == "unsafe":
        return (
            "I didn’t understand that answer. Let’s keep our chat friendly and safe. "
            f"You can answer the question like this: “I think … because …”\n\n{question}"
        )
    return (
        "I couldn’t understand that. Please answer the same question using English words. "
        f"You can start with: “I think …”\n\n{question}"
    )

