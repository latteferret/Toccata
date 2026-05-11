# import setuptools
import numpy as np
np.complex = complex
from piano_transcription_inference import PianoTranscription, sample_rate, load_audio

# transcriptor = PianoTranscription(device='cpu')
# audio, _ = load_audio('audio/顾彬 - 梁祝（钢琴曲）.wav', sr=sample_rate, mono=True)
# transcriptor.transc.
# ribe(audio, '顾彬 - 梁祝（钢琴 b曲）.mid')