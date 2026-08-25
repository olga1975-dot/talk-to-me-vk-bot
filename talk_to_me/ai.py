from __future__ import annotations

import asyncio
import json
import re
import subprocess
import time
from pathlib import Path

import imageio_ffmpeg
import edge_tts
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
        """Convert VK OGG/Opus to WAV, upload it to Kie, then transcribe it."""
        def _upload() -> str:
            wav_path = path.with_suffix(".wav")
            conversion = subprocess.run(
                [
                    imageio_ffmpeg.get_ffmpeg_exe(),
                    "-y",
                    "-i", str(path),
                    "-ac", "1",
                    "-ar", "16000",
                    "-c:a", "pcm_s16le",
                    str(wav_path),
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if conversion.returncode != 0 or not wav_path.exists():
                raise RuntimeError(f"Voice conversion failed: {conversion.stderr[-500:]}")

            headers = {"Authorization": self.headers["Authorization"]}
            with wav_path.open("rb") as audio:
                response = requests.post(
                    "https://kieai.redpandaai.co/api/file-stream-upload",
                    headers=headers,
                    files={"file": ("voice.wav", audio, "audio/wav")},
                    data={"uploadPath": "talk-to-me/voice", "fileName": f"voice-{time.time_ns()}.wav"},
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
        voice = "en-US-JennyNeural" if mode == "female" else "en-US-GuyNeural"
        communicator = edge_tts.Communicate(text=text, voice=voice, rate="-5%")
        await communicator.save(str(path))


def extract_question(text: str) -> str:
    matches = re.findall(r"[^.!?\n]*\?", text)
    return matches[-1].strip() if matches else text.strip()
