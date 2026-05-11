import ctypes
import sys
import os
import threading
import keyboard
import pathlib
import json

from fontTools.varLib.mutator import curr

base = pathlib.Path(__file__).resolve().parent
dll_dir = base / "native" / "fluidsynth" / "bin"

if not dll_dir.is_dir():
    raise FileNotFoundError(dll_dir)

# 让 pyfluidsynth 的 find_library 和 Windows 依赖搜索都能看到它
os.environ["PATH"] = str(dll_dir) + os.pathsep + os.environ["PATH"]
os.add_dll_directory(str(dll_dir))
import fluidsynth

NOTE_TO_MIDI = {
  "A0":21,"A#0":22,"B0":23,
  "C1":24,"C#1":25,"D1":26,"D#1":27,"E1":28,"F1":29,"F#1":30,"G1":31,"G#1":32,"A1":33,"A#1":34,"B1":35,
  "C2":36,"C#2":37,"D2":38,"D#2":39,"E2":40,"F2":41,"F#2":42,"G2":43,"G#2":44,"A2":45,"A#2":46,"B2":47,
  "C3":48,"C#3":49,"D3":50,"D#3":51,"E3":52,"F3":53,"F#3":54,"G3":55,"G#3":56,"A3":57,"A#3":58,"B3":59,
  "C4":60,"C#4":61,"D4":62,"D#4":63,"E4":64,"F4":65,"F#4":66,"G4":67,"G#4":68,"A4":69,"A#4":70,"B4":71,
  "C5":72,"C#5":73,"D5":74,"D#5":75,"E5":76,"F5":77,"F#5":78,"G5":79,"G#5":80,"A5":81,"A#5":82,"B5":83,
  "C6":84,"C#6":85,"D6":86,"D#6":87,"E6":88,"F6":89,"F#6":90,"G6":91,"G#6":92,"A6":93,"A#6":94,"B6":95,
  "C7":96,"C#7":97,"D7":98,"D#7":99,"E7":100,"F7":101,"F#7":102,"G7":103,"G#7":104,"A7":105,"A#7":106,"B7":107,
  "C8":108
}
MIDI_TO_NOTE = {v: k for k, v in NOTE_TO_MIDI.items()}

# {
#     "C2":36,"D2":38,"E2":40,"F2":41,"G2":43,"A2":45,"B2":47,
#     "C3":48,"D3":50,"E3":52,"F3":53,"G3":55,"A3":57,"B3":59,
#     "C4":60,"D4":62,"E4":64,"F4":65,"G4":67,"A4":69,"B4":71,
#     "C5":72,"D5":74,"E5":76,"F5":77,"G5":79,"A5":81,"B5":83,
#     "C6":84,"D6":86,"E6":88,"F6":89,"G6":91,"A6":93,"B6":95,
#     # 升号音符
#     "C#4":61,"D#4":63,"F#4":66,"G#4":68,"A#4":70,
#     "C#5":73,"D#5":75,"F#5":78,"G#5":80,"A#5":82,
# }

class Toccata():
    def __init__(self, score_path:str, sf2_path:str):
        self.cursor = 0
        self.lock = threading.Lock()

        # loading scores
        self.score = self._load_score(score_path)

        # initialize FluidSynth Engine
        self.fs = fluidsynth.Synth(
            gain = 0.8,
            samplerate = 44100
        )

        self.fs.cc(0, 7, 120)

        # choose the video driver
        import platform
        system = platform.system()
        if system == "Windows":
            self.fs.start(driver="dsound")
        elif system == "Darwin":
            self.fs.start(driver="coreaudio")
        else:
            self.fs.start(driver="alsa")

        # loading SF2 timbre font
        self.sfid = self.fs.sfload(sf2_path)
        if self.sfid == -1:
            raise FileNotFoundError(f"SF2 load failed:{sf2_path}")

        # choose Timbre
        self.channel = 0
        self.fs.program_select(self.channel, self.sfid, bank=0, preset=0)

        # note delay persec
        self.note_duration = 1.5

        print(f"[Toccata] scores total: {len(self.score)} ✓")

    def _load_score(self, score_path:str) -> list:
        with open(score_path, 'r', encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data[0], dict):
            return data
        return [{"note": n, "duration": 0.8} for n in data]

    def _play_note(self, midi_pitch:int, duration:float):
        self.fs.noteon(self.channel, midi_pitch, 100)
        timer = threading.Timer(duration, self.fs.noteoff, (self.channel, midi_pitch))
        timer.daemon = True
        timer.start()

    def _on_keypress(self, event):
        if event.event_type != keyboard.KEY_DOWN:
            return

        with self.lock:
            item = self.score[self.cursor]
            self.cursor = (self.cursor + 1) % len(self.score)

        duration = item.get("duration", self.note_duration)

        for note_name in item["notes"]:
            if note_name == "R":
                continue
            midi_pitch = NOTE_TO_MIDI.get(note_name)
            if midi_pitch:
                self._play_note(midi_pitch, duration)

    def run(self):
        keyboard.hook(self._on_keypress)
        print("[Toccata] Listening • Any key to Play • ESC to Exit")
        keyboard.wait("esc")
        self.fs.delete()
        print("[Toccata] FluidSynth release and quit")

def group_notes_into_chords(notes: list, tolerance: float = 0.05) -> list:
    if not notes:
        return []

    sorted_notes = sorted(notes, key=lambda n: n.start)

    groups = []
    current_group = [sorted_notes[0]]
    for note in sorted_notes[1:]:
        if note.start - current_group[0].start <= tolerance:
            current_group.append(note)
        else:
            groups.append(current_group)
            current_group = [note]
    groups.append(current_group)

    return groups

def insert_rests(groups: list, rest_threshold: float = 0.1) -> list:
    result = []
    for i,group in enumerate(groups):
        result.append(group)
        if i < len(groups) - 1:
            gap = groups[i+1][0].start - max(n.end for n in group)
            if gap > rest_threshold:
                result.append({"rest":True, "duration":round(gap, 3)})

    return result



if __name__ == "__main__":
    toccata = Toccata(
        # score_path ="scores/score-moli.json",
        score_path ="scores/scores-顾彬 - 梁祝（钢琴 b曲）.json",
        # sf2_path = "fonts/FluidR3_GM.sf2"
        sf2_path = "fonts/Full Grand Piano.sf2"
        # sf2_path = "scores/aaviolin.sf2"
    )
    toccata.run()