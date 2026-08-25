from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path

import requests

from .config import Settings
from .db import Profile
from .prompts import help_prompt, system_prompt


class TalkToMeAI:
    """Kie.ai-backed dialogue and speech client."""

    def __init__(self, settings: Settings):
        self.chat_url = settings.kie_chat_url
        self.chat_model = settings.kie_chat_model
        self.base_url = "https://api.kie.ai"
        self.headers = {
            "Authorization": f"Bearer {settings.kie_api_key}",
            "Content-Type": "application/json",
        }

    def _chat_sync(self, messages: list[dict]) -> str:
        response = requests.post(
            self.chat_url,
            headers=self.headers,
            json={"model": self.chat_model, "messages": messages, "stream": False},
            timeout=90,
        )
        response.raise_for_status()
        data = response.json()
        choices = data.get("choices") or []
        if choices:
            content = choices[0].get("message", {}).get("content", "")
            if isinstance(content, str) and content.strip():
                return content.strip()
        candidates = data.get("candidates") or []
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            result = "".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
            if result:
                return result
        raise RuntimeError(f"Kie.ai returned no text: {str(data)[:300]}")

    async def reply(self, profile: Profile, history: list[dict[str, str]], text: str) -> str:
        messages = [{"role": "system", "content": system_prompt(profile)}]
        messages.extend({"role": m["role"], "content": m["content"]} for m in history)
        messages.append({"role": "user", "content": text})
        return await asyncio.to_thread(self._chat_sync, messages)

    async def first_question(self, profile: Profile) -> str:
        return await self.reply(
            profile, [], "Start this topic now. Greet me by name briefly and ask one engaging question."
        )

    async def help(self, profile: Profile) -> str:
        return await asyncio.to_thread(
            self._chat_sync,
            [
                {"role": "system", "content": system_prompt(profile)},
                {"role": "user", "content": help_prompt(profile)},
            ],
        )

    async def transcribe_url(self, url: str) -> str:
        return await asyncio.to_thread(
            self._chat_sync,
            [{
                "role": "user",
                "content": [
                    {"type": "text", "text": "Transcribe this child's English speech. Return only the transcript."},
                    {"type": "image_url", "image_url": {"url": url}},
                ],
            }],
        )

    async def transcribe_file(self, path: Path) -> str:
        """Upload a private VK voice file to Kie, then transcribe its public temporary URL."""
        def _upload() -> str:
            headers = {"Authorization": self.headers["Authorization"]}
            with path.open("rb") as audio:
                response = requests.post(
                    "https://kieai.redpandaai.co/api/file-stream-upload",
                    headers=headers,
                    files={"file": ("voice.ogg", audio, "audio/ogg")},
                    data={"uploadPath": "talk-to-me/voice", "fileName": f"voice-{time.time_ns()}.ogg"},
                    timeout=60,
                )
            response.raise_for_status()
            url = response.json().get("data", {}).get("downloadUrl")
            if not url:
                raise RuntimeError(f"Kie file upload returned no URL: {response.text[:300]}")
            return url

        uploaded_url = await asyncio.to_thread(_upload)
        return await self.transcribe_url(uploaded_url)

    async def synthesize(self, text: str, path: Path, mode: str) -> None:
        voice = "Rachel" if mode == "female" else "Adam"

        def _call() -> None:
            created = requests.post(
                f"{self.base_url}/api/v1/jobs/createTask",
                headers=self.headers,
                json={
                    "model": "elevenlabs/text-to-speech-multilingual-v2",
                    "input": {
                        "text": text,
                        "voice": voice,
                        "stability": 0.5,
                        "similarity_boost": 0.75,
                        "style": 0,
                        "speed": 0.95,
                        "timestamps": False,
                    },
                },
                timeout=30,
            )
            created.raise_for_status()
            task_id = created.json().get("data", {}).get("taskId")
            if not task_id:
                raise RuntimeError(f"Kie TTS task was not created: {created.text[:300]}")
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                status = requests.get(
                    f"{self.base_url}/api/v1/jobs/recordInfo",
                    headers=self.headers,
                    params={"taskId": task_id},
                    timeout=30,
                )
                status.raise_for_status()
                data = status.json().get("data") or {}
                if data.get("state") == "success":
                    result = data.get("resultJson") or "{}"
                    result = json.loads(result) if isinstance(result, str) else result
                    urls = result.get("resultUrls") or result.get("result_urls") or []
                    if not urls:
                        raise RuntimeError("Kie TTS completed without an audio URL")
                    audio = requests.get(urls[0], timeout=30)
                    audio.raise_for_status()
                    path.write_bytes(audio.content)
                    return
                if data.get("state") == "fail":
                    raise RuntimeError(f"Kie TTS failed: {data}")
                time.sleep(2)
            raise TimeoutError("Kie TTS timed out")

        await asyncio.to_thread(_call)


def extract_question(text: str) -> str:
    matches = re.findall(r"[^.!?\n]*\?", text)
    return matches[-1].strip() if matches else text.strip()
