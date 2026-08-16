"""
voice.py — BOB Robot Voice Pipeline
====================================
Speech-to-Text : faster-whisper (tiny model, CPU, int8)
Text-to-Speech : pyttsx3 → espeak-ng → Bluetooth speaker
Microphone     : EMEET C960 USB mic, ALSA hw:0,0 @ 16 kHz
Platform       : Debian Linux arm64 (Arduino UNO Q)
"""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Awaitable, Callable, Optional

import numpy as np

logger = logging.getLogger(__name__)

# ──────────────────────────── Constants ────────────────────────────────────────
MIC_DEVICE    = "hw:0,0"   # ALSA card 0, device 0 (EMEET C960 USB mic)
SAMPLE_RATE   = 16_000     # Hz — required by Whisper
CHUNK_SECONDS = 3          # seconds per recording chunk
CHUNK_FRAMES  = SAMPLE_RATE * CHUNK_SECONDS

# Optional: raise this to suppress more background noise
NO_SPEECH_THRESHOLD = 0.6

# ──────────────────────────── Optional imports ──────────────────────────────────
try:
    import sounddevice as sd
    _HAS_SOUNDDEVICE = True
    logger.debug("sounddevice available — mic recording enabled")
except ImportError:
    sd = None  # type: ignore
    _HAS_SOUNDDEVICE = False
    logger.warning(
        "sounddevice not installed — listen_loop will be disabled. "
        "TTS (speak) still works."
    )

try:
    from faster_whisper import WhisperModel
    _HAS_WHISPER = True
except ImportError:
    WhisperModel = None  # type: ignore
    _HAS_WHISPER = False
    logger.warning("faster-whisper not installed — STT unavailable.")

try:
    import pyttsx3
    _HAS_PYTTSX3 = True
except ImportError:
    pyttsx3 = None  # type: ignore
    _HAS_PYTTSX3 = False
    logger.warning("pyttsx3 not installed — TTS unavailable.")


# ═══════════════════════════════════════════════════════════════════════════════
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
        self._tts_engine = None
        self._tts_lock = threading.Lock()
        self._running = False
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="voice")
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ─────────────────────────── Lifecycle ─────────────────────────────────────

    async def start(self) -> None:
        """Load Whisper model and initialise pyttsx3 TTS engine."""
        self._loop = asyncio.get_running_loop()
        self._running = True

        # --- STT: faster-whisper -----------------------------------------------
        if _HAS_WHISPER:
            logger.info("Loading Whisper tiny model (CPU / int8) …")
            try:
                self._whisper = await self._loop.run_in_executor(
                    self._executor,
                    lambda: WhisperModel("tiny", device="cpu", compute_type="int8"),
                )
                logger.info("Whisper model loaded successfully.")
            except Exception as exc:
                logger.error("Failed to load Whisper model: %s", exc, exc_info=True)
                self._whisper = None
        else:
            logger.warning("Skipping Whisper initialisation (package missing).")

        # --- TTS: pyttsx3 → espeak-ng ------------------------------------------
        if _HAS_PYTTSX3:
            logger.info("Initialising pyttsx3 TTS engine (espeak-ng) …")
            try:
                self._tts_engine = await self._loop.run_in_executor(
                    self._executor, self._init_tts
                )
                logger.info("pyttsx3 TTS engine ready.")
            except Exception as exc:
                logger.error("Failed to init pyttsx3: %s", exc, exc_info=True)
                self._tts_engine = None
        else:
            logger.warning("Skipping TTS initialisation (pyttsx3 missing).")

    def _init_tts(self):
        """Blocking TTS initialisation — run in executor thread."""
        engine = pyttsx3.init()
        # Use espeak-ng voice if available
        voices = engine.getProperty("voices")
        for v in voices:
            if "english" in v.name.lower() or "en" in v.id.lower():
                engine.setProperty("voice", v.id)
                break
        engine.setProperty("rate", 165)   # words per minute
        engine.setProperty("volume", 1.0)
        return engine

    async def stop(self) -> None:
        """Signal pipeline to stop and clean up resources."""
        logger.info("Stopping VoicePipeline …")
        self._running = False
        self._executor.shutdown(wait=False)
        logger.info("VoicePipeline stopped.")

    # ─────────────────────────── TTS ───────────────────────────────────────────

    async def speak(self, text: str) -> None:
        """
        Speak *text* via pyttsx3 in a background thread so the event loop
        is never blocked.
        """
        if not text:
            return

        if self._tts_engine is None:
            logger.warning("speak() called but TTS engine is not available.")
            return

        logger.info("TTS ▶ %r", text)

        loop = self._loop or asyncio.get_running_loop()
        await loop.run_in_executor(self._executor, self._blocking_speak, text)

    def _blocking_speak(self, text: str) -> None:
        """Thread-safe, blocking TTS call."""
        with self._tts_lock:
            try:
                self._tts_engine.say(text)
                self._tts_engine.runAndWait()
            except Exception as exc:
                logger.error("TTS error: %s", exc, exc_info=True)

    # ─────────────────────────── STT / Listen loop ─────────────────────────────

    async def listen_loop(
        self,
        callback: Callable[[str], Awaitable[None]],
    ) -> None:
        """
        Continuously record audio from the EMEET C960 mic in 3-second chunks,
        run Whisper transcription, and invoke *callback(text)* for each confident
        recognition.

        The loop runs until :meth:`stop` is called.

        :param callback: Async callable receiving the transcribed string.
        """
        if not _HAS_SOUNDDEVICE:
            logger.error(
                "listen_loop() unavailable: sounddevice is not installed. "
                "Install it with: pip install sounddevice"
            )
            return

        if self._whisper is None:
            logger.error(
                "listen_loop() unavailable: Whisper model is not loaded."
            )
            return

        logger.info(
            "Starting listen loop — mic=%s, rate=%d Hz, chunk=%ds",
            MIC_DEVICE, SAMPLE_RATE, CHUNK_SECONDS,
        )

        loop = self._loop or asyncio.get_running_loop()

        while self._running:
            try:
                # ---- Record chunk (blocking) in executor ----------------------
                audio_np = await loop.run_in_executor(
                    self._executor, self._record_chunk
                )

                if audio_np is None:
                    # Recording error — short back-off then retry
                    await asyncio.sleep(0.5)
                    continue

                # ---- Transcribe (blocking) in executor ------------------------
                text = await loop.run_in_executor(
                    self._executor,
                    lambda a=audio_np: self._transcribe(a),
                )

                if text:
                    logger.info("STT recognised: %r", text)
                    try:
                        await callback(text)
                    except Exception as exc:
                        logger.error(
                            "Callback raised an exception: %s", exc, exc_info=True
                        )

            except asyncio.CancelledError:
                logger.info("listen_loop cancelled.")
                break
            except Exception as exc:
                logger.error("Unexpected error in listen_loop: %s", exc, exc_info=True)
                await asyncio.sleep(1.0)

        logger.info("listen_loop exited.")

    # ─────────────────────────── Helpers (blocking) ────────────────────────────

    def _record_chunk(self) -> Optional[np.ndarray]:
        """
        Record *CHUNK_FRAMES* mono samples from the ALSA mic.
        Returns float32 numpy array normalised to [-1, 1], or None on error.
        """
        try:
            logger.debug("Recording %d-second chunk from %s …", CHUNK_SECONDS, MIC_DEVICE)
            audio = sd.rec(
                frames=CHUNK_FRAMES,
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                device=MIC_DEVICE,
                blocking=True,
            )
            # audio shape: (CHUNK_FRAMES, 1) → flatten to 1-D
            return audio.flatten()
        except Exception as exc:
            logger.error("Recording error: %s", exc, exc_info=True)
            return None

    def _transcribe(self, audio: np.ndarray) -> str:
        """
        Run Whisper transcription on a float32 audio array.
        Returns the recognised text, or empty string if not confident enough.
        """
        try:
            segments, info = self._whisper.transcribe(
                audio,
                language="en",
                beam_size=1,          # fast beam search for tiny model
                vad_filter=True,      # skip silent segments quickly
            )

            # Collect all confident segments
            parts: list[str] = []
            for seg in segments:
                if seg.no_speech_prob < NO_SPEECH_THRESHOLD:
                    parts.append(seg.text.strip())
                else:
                    logger.debug(
                        "Dropped segment (no_speech_prob=%.2f): %r",
                        seg.no_speech_prob, seg.text,
                    )

            result = " ".join(parts).strip()
            if result:
                logger.debug("Transcription result: %r", result)
            return result

        except Exception as exc:
            logger.error("Transcription error: %s", exc, exc_info=True)
            return ""


# ──────────────────────────── Quick self-test ──────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    async def _test() -> None:
        vp = VoicePipeline()
        await vp.start()
        await vp.speak("Hello, I am BOB. Voice pipeline is online.")

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
