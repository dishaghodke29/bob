"""
voice.py — BOB Robot Voice Pipeline
=====================================
Speech-to-Text : faster-whisper  (tiny model, CPU, int8)
Text-to-Speech : piper-tts → ffmpeg audio filter (T3 throat-resonant voice)
Microphone     : EMEET C960 USB mic, auto-detected (falls back to hw:1,0)
Platform       : Debian Linux arm64 (Arduino UNO Q)
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Awaitable, Callable, Optional

import numpy as np

logger = logging.getLogger(__name__)

# ──────────────────────────── Constants ──────────────────────────────────────
SAMPLE_RATE       = 16_000    # Hz — required by Whisper
CHUNK_SECONDS     = 3         # seconds per recording chunk
CHUNK_FRAMES      = SAMPLE_RATE * CHUNK_SECONDS
NO_SPEECH_THRESH  = 0.55      # drop segment if no_speech_prob is above this

# Piper TTS settings
PIPER_BIN         = "/home/arduino/bob/venv/bin/piper"
PIPER_MODEL       = "/home/arduino/bob/models/en_US-amy-medium.onnx"
PIPER_MODEL_JSON  = "/home/arduino/bob/models/en_US-amy-medium.onnx.json"

# T3 Throat-Resonant voice filter chain for ffmpeg
# Deepens pitch slightly, boosts chest/throat frequencies, tamps highs
T3_FILTER = (
    "volume=0.72,"
    "asetrate=22050*1.26,"
    "aresample=22050,"
    "equalizer=f=620:width_type=h:w=280:g=11,"
    "equalizer=f=1380:width_type=h:w=400:g=7,"
    "equalizer=f=2800:width_type=h:w=500:g=4,"
    "atempo=0.94"
)

# ──────────────────────────── Optional imports ────────────────────────────────
try:
    import sounddevice as sd
    _HAS_SD = True
    logger.debug("sounddevice available")
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
    """
    Async voice pipeline for BOB.

    Usage::

        vp = VoicePipeline()
        await vp.start()
        await vp.speak("Hello, I am BOB.")
        await vp.listen_loop(callback=my_async_callback)
        await vp.stop()
    """

    def __init__(self) -> None:
        self._whisper: Optional[WhisperModel] = None
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="voice")
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._running   = False
        self._speaking  = False   # True while BOB is playing audio (mic muted)
        self._mic_index: Optional[int] = None   # sounddevice device index

    # ──────────────────────── Lifecycle ──────────────────────────────────────

    async def start(self) -> None:
        """Load Whisper model and detect microphone."""
        self._loop    = asyncio.get_running_loop()
        self._running = True

        # Detect EMEET mic
        self._mic_index = self._find_emeet_mic()
        if self._mic_index is not None:
            logger.info("EMEET C960 mic found at device index %d", self._mic_index)
        else:
            logger.warning("EMEET C960 not found — using default mic")

        # Verify piper binary
        if not Path(PIPER_BIN).exists():
            logger.warning("piper not found at %s — TTS will be silent", PIPER_BIN)
        else:
            logger.info("Piper TTS ready (%s)", PIPER_BIN)

        # Verify piper model
        if not Path(PIPER_MODEL).exists():
            logger.warning("Piper model not found at %s", PIPER_MODEL)

        # Load STT model
        if _HAS_WHISPER:
            logger.info("Loading Whisper tiny model (CPU/int8)…")
            try:
                self._whisper = await self._loop.run_in_executor(
                    self._executor,
                    lambda: WhisperModel("tiny", device="cpu", compute_type="int8"),
                )
                logger.info("Whisper model loaded.")
            except Exception as exc:
                logger.error("Whisper load failed: %s", exc, exc_info=True)
                self._whisper = None
        else:
            logger.warning("faster-whisper missing — STT unavailable")

        # Warm up piper (avoids first-speak delay)
        asyncio.create_task(self._warmup_tts())

    async def _warmup_tts(self) -> None:
        """Silently warm up Piper so first real speak has no init delay."""
        await asyncio.sleep(3)
        await self._loop.run_in_executor(
            self._executor,
            lambda: self._blocking_speak(".", silent=True),
        )
        logger.info("TTS warmed up.")

    async def stop(self) -> None:
        """Stop the pipeline and clean up."""
        logger.info("Stopping VoicePipeline…")
        self._running = False
        self._executor.shutdown(wait=False)
        logger.info("VoicePipeline stopped.")

    # ──────────────────────── TTS ─────────────────────────────────────────────

    async def speak(self, text: str) -> None:
        """
        Speak *text* via Piper TTS with T3 throat filter.
        Mutes mic during playback to prevent feedback loops.
        """
        if not text or not text.strip():
            return

        # Clean text — remove markdown/special chars that piper can't pronounce
        clean = re.sub(r"[*_`#\[\]{}|<>]", "", text).strip()
        if not clean:
            return

        logger.info("TTS ▶ %r", clean)
        self._speaking = True
        try:
            loop = self._loop or asyncio.get_running_loop()
            await loop.run_in_executor(
                self._executor,
                lambda: self._blocking_speak(clean),
            )
        finally:
            self._speaking = False

    def _blocking_speak(self, text: str, silent: bool = False) -> None:
        """
        Run piper → ffmpeg pipeline in a blocking thread.
        Piper generates raw PCM → ffmpeg applies T3 filter → plays via aplay.
        """
        try:
            if not Path(PIPER_BIN).exists() or not Path(PIPER_MODEL).exists():
                return

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name

            try:
                # Step 1: Piper generates raw WAV
                piper_cmd = [
                    PIPER_BIN,
                    "--model", PIPER_MODEL,
                    "--output_file", tmp_path,
                ]
                piper_proc = subprocess.run(
                    piper_cmd,
                    input=text.encode("utf-8"),
                    capture_output=True,
                    timeout=10,
                )
                if piper_proc.returncode != 0:
                    logger.error("Piper error: %s", piper_proc.stderr.decode())
                    return

                if silent:
                    return  # warm-up: don't play audio

                # Step 2: ffmpeg applies T3 filter, outputs to aplay
                ffmpeg_cmd = [
                    "ffmpeg", "-y",
                    "-i", tmp_path,
                    "-af", T3_FILTER,
                    "-f", "wav",
                    "pipe:1",
                ]
                aplay_cmd = ["aplay", "-q"]

                ffmpeg_proc = subprocess.Popen(
                    ffmpeg_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                aplay_proc = subprocess.Popen(
                    aplay_cmd,
                    stdin=ffmpeg_proc.stdout,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                ffmpeg_proc.stdout.close()
                aplay_proc.wait(timeout=30)
                ffmpeg_proc.wait()

            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        except subprocess.TimeoutExpired:
            logger.error("TTS timeout — piper took too long")
        except Exception as exc:
            logger.error("TTS error: %s", exc, exc_info=True)

    # ──────────────────────── STT / Listen loop ───────────────────────────────

    async def listen_loop(
        self,
        callback: Callable[[str], Awaitable[None]],
    ) -> None:
        """
        Continuously record audio from the EMEET C960 mic in 3-second chunks,
        transcribe with Whisper, and call *callback(text)* when speech detected.
        Mic is automatically muted while BOB is speaking.
        """
        if not _HAS_SD:
            logger.error("sounddevice not installed — listen_loop disabled")
            return

        if self._whisper is None:
            logger.error("Whisper not loaded — listen_loop disabled")
            return

        logger.info(
            "Listening (mic_index=%s, rate=%d Hz, chunk=%ds)",
            self._mic_index, SAMPLE_RATE, CHUNK_SECONDS,
        )

        loop = self._loop or asyncio.get_running_loop()

        while self._running:
            try:
                # Pause while BOB is speaking (avoid picking up own voice)
                if self._speaking:
                    await asyncio.sleep(0.1)
                    continue

                # Record chunk
                audio_np = await loop.run_in_executor(
                    self._executor, self._record_chunk
                )

                if audio_np is None:
                    await asyncio.sleep(0.5)
                    continue

                # Skip if still speaking (recorded while speaking)
                if self._speaking:
                    continue

                # Transcribe
                text = await loop.run_in_executor(
                    self._executor,
                    lambda a=audio_np: self._transcribe(a),
                )

                if text:
                    logger.info("STT: %r", text)
                    try:
                        await callback(text)
                    except Exception as exc:
                        logger.error("Callback error: %s", exc, exc_info=True)

            except asyncio.CancelledError:
                logger.info("listen_loop cancelled.")
                break
            except Exception as exc:
                logger.error("listen_loop error: %s", exc, exc_info=True)
                await asyncio.sleep(1.0)

        logger.info("listen_loop exited.")

    # ──────────────────────── Helpers ────────────────────────────────────────

    def _find_emeet_mic(self) -> Optional[int]:
        """Find EMEET C960 microphone in sounddevice device list."""
        if not _HAS_SD:
            return None
        try:
            devices = sd.query_devices()
            for i, dev in enumerate(devices):
                name = dev.get("name", "").lower()
                if dev.get("max_input_channels", 0) > 0 and (
                    "emeet" in name or "c960" in name or "usb" in name
                ):
                    logger.info("Found input mic: [%d] %s", i, dev["name"])
                    return i
            # Fall back to default input device
            default = sd.default.device[0]
            logger.warning("EMEET not found — using default input device %d", default)
            return None
        except Exception as exc:
            logger.warning("Mic detection error: %s", exc)
            return None

    def _record_chunk(self) -> Optional[np.ndarray]:
        """
        Record CHUNK_FRAMES samples from mic.
        Returns float32 numpy array [-1, 1], or None on error.
        """
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
            logger.error("Recording error: %s", exc, exc_info=True)
            return None

    def _transcribe(self, audio: np.ndarray) -> str:
        """Transcribe float32 audio → text string, or '' if not confident."""
        try:
            segments, _ = self._whisper.transcribe(
                audio,
                language="en",
                beam_size=1,        # greedy = fastest for tiny model
                vad_filter=True,    # skip silent chunks
                vad_parameters={"min_silence_duration_ms": 300},
            )

            parts: list[str] = []
            for seg in segments:
                if seg.no_speech_prob < NO_SPEECH_THRESH:
                    parts.append(seg.text.strip())

            result = " ".join(parts).strip()
            return result

        except Exception as exc:
            logger.error("Transcription error: %s", exc, exc_info=True)
            return ""


# ─────────────────────────── Quick self-test ─────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    async def _test() -> None:
        vp = VoicePipeline()
        await vp.start()
        await vp.speak("Hey, I am BOB. Voice pipeline is working perfectly.")

        async def _cb(text: str) -> None:
            print(f"[callback] Heard: {text!r}")
            await vp.speak(f"You said: {text}")

        try:
            await vp.listen_loop(_cb)
        except KeyboardInterrupt:
            pass
        finally:
            await vp.stop()

    asyncio.run(_test())
