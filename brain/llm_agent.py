"""
BOB Brain — LLM Agent
Wraps llama-server (already compiled in /home/arduino/bob/llama.cpp/build/bin/)
and provides a clean async chat interface.

llama-server exposes an OpenAI-compatible REST API:
  POST http://localhost:8080/v1/chat/completions

BOB's system prompt gives it a personality and robot-control awareness.
"""

import asyncio
import json
import logging
import subprocess
import time
from pathlib import Path
from typing import AsyncGenerator, Optional

import httpx

log = logging.getLogger("llm_agent")

# ── Paths ──────────────────────────────────────────────────────────────────
LLAMA_SERVER_BIN = Path("/home/arduino/bob/llama.cpp/build/bin/llama-server")
LLAMA_LIBS_DIR   = Path("/home/arduino/bob/llama.cpp/build/bin")

# ── Model selection — prefer 0.5B for speed, fall back to 1.5B if missing ──
_MODEL_05B = Path("/home/arduino/bob/models/Qwen2.5-0.5B-Instruct-Q4_K_M.gguf")
_MODEL_15B = Path("/home/arduino/bob/models/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf")
_MODEL_SYM = Path("/home/arduino/bob/models/bob_llm.gguf")
MODEL_PATH = _MODEL_05B if _MODEL_05B.exists() else (_MODEL_SYM if _MODEL_SYM.exists() else _MODEL_15B)

# ── Server config ───────────────────────────────────────────────────────────
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8080
SERVER_URL  = f"http://{SERVER_HOST}:{SERVER_PORT}"
CTX_SIZE    = 512    # Smaller context = faster inference
N_THREADS   = 4      # All 4 ARM cores

# ── BOB System Prompt ───────────────────────────────────────────────────────
BOB_SYSTEM_PROMPT = """You are BOB, a friendly robot assistant. Be warm, concise, and helpful.
Respond in 1-2 short sentences only. Never repeat yourself. Never say 'I am an AI'.
You have wheels, a camera, sensors, and a face screen. You run fully offline on-device."""


class LLMAgent:
    def __init__(self):
        self._proc: Optional[subprocess.Popen] = None
        # connect_timeout=5s, read_timeout=20s — fast fail if server hangs
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=20.0, write=5.0, pool=5.0)
        )
        self._history: list[dict] = []
        self._ready = False
        self._fail_count = 0   # Track consecutive failures

    # ──────────────────────────────────────────
    # Server lifecycle
    # ──────────────────────────────────────────

    async def start(self):
        """Launch llama-server as a subprocess."""
        if not MODEL_PATH.exists():
            log.error("Model not found at %s — run download_model.sh first!", MODEL_PATH)
            return False

        if not LLAMA_SERVER_BIN.exists():
            log.error("llama-server binary not found at %s", LLAMA_SERVER_BIN)
            return False

        log.info("Using model: %s", MODEL_PATH)
        cmd = [
            str(LLAMA_SERVER_BIN),
            "--model",   str(MODEL_PATH),
            "--host",    SERVER_HOST,
            "--port",    str(SERVER_PORT),
            "--ctx-size", str(CTX_SIZE),
            "--threads",  str(N_THREADS),
            "--no-mmap",               # Don't mmap on eMMC — use RAM
            "--flash-attn",            # Flash attention for speed
            "--log-disable",           # Silence verbose logs
            "-ngl", "0",               # Force CPU-only (no GPU layers)
            "--batch-size", "128",     # Smaller batch = lower latency
        ]

        env = {"LD_LIBRARY_PATH": str(LLAMA_LIBS_DIR)}
        log.info("Starting llama-server: %s", " ".join(cmd))

        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )

        # Wait for server to be ready (up to 60s — model load takes time)
        for _ in range(60):
            await asyncio.sleep(1.0)
            try:
                r = await self._client.get(f"{SERVER_URL}/health")
                if r.status_code == 200:
                    self._ready = True
                    log.info("llama-server ready!")
                    return True
            except httpx.ConnectError:
                pass

        log.error("llama-server failed to start within 60s")
        return False

    async def stop(self):
        self._ready = False
        await self._client.aclose()
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()

    # ──────────────────────────────────────────
    # Chat interface
    # ──────────────────────────────────────────

    def clear_history(self):
        """Reset conversation history."""
        self._history = []

    async def chat(
        self,
        user_message: str,
        context: Optional[dict] = None,
        stream: bool = False,
    ) -> str:
        """
        Send a message to BOB's LLM and return the response.

        Args:
            user_message: The user's text input.
            context: Optional dict with robot sensor data injected into system prompt.
            stream: If True, returns streamed response (for display).
        """
        if not self._ready:
            return "I'm still warming up — give me a moment!"

        # Build enriched system prompt with current sensor context
        system = BOB_SYSTEM_PROMPT
        if context:
            system += f"\n\nCurrent sensor data: {json.dumps(context)}"

        messages = [
            {"role": "system", "content": system},
            *self._history,
            {"role": "user",   "content": user_message},
        ]

        payload = {
            "model":       "bob",
            "messages":    messages,
            "max_tokens":  80,        # Short answers = fast responses
            "temperature": 0.6,       # Slightly less random = more coherent
            "top_p":       0.9,
            "stream":      stream,
        }

        try:
            if stream:
                return await self._stream_chat(payload)
            else:
                r = await self._client.post(
                    f"{SERVER_URL}/v1/chat/completions",
                    json=payload,
                )
                r.raise_for_status()
                data     = r.json()
                response = data["choices"][0]["message"]["content"].strip()

                # Update conversation history (keep last 4 exchanges = 8 msgs)
                self._history.append({"role": "user",      "content": user_message})
                self._history.append({"role": "assistant", "content": response})
                if len(self._history) > 8:
                    self._history = self._history[-8:]

                self._fail_count = 0  # Reset on success
                return response

        except httpx.TimeoutException:
            self._fail_count += 1
            log.error("LLM timeout (attempt %d)", self._fail_count)
            return "Give me a sec, I'm thinking."
        except httpx.HTTPError as e:
            self._fail_count += 1
            log.error("LLM request failed: %s", e)
            return "Hmm, I didn't catch that. Try again?"

    async def _stream_chat(self, payload: dict) -> AsyncGenerator[str, None]:
        """Streaming version — yields token chunks."""
        async with self._client.stream(
            "POST",
            f"{SERVER_URL}/v1/chat/completions",
            json=payload,
        ) as r:
            async for line in r.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        token = chunk["choices"][0]["delta"].get("content", "")
                        if token:
                            yield token
                    except (json.JSONDecodeError, KeyError):
                        pass

    @property
    def is_ready(self) -> bool:
        return self._ready
