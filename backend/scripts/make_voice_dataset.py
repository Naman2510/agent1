"""Build the synthetic voice dataset (datasets/v1/voice/) for the `voice` evaluation suite.

    python scripts/make_voice_dataset.py          # needs espeak-ng on PATH

Writes one 16 kHz mono WAV per spoken part into `parts/`, three noise beds into `noise/`, and
`cases.jsonl` — how each case is put together from them: lead-in, parts, the pauses between them,
trailing quiet, and any noise under it all. The suite assembles the audio from these at run time
(eval/voice.py), so the ground truth — where speech starts, pauses and ends — is known exactly,
by construction, rather than annotated.

The case list below was fixed before any endpointing was measured on it: which kinds of turn, in
what proportions, with which pauses. Changing it changes every voice number, so it is a new dataset
version, not an edit.

Synthetic, not human (README.md). The outputs are committed; this script records how they were
made, and is only needed to make them again.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

ROOT = Path(__file__).resolve().parents[2] / "datasets" / "v1" / "voice"
SAMPLE_RATE = 16_000
ESPEAK_RATE = 22_050
LEAD_MS = 500
TRAIL_MS = 1500
# Silence trimmed from each synthesised part: below this level for a whole 10 ms frame.
TRIM_DBFS = -45.0


@dataclass(frozen=True)
class Part:
    text: str
    voice: str
    speed: int  # words per minute, espeak-ng -s


@dataclass(frozen=True)
class Case:
    id: str
    kind: str  # single | hesitation | multi_sentence | backchannel | noise
    language: str  # en | hi | hi-Latn | none
    parts: tuple[Part, ...] = ()
    pauses_ms: tuple[int, ...] = ()
    noise: str | None = None
    noise_dbfs: float | None = None
    duration_ms: int | None = None  # noise-only cases


EN_F, EN_M, GB = "en-us+f3", "en-us+m3", "en-gb"
HI, HI_F = "hi", "hi+f3"


def _one(id_: str, language: str, text: str, voice: str, speed: int, **noise: object) -> Case:
    return Case(id_, "single", language, (Part(text, voice, speed),), **noise)  # type: ignore[arg-type]


def _two(
    id_: str,
    kind: str,
    language: str,
    first: str,
    second: str,
    pause_ms: int,
    voice: str,
    speed: int,
    **noise: object,
) -> Case:
    return Case(
        id_,
        kind,
        language,
        (Part(first, voice, speed), Part(second, voice, speed)),
        (pause_ms,),
        **noise,  # type: ignore[arg-type]
    )


FAN = {"noise": "fan", "noise_dbfs": -35.0}

CASES: tuple[Case, ...] = (
    # --- one sentence, no pause inside it ---------------------------------------------------
    _one("single-en-01", "en", "What is Kirchhoff's voltage law?", EN_F, 165),
    _one("single-en-02", "en", "Can you explain Ohm's law with an example?", EN_M, 175),
    _one("single-en-03", "en", "How does a capacitor store energy?", GB, 160),
    _one("single-en-04", "en", "Why is the current the same in a series circuit?", EN_F, 180),
    _one("single-en-05", "en", "What is the difference between AC and DC?", EN_M, 165, **FAN),
    _one("single-en-06", "en", "Explain the superposition theorem.", GB, 175),
    _one(
        "single-en-07",
        "en",
        "How do I find the equivalent resistance of parallel resistors?",
        EN_F,
        170,
    ),
    _one("single-en-08", "en", "What does Thevenin's theorem say?", EN_M, 160),
    _one("single-hi-01", "hi", "किरचॉफ का वोल्टेज नियम क्या है?", HI, 160),
    _one("single-hi-02", "hi", "ओम का नियम समझाइए।", HI_F, 170, **FAN),
    _one("single-hil-01", "hi-Latn", "Capacitor energy kaise store karta hai?", EN_M, 165),
    _one("single-hil-02", "hi-Latn", "Series circuit mein current same kyun hota hai?", EN_F, 170),
    # --- one sentence, with a hesitation inside it: the first part ends mid-sentence ---------
    _two(
        "hesitation-en-01",
        "hesitation",
        "en",
        "What is the",
        "voltage across the second resistor?",
        200,
        EN_F,
        165,
    ),
    _two(
        "hesitation-en-02",
        "hesitation",
        "en",
        "How do I calculate the",
        "power dissipated in this circuit?",
        250,
        EN_M,
        170,
    ),
    _two(
        "hesitation-en-03",
        "hesitation",
        "en",
        "Can you tell me",
        "why the diode only conducts one way?",
        300,
        GB,
        160,
        **FAN,
    ),
    _two(
        "hesitation-en-04",
        "hesitation",
        "en",
        "In the last example",
        "where did the minus sign come from?",
        350,
        EN_F,
        175,
    ),
    _two(
        "hesitation-en-05",
        "hesitation",
        "en",
        "What happens to the current",
        "when I add another resistor in parallel?",
        400,
        EN_M,
        165,
    ),
    _two(
        "hesitation-en-06",
        "hesitation",
        "en",
        "Why do we take",
        "the loop direction as clockwise?",
        450,
        GB,
        170,
    ),
    _two(
        "hesitation-en-07",
        "hesitation",
        "en",
        "Is the voltage across a capacitor",
        "allowed to change instantly?",
        500,
        EN_F,
        160,
    ),
    _two(
        "hesitation-en-08",
        "hesitation",
        "en",
        "How is Norton's theorem",
        "related to Thevenin's theorem?",
        550,
        EN_M,
        180,
    ),
    _two(
        "hesitation-hi-01",
        "hesitation",
        "hi",
        "किरचॉफ का करंट नियम",
        "किस सिद्धांत पर आधारित है?",
        600,
        HI,
        165,
    ),
    _two(
        "hesitation-hi-02",
        "hesitation",
        "hi",
        "इस सर्किट में",
        "कुल प्रतिरोध कितना होगा?",
        650,
        HI_F,
        160,
    ),
    _two(
        "hesitation-hil-01",
        "hesitation",
        "hi-Latn",
        "Mujhe yeh samajh nahi aaya ki",
        "current divide kaise hota hai?",
        700,
        EN_F,
        170,
    ),
    _two(
        "hesitation-hil-02",
        "hesitation",
        "hi-Latn",
        "Is example mein",
        "voltage drop kitna hoga?",
        750,
        EN_M,
        165,
        **FAN,
    ),
    # --- two sentences in one turn: the first is complete, and more is coming ----------------
    _two(
        "multi-en-01",
        "multi_sentence",
        "en",
        "I have a doubt.",
        "What is Kirchhoff's current law?",
        250,
        EN_F,
        170,
    ),
    _two(
        "multi-en-02",
        "multi_sentence",
        "en",
        "Okay, I understood the first part.",
        "Now what about the second loop?",
        300,
        EN_M,
        165,
    ),
    _two(
        "multi-en-03",
        "multi_sentence",
        "en",
        "Sorry, one more question.",
        "Why is the capacitor voltage continuous?",
        350,
        GB,
        175,
        **FAN,
    ),
    _two(
        "multi-en-04",
        "multi_sentence",
        "en",
        "Let me see.",
        "Is the answer twelve volts?",
        400,
        EN_F,
        160,
    ),
    _two(
        "multi-en-05",
        "multi_sentence",
        "en",
        "That makes sense.",
        "Can you give me another example?",
        450,
        EN_M,
        170,
    ),
    _two(
        "multi-en-06",
        "multi_sentence",
        "en",
        "Wait.",
        "Did you say the resistors are in series?",
        500,
        GB,
        165,
    ),
    _two(
        "multi-en-07",
        "multi_sentence",
        "en",
        "I tried this problem.",
        "My answer was two amperes, is that right?",
        550,
        EN_F,
        175,
    ),
    _two(
        "multi-en-08",
        "multi_sentence",
        "en",
        "What is a node?",
        "And how is it different from a junction?",
        600,
        EN_M,
        160,
    ),
    _two(
        "multi-hi-01",
        "multi_sentence",
        "hi",
        "मुझे एक सवाल पूछना है।",
        "ओम का नियम कब लागू नहीं होता?",
        650,
        HI,
        165,
    ),
    _two(
        "multi-hi-02",
        "multi_sentence",
        "hi",
        "ठीक है, समझ गया।",
        "अब अगला उदाहरण बताइए।",
        700,
        HI_F,
        170,
        **FAN,
    ),
    _two(
        "multi-hil-01",
        "multi_sentence",
        "hi-Latn",
        "Sir, ek doubt hai.",
        "Parallel circuit mein voltage same kyun rehta hai?",
        750,
        EN_M,
        170,
    ),
    _two(
        "multi-hil-02",
        "multi_sentence",
        "hi-Latn",
        "Theek hai.",
        "Ab Thevenin theorem samjhao.",
        400,
        EN_F,
        165,
    ),
    # --- acknowledgements: speech, but not a question ----------------------------------------
    Case("backchannel-en-01", "backchannel", "en", (Part("Hmm.", EN_M, 150),)),
    Case("backchannel-en-02", "backchannel", "en", (Part("Okay.", EN_F, 165),)),
    Case("backchannel-en-03", "backchannel", "en", (Part("Yes.", GB, 160),)),
    Case("backchannel-en-04", "backchannel", "en", (Part("Right.", EN_M, 170),)),
    Case("backchannel-hi-01", "backchannel", "hi", (Part("हाँ।", HI, 160),)),
    Case("backchannel-hil-01", "backchannel", "hi-Latn", (Part("Haan.", EN_F, 160),)),
    # --- no speech at all -----------------------------------------------------------------
    Case("noise-quiet", "noise", "none", noise="white", noise_dbfs=-60.0, duration_ms=4000),
    Case("noise-white", "noise", "none", noise="white", noise_dbfs=-35.0, duration_ms=4000),
    Case("noise-loud-white", "noise", "none", noise="white", noise_dbfs=-25.0, duration_ms=4000),
    Case("noise-fan", "noise", "none", noise="fan", noise_dbfs=-30.0, duration_ms=4000),
    Case("noise-keyboard", "noise", "none", noise="keyboard", noise_dbfs=-25.0, duration_ms=4000),
    Case(
        "noise-keyboard-loud", "noise", "none", noise="keyboard", noise_dbfs=-15.0, duration_ms=4000
    ),
)


# --- synthesis ---------------------------------------------------------------------------------


def _espeak() -> str:
    path = shutil.which("espeak-ng")
    if path is None:
        raise SystemExit("espeak-ng is not installed")
    return path


def _espeak_version() -> str:
    out = subprocess.run(  # noqa: S603 - the resolved espeak-ng binary
        [_espeak(), "--version"], capture_output=True, text=True, check=True
    ).stdout
    return out.split("Data at")[0].strip()


def _synthesise(part: Part, workdir: Path) -> np.ndarray:
    raw = workdir / "part.wav"
    subprocess.run(  # noqa: S603 - the resolved espeak-ng binary; the text is ours
        [_espeak(), "-v", part.voice, "-s", str(part.speed), "-w", str(raw), part.text],
        check=True,
        capture_output=True,
    )
    with wave.open(str(raw), "rb") as w:
        if w.getframerate() != ESPEAK_RATE or w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise RuntimeError(f"unexpected espeak-ng output format for {part.text!r}")
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float64)
    # 22 050 Hz -> 16 000 Hz: a polyphase filter, so nothing above 8 kHz folds back into the band.
    resampled = resample_poly(audio / 32768.0, 320, 441)
    return _trim(resampled)


def _trim(audio: np.ndarray) -> np.ndarray:
    frame = SAMPLE_RATE // 100
    frames = len(audio) // frame
    levels = [
        20 * np.log10(np.sqrt(np.mean(audio[i * frame : (i + 1) * frame] ** 2)) + 1e-12)
        for i in range(frames)
    ]
    loud = [i for i, level in enumerate(levels) if level > TRIM_DBFS]
    if not loud:
        raise RuntimeError("synthesised part is silent")
    trimmed = audio[loud[0] * frame : (loud[-1] + 1) * frame].copy()
    fade = SAMPLE_RATE // 200  # 5 ms, so the cut edges do not click
    ramp = np.linspace(0.0, 1.0, fade)
    trimmed[:fade] *= ramp
    trimmed[-fade:] *= ramp[::-1]
    return trimmed


def _noise_beds(seconds: float = 6.0) -> dict[str, np.ndarray]:
    """Unit-RMS beds, scaled per case. Seeded once here and committed, so the run-time audio
    never depends on a random generator's version."""
    n = int(seconds * SAMPLE_RATE)
    rng = np.random.default_rng(20260927)
    white = rng.standard_normal(n)
    t = np.arange(n) / SAMPLE_RATE
    hum = sum(np.sin(2 * np.pi * f * t) / k for k, f in enumerate((100, 200, 300, 400), start=1))
    fan = hum + 0.5 * np.convolve(rng.standard_normal(n), np.ones(40) / 40, mode="same") * 8
    keyboard = np.zeros(n)
    click = np.exp(-np.arange(160) / 25.0) * rng.standard_normal(160)
    position = 800
    while position + 160 < n:
        keyboard[position : position + 160] += click
        position += int(rng.integers(1600, 4800))  # a key every 100-300 ms
    return {
        name: bed / np.sqrt(np.mean(bed**2))
        for name, bed in (("white", white), ("fan", fan), ("keyboard", keyboard))
    }


def _write(path: Path, audio: np.ndarray, *, peak_dbfs: float | None = -3.0) -> None:
    if peak_dbfs is not None:
        audio = audio * (10 ** (peak_dbfs / 20) / max(np.max(np.abs(audio)), 1e-9))
    pcm = np.clip(np.round(audio * 32767), -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())


def main() -> None:
    _espeak()
    for sub in ("parts", "noise"):
        (ROOT / sub).mkdir(parents=True, exist_ok=True)
        for old in (ROOT / sub).glob("*.wav"):
            old.unlink()

    beds = _noise_beds()
    for name, bed in beds.items():
        # Stored at a fixed -20 dBFS RMS; a case's `noise_dbfs` is relative to full scale.
        _write(ROOT / "noise" / f"{name}.wav", bed * 10 ** (-20 / 20), peak_dbfs=None)

    lines = []
    with tempfile.TemporaryDirectory() as tmp:
        for case in CASES:
            parts = []
            for index, part in enumerate(case.parts):
                name = f"{case.id}-{'ab'[index]}"
                audio = _synthesise(part, Path(tmp))
                _write(ROOT / "parts" / f"{name}.wav", audio)
                parts.append(
                    {
                        "file": f"parts/{name}.wav",
                        "text": part.text,
                        "voice": part.voice,
                        "speed_wpm": part.speed,
                        "duration_ms": round(len(audio) * 1000 / SAMPLE_RATE),
                    }
                )
            record = {
                "id": case.id,
                "kind": case.kind,
                "language": case.language,
                "lead_ms": LEAD_MS,
                "parts": parts,
                "pauses_ms": list(case.pauses_ms),
                "trail_ms": TRAIL_MS,
                "noise": None
                if case.noise is None
                else {"file": f"noise/{case.noise}.wav", "dbfs": case.noise_dbfs},
            }
            if case.duration_ms is not None:
                record["duration_ms"] = case.duration_ms
            lines.append(json.dumps(record, ensure_ascii=False))

    (ROOT / "cases.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (ROOT / "SYNTHESIS.txt").write_text(
        f"{_espeak_version()}\n"
        "resampled 22050 -> 16000 Hz with scipy.signal.resample_poly(320, 441)\n"
        f"trimmed below {TRIM_DBFS} dBFS per 10 ms frame, 5 ms fades, peak -3 dBFS\n",
        encoding="utf-8",
    )
    print(f"wrote {len(CASES)} cases to {ROOT}")


if __name__ == "__main__":
    main()
