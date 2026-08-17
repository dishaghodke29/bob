"""
BOB Brain — LLM Agent
Wraps llama-server (already running on port 8080) and provides a clean async chat interface.

llama-server is started EXTERNALLY by start_bob.sh before this brain runs.
This module only connects to it — it does NOT launch it as a subprocess.

llama-server exposes an OpenAI-compatible REST API:
  POST http://localhost:8080/v1/chat/completions
"""

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import AsyncGenerator, Optional

import httpx

log = logging.getLogger("llm_agent")

# ── Server config ────────────────────────────────────────────────────────────
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8080
SERVER_URL  = f"http://{SERVER_HOST}:{SERVER_PORT}"

# ── BOB System Prompt — KEEP SHORT for fast inference ────────────────────────
BOB_SYSTEM_PROMPT = (
    "You are BOB, a friendly robot assistant. "
    "Respond in 1-2 short sentences only. "
    "Be warm, helpful, and direct. Never say 'I am an AI'. "
    "You have wheels, a camera, sensors, and a face screen. "
    "You run fully offline on-device."
)


class LLMAgent:
    def __init__(self):
        # connect=5s fast-fail, read=20s for generation, write/pool=5s
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=20.0, write=5.0, pool=5.0)
        )
        self._history: list[dict] = []
        self._ready    = False
        self._fail_cnt = 0

    # ──────────────────────────────────────────
    # Server lifecycle
    # ──────────────────────────────────────────

    async def start(self) -> bool:
        """
        Wait for the already-running llama-server to be healthy.
        Does NOT launch a new subprocess — start_bob.sh handles that.
        """
        log.info("Waiting for llama-server at %s …", SERVER_URL)
        for attempt in range(60):          # wait up to 60s
            try:
                r = await self._client.get(f"{SERVER_URL}/health")
                if r.status_code == 200:
                    data = r.json()
                    if data.get("status") in ("ok", "loading model"):
                        # Keep waiting if still loading
                        if data.get("status") == "loading model":
                            if attempt % 5 == 0:
                                log.info("LLM still loading model… (%ds)", attempt)
                            await asyncio.sleep(1.0)
                            continue
                        self._ready = True
                        log.info("llama-server is ready! ✓")
                        await self._prewarm()
                        return True
            except httpx.ConnectError:
                if attempt % 10 == 0:
                    log.warning("llama-server not up yet (attempt %d/60)…", attempt)
            await asyncio.sleep(1.0)

        log.error("llama-server did not become ready within 60s")
        return False

    async def _prewarm(self):
        """Send a tiny warm-up request so first real chat is instant."""
        try:
            await self._client.post(
                f"{SERVER_URL}/v1/chat/completions",
                json={
                    "model": "bob",
                    "messages": [
                        {"role": "system", "content": "hi"},
                        {"role": "user",   "content": "hi"},
                    ],
                    "max_tokens": 1,
                    "temperature": 0.1,
                },
            )
            log.info("LLM pre-warmed ✓")
        except Exception:
            pass  # prewarm failure is non-fatal

    async def stop(self):
        self._ready = False
        await self._client.aclose()
        # Note: we do NOT kill llama-server here — stop_bob.sh handles that

    # ──────────────────────────────────────────
    # Chat interface
    # ──────────────────────────────────────────

    def clear_history(self):
        self._history = []

    async def chat(
        self,
        user_message: str,
        context: Optional[dict] = None,
    ) -> str:
        """
        Send a message and return BOB's response as a string.
        Keeps last 4 conversation turns (8 messages) for context.
        """
        if not self._ready:
            return "I'm still warming up, give me a moment!"

        # Build system prompt (append sensor context only if meaningful)
        system = BOB_SYSTEM_PROMPT
        if context:
            obs = context.get("obstacle_cm", 999)
            if obs < 100:
                system += f" There is an obstacle {obs}cm away."

        messages = [
            {"role": "system", "content": system},
            *self._history[-8:],  # last 4 exchanges
            {"role": "user",   "content": user_message},
        ]

        payload = {
            "model":       "bob",
            "messages":    messages,
            "max_tokens":  80,        # short = fast
            "temperature": 0.6,
            "top_p":       0.9,
            "stream":      False,
        }

        try:
            r = await self._client.post(
                f"{SERVER_URL}/v1/chat/completions",
                json=payload,
            )
            r.raise_for_status()
            data     = r.json()
            response = data["choices"][0]["message"]["content"].strip()

            # Update conversation history
            self._history.append({"role": "user",      "content": user_message})
            self._history.append({"role": "assistant", "content": response})
            if len(self._history) > 8:
                self._history = self._history[-8:]

            self._fail_cnt = 0
            log.info("LLM ← %r", response[:80])
            return response

        except httpx.TimeoutException:
            self._fail_cnt += 1
            log.error("LLM timeout #%d", self._fail_cnt)
            if self._fail_cnt >= 3:
                # Server may be overloaded — mark not ready and re-check
                self._ready = False
                asyncio.create_task(self._recheck_health())
            return "Give me a second, I'm thinking."

        except httpx.HTTPStatusError as e:
            log.error("LLM HTTP error %s: %s", e.response.status_code, e)
            return "Hmm, something went wrong on my end."

        except httpx.HTTPError as e:
            log.error("LLM request failed: %s", e)
            return "I didn't catch that. Try again?"

        except (KeyError, IndexError, json.JSONDecodeError) as e:
            log.error("LLM bad response format: %s", e)
            return "Got a garbled reply. Try again?"

    async def _recheck_health(self):
        """Re-check server health after repeated failures, re-mark ready if OK."""
        await asyncio.sleep(2)
        try:
            r = await self._client.get(f"{SERVER_URL}/health", timeout=5.0)
            if r.status_code == 200:
                self._ready   = True
                self._fail_cnt = 0
                log.info("llama-server recovered ✓")
        except Exception:
            log.warning("llama-server still down after recheck")

    @property
    def is_ready(self) -> bool:
        return self._ready
