import os
import subprocess
import sys
from pathlib import Path

os.environ["TORCHAUDIO_USE_TORCHCODEC"] = "0"

def to_wav(input_file: Path) -> Path:
    wav_path = input_file.with_suffix(".wav")

    subprocess.run([
        "ffmpeg",
        "-y",
        "-i",
        str(input_file),
        str(wav_path)
    ], check=True)

    return wav_path

def separate_audio(input_file: str, output_dir: str):
    input_path = Path(input_file).resolve()
    output_path = Path(output_dir).resolve()

    if not input_path.exists():
        raise FileNotFoundError(input_path)

    output_path.mkdir(parents=True, exist_ok=True)

    wav_path = to_wav(input_path)

    subprocess.run([
        sys.executable,
        "-m",
        "demucs",
        "-n","htdemucs_6s",
        "-o",str(output_path),
        str(wav_path)
    ], check=True)

    print("Separated complete ✓")

if __name__ == "__main__":
    separate_audio("audio/顾彬 - 梁祝（钢琴曲）.mp3", "output")
