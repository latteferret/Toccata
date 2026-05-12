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

NOTE_TO_MIDI = {}
for octave in range(0, 8):
    base = {"C":0,"D":2,"E":4,"F":5,"G":7,"A":9,"B":11}
    sharps = {"C#":1,"D#":3,"F#":6,"G#":8,"A#":10,"A#":10,"B#":0}
    for name, semi in {**base, **sharps}.items():
        midi_num = 12 * (octave + 1) + semi
        NOTE_TO_MIDI[f"{name}{octave}"] = midi_num

MIDI_TO_NOTE = {v: k for k, v in NOTE_TO_MIDI.items()}

extra = {61:"C#4",63:"D#4",66:"F#4",68:"G#4",70:"A#4",
         73:"C#5",75:"D#5",78:"F#5",80:"G#5",82:"A#5",
         85:"C#6",87:"D#6",90:"F#6",92:"G#6",94:"A#6"}
MIDI_TO_NOTE.update(extra)

class Toccata():
    def __init__(self, score_path:str, sf2_path:str, bpm = 120.0):
        self.beat_duration = 60.0/bpm
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
        self.note_duration = 1.8

        print(f"[Toccata] scores total: {len(self.score)} ✓")

    def _load_score(self, score_path:str) -> list:
        with open(score_path, 'r', encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data[0], dict):
            return data
        return [{"note": n, "duration": 0.8} for n in data]

    # def _play_note(self, midi_pitch:int, duration:float):
    #     self.fs.noteon(self.channel, midi_pitch, 100)
    #     timer = threading.Timer(duration, self.fs.noteoff, (self.channel, midi_pitch))
    #     timer.daemon = True
    #     timer.start()

    def _play_note(self, midi_pitch, duration_beats):
        duration_sec = duration_beats * self.beat_duration
        self.fs.noteon(self.channel, midi_pitch, 100)
        timer = threading.Timer(duration_sec, self.fs.noteoff,[self.channel, midi_pitch])
        timer.daemon = True
        timer.start()

    def _on_keypress(self, event):
        if event.event_type != keyboard.KEY_DOWN:
            return

        with self.lock:
            # auto skip all phrase_break
            while self.cursor < len(self.score):
                item = self.score[self.cursor]
                if item.get("type") == "phrase_break":
                    self.cursor += 1
                else:
                    break

            item = self.score[self.cursor]
            self.cursor = (self.cursor + 1) % len(self.score)

        print(f"[Playing] {item}")

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
        score_path ="scores/Call of Silence [钢琴].json",
        # sf2_path = "fonts/FluidR3_GM.sf2"
        sf2_path = "fonts/Full Grand Piano.sf2"
        # sf2_path = "scores/aaviolin.sf2"
    )
    toccata.run()