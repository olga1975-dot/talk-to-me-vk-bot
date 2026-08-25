from __future__ import annotations

import asyncio
import json
import logging
import random
import tempfile
from pathlib import Path

import requests
import vk_api
from vk_api.bot_longpoll import VkBotEventType, VkBotLongPoll
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
from vk_api.upload import VkUpload

from talk_to_me.ai import TalkToMeAI, extract_question
from talk_to_me.config import load_settings
from talk_to_me.db import Database, Profile
from talk_to_me.guardrails import check_answer, retry_message

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
LOG = logging.getLogger(__name__)

LEVELS = ["Beginner (A0–A1)", "Elementary (A1–A2)", "Intermediate (A2–B1)"]
TOPICS = ["Animals", "Games", "Sports", "Music", "Films", "Everyday life", "Surprise me"]
LEVEL_BUTTONS = ["🌱 Beginner", "🌿 Elementary", "🌳 Intermediate"]
TOPIC_BUTTONS = ["🐾 Animals", "🎮 Games", "⚽ Sports", "🎵 Music", "🎬 Films", "🏠 Everyday life", "🎲 Surprise me"]
MODE_BUTTONS = ["💬 Text", "👩 Female voice", "👨 Male voice"]
HELP = "💡 Help"

settings = load_settings()
db = Database(settings.database_path)
ai = TalkToMeAI(settings)
session = vk_api.VkApi(token=settings.vk_group_token)
vk = session.get_api()
upload = VkUpload(session)


def keyboard(rows: list[list[str]], one_time: bool = False) -> str:
    kb = VkKeyboard(one_time=one_time, inline=False)
    for row_i, row in enumerate(rows):
        if row_i:
            kb.add_line()
        for col_i, label in enumerate(row):
            if col_i:
                kb.add_button(label, color=VkKeyboardColor.SECONDARY)
            else:
                kb.add_button(label, color=VkKeyboardColor.PRIMARY)
    return kb.get_keyboard()


MAIN_KEYBOARD = keyboard([[HELP, "📚 Topics"], ["🎙 Mode", "🔄 Start again"]])
LEVEL_KEYBOARD = keyboard([[LEVEL_BUTTONS[0]], [LEVEL_BUTTONS[1]], [LEVEL_BUTTONS[2]]], one_time=True)
TOPIC_KEYBOARD = keyboard([[x] for x in TOPIC_BUTTONS], one_time=True)
MODE_KEYBOARD = keyboard([[x] for x in MODE_BUTTONS], one_time=True)


def send(peer_id: int, text: str, kb: str | None = None, attachment: str | None = None) -> None:
    params = {"peer_id": peer_id, "message": text, "random_id": random.randint(1, 2_147_483_647)}
    if kb:
        params["keyboard"] = kb
    if attachment:
        params["attachment"] = attachment
    vk.messages.send(**params)


def stage(p: Profile) -> str:
    if not p.name:
        return "name"
    if p.age is None:
        return "age"
    if not p.level:
        return "level"
    if not p.interests:
        return "interests"
    if not p.topic:
        return "topic"
    return "chat"


async def begin(peer_id: int, user_id: int) -> None:
    db.reset(user_id)
    send(peer_id, "Hi! I’m Talk to me 🦢 Я — ИИ-собеседник для практики английского.\n\nWhat is your first name?", MAIN_KEYBOARD)


async def choose_topic(peer_id: int, p: Profile, index: int) -> None:
    p.topic = TOPICS[index]
    p.current_question = ""
    p.bad_answer_count = 0
    db.clear_history(p.user_id)
    db.save_profile(p)
    send(peer_id, f"Topic: {p.topic}")
    if p.user_id != settings.authorized_vk_id:
        answer = f"Great choice! Let’s talk about {p.topic}. What do you like most about it?"
        p.current_question = extract_question(answer)
        db.save_profile(p)
        db.add_message(p.user_id, "assistant", answer)
        send(peer_id, answer + "\n\n🧪 Demo mode: AI is enabled only for the project owner.", MAIN_KEYBOARD)
        return
    try:
        answer = await ai.first_question(p)
        p.current_question = extract_question(answer)
        db.save_profile(p)
        db.add_message(p.user_id, "assistant", answer)
        await deliver(peer_id, p, answer)
    except Exception:
        LOG.exception("First AI question failed")
        send(peer_id, "Не получается связаться с ИИ. Попробуйте ещё раз через минуту.", MAIN_KEYBOARD)


async def help_user(peer_id: int, p: Profile) -> None:
    if not p.complete or not p.current_question:
        send(peer_id, "Сначала завершите регистрацию и выберите тему. Напишите «Начать».", MAIN_KEYBOARD)
        return
    if p.user_id != settings.authorized_vk_id:
        send(peer_id, "💡 1. I like it because it is fun.\n2. My favorite thing is …\n3. I think it is interesting.", MAIN_KEYBOARD)
        return
    try:
        examples = await ai.help(p)
        send(peer_id, "💡 Примеры-подсказки. Напишите свой ответ или измените один из примеров:\n\n" + examples, MAIN_KEYBOARD)
    except Exception:
        LOG.exception("AI help failed")
        send(peer_id, "Начните ответ так: “I think … because …”", MAIN_KEYBOARD)


async def process_answer(peer_id: int, p: Profile, text: str) -> None:
    check = check_answer(text, p.age or 5, p.bad_answer_count)
    if not check.accepted:
        p.bad_answer_count += 1
        db.save_profile(p)
        send(peer_id, retry_message(check.reason, p.current_question, p.age or 5), MAIN_KEYBOARD)
        return
    if p.user_id != settings.authorized_vk_id:
        send(peer_id, "✅ Ответ принят.\n\n🧪 Демо-режим: продолжение через Kie.ai доступно владельцу проекта.", MAIN_KEYBOARD)
        return
    try:
        history = db.history(p.user_id, settings.history_limit)
        answer = await ai.reply(p, history, text)
        db.add_message(p.user_id, "user", text)
        db.add_message(p.user_id, "assistant", answer)
        p.current_question = extract_question(answer)
        p.bad_answer_count = 0
        db.save_profile(p)
        await deliver(peer_id, p, answer)
    except Exception:
        LOG.exception("AI reply failed")
        send(peer_id, "Связь с ИИ временно недоступна. Отправьте ответ ещё раз через минуту.", MAIN_KEYBOARD)


def attachment_id(doc: dict) -> str:
    access = f"_{doc['access_key']}" if doc.get("access_key") else ""
    return f"doc{doc['owner_id']}_{doc['id']}{access}"


async def deliver(peer_id: int, p: Profile, text: str) -> None:
    send(peer_id, text, MAIN_KEYBOARD)
    if p.mode == "text":
        return
    try:
        with tempfile.TemporaryDirectory(prefix="talk_to_me_tts_") as folder:
            path = Path(folder) / "reply.mp3"
            await ai.synthesize(text, path, p.mode)
            result = await asyncio.to_thread(upload.audio_message, str(path), peer_id=peer_id)
            doc = result[0] if isinstance(result, list) else result
            send(peer_id, "🔊 Голос сгенерирован ИИ", MAIN_KEYBOARD, attachment_id(doc))
    except Exception:
        LOG.exception("VK voice upload failed")
        send(peer_id, "Не удалось создать голос — текстовый ответ уже отправлен.", MAIN_KEYBOARD)


def voice_url(attachments: list[dict]) -> str | None:
    for item in attachments:
        kind = item.get("type")
        obj = item.get(kind, {}) if kind else {}
        if kind == "audio_message":
            return obj.get("link_ogg") or obj.get("link_mp3")
        if kind == "doc":
            preview = obj.get("preview", {}).get("audio_msg", {})
            url = preview.get("link_ogg") or preview.get("link_mp3")
            if url:
                return url
    return None


async def handle(message: dict) -> None:
    peer_id = int(message["peer_id"])
    user_id = int(message["from_id"])
    text = (message.get("text") or "").strip()
    p = db.get_profile(user_id)
    lower = text.lower()

    if lower in {"начать", "/start", "start", "🔄 start again"}:
        await begin(peer_id, user_id)
        return
    if lower in {"/topics", "📚 topics", "темы"}:
        if not p.complete:
            send(peer_id, "Сначала завершите регистрацию. Напишите «Начать».", MAIN_KEYBOARD)
            return
        send(peer_id, "Выберите тему:", TOPIC_KEYBOARD)
        return
    if lower in {"/mode", "🎙 mode", "режим"}:
        if not p.complete:
            send(peer_id, "Сначала завершите регистрацию. Напишите «Начать».", MAIN_KEYBOARD)
            return
        send(peer_id, "Выберите режим ответа:", MODE_KEYBOARD)
        return
    if text == HELP:
        await help_user(peer_id, p)
        return

    current = stage(p)
    if current == "name":
        if not text or len(text) > 30 or any(ch.isdigit() for ch in text):
            send(peer_id, "Напишите только имя — до 30 букв.", MAIN_KEYBOARD)
            return
        p.name = text
        db.save_profile(p)
        send(peer_id, f"Nice to meet you, {text}! How old are you? Напишите число от 5 до 15.", MAIN_KEYBOARD)
        return
    if current == "age":
        try:
            age = int(text)
        except ValueError:
            age = 0
        if not 5 <= age <= 15:
            send(peer_id, "Talk to me рассчитан на возраст 5–15 лет. Напишите число от 5 до 15.", MAIN_KEYBOARD)
            return
        p.age = age
        db.save_profile(p)
        send(peer_id, "Выберите примерный уровень английского:", LEVEL_KEYBOARD)
        return
    if current == "level":
        if text not in LEVEL_BUTTONS:
            send(peer_id, "Выберите уровень кнопкой:", LEVEL_KEYBOARD)
            return
        p.level = LEVELS[LEVEL_BUTTONS.index(text)]
        db.save_profile(p)
        send(peer_id, "Что вам нравится? Например: кошки, Minecraft, футбол, рисование, музыка.", MAIN_KEYBOARD)
        return
    if current == "interests":
        if len(text) < 2:
            send(peer_id, "Напишите хотя бы одно увлечение.", MAIN_KEYBOARD)
            return
        p.interests = text[:300]
        db.save_profile(p)
        send(peer_id, "Отлично! Выберите первую тему:", TOPIC_KEYBOARD)
        return
    if text in TOPIC_BUTTONS:
        await choose_topic(peer_id, p, TOPIC_BUTTONS.index(text))
        return
    if text in MODE_BUTTONS:
        p.mode = ["text", "female", "male"][MODE_BUTTONS.index(text)]
        db.save_profile(p)
        note = "" if p.mode == "text" else " Голос синтезируется ИИ."
        send(peer_id, f"Режим изменён: {text}.{note}", MAIN_KEYBOARD)
        return
    if current == "topic":
        send(peer_id, "Выберите тему кнопкой:", TOPIC_KEYBOARD)
        return

    url = voice_url(message.get("attachments", []))
    if url:
        if user_id != settings.authorized_vk_id:
            send(peer_id, "🧪 Распознавание голоса через ИИ доступно только владельцу проекта.", MAIN_KEYBOARD)
            return
        try:
            with tempfile.TemporaryDirectory(prefix="talk_to_me_voice_") as folder:
                path = Path(folder) / "answer.ogg"
                response = await asyncio.to_thread(requests.get, url, timeout=30)
                response.raise_for_status()
                path.write_bytes(response.content)
                text = await ai.transcribe_file(path)
            send(peer_id, f"🎙 Я услышал: {text}", MAIN_KEYBOARD)
        except Exception:
            LOG.exception("VK voice transcription failed")
            send(peer_id, "Не удалось распознать голосовое сообщение. Попробуйте ещё раз или напишите текстом.", MAIN_KEYBOARD)
            return
    if not text:
        send(peer_id, "Отправьте текст или голосовое сообщение.", MAIN_KEYBOARD)
        return
    await process_answer(peer_id, p, text)


def main() -> None:
    longpoll = VkBotLongPoll(session, settings.vk_group_id)
    LOG.info("Talk to me VK bot started")
    for event in longpoll.listen():
        if event.type == VkBotEventType.MESSAGE_NEW and event.from_user:
            try:
                asyncio.run(handle(dict(event.message)))
            except Exception:
                LOG.exception("Unhandled VK event")


if __name__ == "__main__":
    main()
