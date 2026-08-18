"""
voice.py — BOB Robot Voice Pipeline
=====================================
Speech-to-Text : faster-whisper  (tiny model, CPU, int8)
Text-to-Speech : piper-tts → ffmpeg T3 filter → aplay (hw:0,0)
Wake Word      : "hey bob" or "bob" — responds only when called
Microphone     : EMEET C960 USB mic, auto-detected
Platform       : Debian Linux arm64 (Arduino UNO Q)
"""

from __future__ import annotations

import asyncio
import logging
import re
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Awaitable, Callable, Optional

import numpy as np

logger = logging.getLogger(__name__)

# ──────────────────────────── Constants ──────────────────────────────────────
SAMPLE_RATE      = 16_000
CHUNK_SECONDS    = 3
CHUNK_FRAMES     = SAMPLE_RATE * CHUNK_SECONDS
NO_SPEECH_THRESH = 0.55

# Piper TTS settings
PIPER_BIN    = "/home/arduino/bob/venv/bin/piper"
PIPER_MODEL  = "/home/arduino/bob/models/en_US-amy-medium.onnx"

# Audio output: use PipeWire (same as YouTube/system audio → routes to BT or 3.5mm)
# PipeWire is confirmed running on this board
USE_PIPEWIRE = True   # set False to fall back to aplay

# T3 Throat-Resonant voice filter — deep, warm, grounded
T3_FILTER = (
    "volume=0.85,"
    "asetrate=22050*0.88,"       # slightly deeper pitch
    "aresample=22050,"
    "equalizer=f=180:width_type=h:w=120:g=6,"   # sub-bass warmth
    "equalizer=f=520:width_type=h:w=200:g=8,"   # chest resonance
    "equalizer=f=1200:width_type=h:w=350:g=4,"  # throat presence
    "equalizer=f=3500:width_type=h:w=600:g=-3," # de-harsh highs
    "atempo=0.96"                # slightly slower = more authoritative
)

# Wake word — BOB responds only when one of these is detected
WAKE_WORDS = ["hey bob", "hey, bob", "ok bob", "okay bob", "bob"]

# ──────────────────────────── Optional imports ────────────────────────────────
try:
    import sounddevice as sd
    _HAS_SD = True
except ImportError:
    sd = None  # type: ignore
    _HAS_SD = False
    logger.warning("sounddevice not installed — listen_loop disabled")

try:
    from faster_whisper import WhisperModel
    _HAS_WHISPER = True
except ImportError:
    WhisperModel = None  # type: ignore
    _HAS_WHISPER = False
    logger.warning("faster-whisper not installed — STT unavailable")


# ═════════════════════════════════════════════════════════════════════════════
class VoicePipeline:
    """Async voice pipeline: mic → Whisper STT → wake-word → callback → Piper TTS."""

    def __init__(self) -> None:
        self._whisper: Optional[WhisperModel] = None
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="voice")
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._running  = False
        self._speaking = False
        self._mic_index: Optional[int] = None
        self._wake_active = False  # True after wake word detected (stays active 30s)
        self._wake_timer: Optional[asyncio.TimerHandle] = None

    # ──────────────────────── Lifecycle ──────────────────────────────────────

    async def start(self) -> None:
        self._loop    = asyncio.get_running_loop()
        self._running = True

        self._mic_index = self._find_emeet_mic()
        if self._mic_index is not None:
            logger.info("EMEET C960 mic at device index %d", self._mic_index)
        else:
            logger.warning("EMEET C960 not found — using default mic")

        if not Path(PIPER_BIN).exists():
            logger.warning("piper not found at %s", PIPER_BIN)
        elif not Path(PIPER_MODEL).exists():
            logger.warning("Piper model not found at %s", PIPER_MODEL)
        else:
            logger.info("Piper TTS ready")

        if _HAS_WHISPER:
            logger.info("Loading Whisper tiny model (CPU/int8)…")
            try:
                self._whisper = await self._loop.run_in_executor(
                    self._executor,
                    lambda: WhisperModel("tiny", device="cpu", compute_type="int8"),
                )
                logger.info("Whisper loaded ✓")
            except Exception as exc:
                logger.error("Whisper load failed: %s", exc)

        # Warm up piper after 4s delay
        asyncio.create_task(self._warmup_tts())

    async def _warmup_tts(self) -> None:
        await asyncio.sleep(4)
        loop = self._loop or asyncio.get_running_loop()
        await loop.run_in_executor(
            self._executor,
            lambda: self._blocking_speak(".", silent=True),
        )
        logger.info("TTS warmed up ✓")

    async def stop(self) -> None:
        self._running = False
        self._executor.shutdown(wait=False)

    # ──────────────────────── Wake Word ──────────────────────────────────────

    def _check_wake_word(self, text: str) -> tuple[bool, str]:
        """
        Check if text contains a wake word.
        Returns (wake_detected, text_after_wake_word).
        """
        lower = text.lower().strip()
        for word in WAKE_WORDS:
            if lower.startswith(word):
                remainder = text[len(word):].strip(" ,!?.")
                return True, remainder
            if word in lower:
                # Wake word anywhere in utterance
                idx = lower.find(word)
                remainder = text[idx + len(word):].strip(" ,!?.")
                return True, remainder
        return False, text

    def _activate_wake(self) -> None:
        """Activate wake mode for 30 seconds."""
        if self._wake_timer:
            self._wake_timer.cancel()
        self._wake_active = True
        loop = self._loop
        if loop:
            self._wake_timer = loop.call_later(30, self._deactivate_wake)
        logger.info("Wake mode ON (30s window)")

    def _deactivate_wake(self) -> None:
        self._wake_active = False
        logger.info("Wake mode OFF — say 'Hey BOB' to activate")

    # ──────────────────────── TTS ─────────────────────────────────────────────

    async def speak(self, text: str) -> None:
        if not text or not text.strip():
            return
        clean = re.sub(r"[*_`#\[\]{}|<>]", "", text).strip()
        if not clean:
            return
        logger.info("TTS ▶ %r", clean[:60])
        self._speaking = True
        # Extend wake window while BOB is speaking
        self._activate_wake()
        try:
            loop = self._loop or asyncio.get_running_loop()
            await loop.run_in_executor(
                self._executor,
                lambda: self._blocking_speak(clean),
            )
        finally:
            self._speaking = False

    def _blocking_speak(self, text: str, silent: bool = False) -> None:
        """Piper → ffmpeg T3 filter → aplay (hw:0,0)  fully streamed."""
        piper_proc = ffmpeg_proc = aplay_proc = None
        try:
            if not Path(PIPER_BIN).exists() or not Path(PIPER_MODEL).exists():
                logger.error("Piper binary or model not found")
                return

            piper_proc = subprocess.Popen(
                [PIPER_BIN, "--model", PIPER_MODEL, "--output-raw"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )

            if silent:
                piper_proc.communicate(input=text.encode("utf-8"), timeout=60)
                return

            ffmpeg_proc = subprocess.Popen(
                [
                    "ffmpeg", "-y",
                    "-f", "s16le", "-ar", "22050", "-ac", "1",
                    "-i", "pipe:0",
                    "-af", T3_FILTER,
                    "-f", "wav", "pipe:1",
                ],
                stdin=piper_proc.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )

            aplay_proc = subprocess.Popen(
                ["aplay", "-q", "-D", APLAY_DEVICE],
                stdin=ffmpeg_proc.stdout,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            piper_proc.stdin.write(text.encode("utf-8"))
            piper_proc.stdin.close()
            piper_proc.stdout.close()
            ffmpeg_proc.stdout.close()

            aplay_proc.wait(timeout=60)
            ffmpeg_proc.wait(timeout=5)
            piper_proc.wait(timeout=5)

        except subprocess.TimeoutExpired:
            logger.error("TTS timeout — killing pipeline")
            for p in [aplay_proc, ffmpeg_proc, piper_proc]:
                if p:
                    try: p.kill()
                    except Exception: pass
        except Exception as exc:
            logger.error("TTS error: %s", exc, exc_info=True)

    # ──────────────────────── STT / Listen loop ───────────────────────────────

    async def listen_loop(
        self,
        callback: Callable[[str], Awaitable[None]],
    ) -> None:
        """
        Record 3s audio chunks → Whisper STT → wake-word check → callback.
        Only calls callback if 'hey bob' (or similar) is detected OR
        if already in an active wake window (30s after last activation).
        """
        if not _HAS_SD or self._whisper is None:
            logger.error("STT not available — listen_loop disabled")
            return

        logger.info("Listening for wake word ('Hey BOB') — mic_index=%s", self._mic_index)
        loop = self._loop or asyncio.get_running_loop()

        while self._running:
            try:
                if self._speaking:
                    await asyncio.sleep(0.1)
                    continue

                audio_np = await loop.run_in_executor(
                    self._executor, self._record_chunk
                )
                if audio_np is None:
                    await asyncio.sleep(0.5)
                    continue

                if self._speaking:
                    continue

                text = await loop.run_in_executor(
                    self._executor,
                    lambda a=audio_np: self._transcribe(a),
                )

                if not text:
                    continue

                # Check for wake word
                has_wake, query = self._check_wake_word(text)

                if has_wake:
                    self._activate_wake()
                    if query:
                        # Wake word + question in same utterance → answer directly
                        logger.info("Wake+Query: %r", query)
                        try:
                            await callback(query)
                        except Exception as exc:
                            logger.error("Callback error: %s", exc)
                    else:
                        # Just the wake word — respond with a greeting
                        logger.info("Wake word detected — greeting")
                        try:
                            await callback("hello")
                        except Exception as exc:
                            logger.error("Callback error: %s", exc)

                elif self._wake_active:
                    # Already in wake window — answer follow-up questions
                    logger.info("Follow-up (wake active): %r", text)
                    self._activate_wake()   # reset 30s timer
                    try:
                        await callback(text)
                    except Exception as exc:
                        logger.error("Callback error: %s", exc)
                else:
                    logger.debug("Ignored (no wake word): %r", text[:40])

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("listen_loop error: %s", exc)
                await asyncio.sleep(1.0)

        logger.info("listen_loop exited.")

    # ──────────────────────── Helpers ────────────────────────────────────────

    def _find_emeet_mic(self) -> Optional[int]:
        if not _HAS_SD:
            return None
        try:
            devices = sd.query_devices()
            for i, dev in enumerate(devices):
                name = dev.get("name", "").lower()
                if dev.get("max_input_channels", 0) > 0 and (
                    "emeet" in name or "c960" in name
                ):
                    return i
            return None
        except Exception:
            return None

    def _record_chunk(self) -> Optional[np.ndarray]:
        try:
            kwargs: dict = {
                "frames":     CHUNK_FRAMES,
                "samplerate": SAMPLE_RATE,
                "channels":   1,
                "dtype":      "float32",
                "blocking":   True,
            }
            if self._mic_index is not None:
                kwargs["device"] = self._mic_index
            audio = sd.rec(**kwargs)
            return audio.flatten()
        except Exception as exc:
            logger.error("Recording error: %s", exc)
            return None

    def _transcribe(self, audio: np.ndarray) -> str:
        try:
            segments, _ = self._whisper.transcribe(
                audio,
                language="en",
                beam_size=1,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 300},
            )
            parts = [seg.text.strip() for seg in segments
                     if seg.no_speech_prob < NO_SPEECH_THRESH]
            return " ".join(parts).strip()
        except Exception as exc:
            logger.error("Transcription error: %s", exc)
            return ""
