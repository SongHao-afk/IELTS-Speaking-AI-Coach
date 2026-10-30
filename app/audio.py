"""Deterministic recording diagnostics, NOT a pronunciation assessment."""
from __future__ import annotations

import io
import math
import re
import wave
from array import array
from dataclasses import dataclass, asdict


class InvalidAudio(ValueError):
    pass


@dataclass
class AudioMetrics:
    duration_seconds: float
    active_seconds: float
    speech_ratio: float
    pause_count: int
    clipping_percent: float
    peak_dbfs: float

    def serialize(self) -> dict:
        return asdict(self)


def wav_metrics(data: bytes) -> dict:
    """Measure silence/energy for PCM16 mono WAV. Thresholds are approximate."""
    try:
        with wave.open(io.BytesIO(data), 'rb') as reader:
            if reader.getcomptype() != 'NONE' or reader.getsampwidth() != 2:
                raise InvalidAudio('Please provide an uncompressed 16-bit PCM WAV recording.')
            channels = reader.getnchannels()
            sample_rate = reader.getframerate()
            frame_count = reader.getnframes()
            if channels not in (1, 2) or not (8000 <= sample_rate <= 96000):
                raise InvalidAudio('Unsupported WAV channel count or sample rate.')
            duration = frame_count / sample_rate
            if not (0.3 <= duration <= 200):
                raise InvalidAudio('Record between 0.3 seconds and 3 minutes 20 seconds.')
            pcm = reader.readframes(frame_count)
    except (EOFError, wave.Error) as exc:
        raise InvalidAudio('The audio file is not a readable WAV recording.') from exc

    samples = array('h')
    try:
        samples.frombytes(pcm)
    except (ValueError, BufferError) as exc:
        raise InvalidAudio('Incomplete PCM16 recording.') from exc
    if len(samples) != frame_count * channels:
        raise InvalidAudio('Incomplete audio samples.')
    if not samples:
        raise InvalidAudio('The recording is empty.')

    frame_size = max(1, int(sample_rate * 0.025))
    energies = []
    clipped = 0
    peak = 0
    # Process each frame without introducing NumPy or system audio dependencies.
    for start in range(0, frame_count, frame_size):
        end = min(frame_count, start + frame_size)
        square_sum = 0.0
        count = end - start
        for i in range(start, end):
            left = samples[i * channels]
            right = samples[i * channels + 1] if channels == 2 else left
            sample = (left + right) / 2
            square_sum += sample * sample
            peak = max(peak, abs(left), abs(right))
            clipped += (abs(left) >= 32760 or abs(right) >= 32760)
        energies.append(math.sqrt(square_sum / max(1, count)))

    floor = sorted(energies)[max(0, int(len(energies) * .12) - 1)]
    threshold = max(260, min(3000, floor * 1.9))
    active = [rms >= threshold for rms in energies]
    # Run-length smoothing prevents syllable breaks from counting as pauses.
    for i in range(1, len(active) - 1):
        if active[i - 1] and active[i + 1]:
            active[i] = True
    first = next((i for i, a in enumerate(active) if a), None)
    last = next((i for i in range(len(active)-1, -1, -1) if active[i]), None)
    pause_count = 0
    if first is not None and last is not None:
        inactive_run = 0
        for i in range(first, last + 1):
            if not active[i]:
                inactive_run += 1
            elif inactive_run:
                if inactive_run * .025 >= .55:
                    pause_count += 1
                inactive_run = 0

    active_sec = min(duration, sum(active) * .025)
    return AudioMetrics(
        duration_seconds=round(duration, 2),
        active_seconds=round(active_sec, 2),
        speech_ratio=round(active_sec / duration, 3),
        pause_count=pause_count,
        clipping_percent=round(clipped * 100 / frame_count, 2),
        peak_dbfs=round(20 * math.log10(max(1, peak) / 32768), 1),
    ).serialize()


def transcript_metrics(transcript: str, duration: float, audio: dict | None = None) -> dict:
    words = re.findall(r"\b[\w']+\b", transcript)
    # The ratio of spoken to quiet audio is a heuristic, not recognition accuracy.
    active = (audio or {}).get('active_seconds', 0)
    denominator = active if active >= 3 else duration
    wpm = round(len(words) * 60 / denominator, 1) if denominator > 0 else None
    fillers = len(re.findall(r'\b(?:um|uh|erm|hmm)\b|\byou know\b', transcript.lower()))
    repetitions = len(re.findall(r"\b([a-z']+)\s+\1\b", transcript.lower()))
    tips: list[str] = []
    if len(words) < 15:
        tips.append('Build a fuller answer: point → reason → specific example.')
    if wpm is not None and len(words) > 20 and wpm > 190:
        tips.append('Try a calmer pace so important ideas are easier to follow.')
    if fillers >= 3:
        tips.append('Replace repeated fillers with a brief silent pause.')
    if audio and audio['clipping_percent'] > 2:
        tips.append('Move a little farther from the microphone to reduce distortion.')
    if audio and audio['speech_ratio'] < .25:
        tips.append('The recording contains a lot of quiet audio; check microphone input.')
    if audio and audio['pause_count'] >= 4:
        tips.append('Plan two or three key ideas before speaking to reduce long pauses.')
    if not tips:
        tips.append('Nice practice session. Check whether each claim has a reason or example.')
    return {
        'word_count': len(words), 'estimated_wpm': wpm,
        'filler_count': fillers, 'repeated_words': repetitions,
        'audio': audio, 'practice_tips': tips,
        'notice': 'These are simple signals, not an IELTS score or phoneme-level pronunciation test.',
    }
