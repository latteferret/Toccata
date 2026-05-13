import os
import threading
import keyboard
import pathlib
import json

base = pathlib.Path(__file__).resolve().parent
dll_dir = base / "native" / "fluidsynth" / "bin"
if dll_dir.is_dir():
    os.environ["PATH"] = str(dll_dir) + os.pathsep + os.environ["PATH"]
    os.add_dll_directory(str(dll_dir))

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
    def __init__(self, score_path:str,
                 sf2_path:str,
                 bpm:float = None,
                 release_multiplier: float = 1.5):

        # release_multiplier
        # 1.0 严格按照谱面时长，尾音被截断
        # 1.5 延长50%，给SF2 Release 包络留出时间 适合钢琴
        # 2.0 更长尾音，适合弦乐/pad 音色

        self.release_multiplier = release_multiplier
        self.cursor = 0
        self.lock = threading.Lock()

        # loading scores
        self.score, detected_bpm = self._load_score(score_path)
        resolved_bpm = bpm if bpm is not None else detected_bpm
        self.beat_duration = 60.0 / resolved_bpm
        print(f"[Toccata] BPM = {resolved_bpm:1f}  "
              f"一拍 = {self.beat_duration:.4f}s  "
              f"release x {release_multiplier}")

        self._active_timers: dict[int, threading.Timer] = {}
        self._timer_lock = threading.Lock()

        # initialize FluidSynth Engine
        self.fs = fluidsynth.Synth(
            gain = 0.8,
            samplerate = 44100
        )

        # self.fs.cc(0, 7, 120)

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
        self.fs.cc(self.channel, 64, 0)
        # self.note_duration = 1.8

        print(f"[Toccata] scores total: {len(self.score)} ✓")

    def _load_score(self, score_path:str) -> tuple[list, float]:
        with open(score_path, 'r', encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            bpm = float(data.get('bpm', 120.0))
            score = data['score']
        else:
            bpm = 120.0
            score = data
            print("[Toccata]  ⚠ 旧格式 JSON，使用默认 BPM=120")
        return score, bpm

    def _play_note(self, midi_pitch: int, duration_beats: float, velocity: int = 100):
        duration_sec = duration_beats * self.beat_duration
        # Release 尾音时长：实际音符时长 × 倍率
        release_sec  = duration_sec * self.release_multiplier

        with self._timer_lock:
            # ★ 若该音高已有活跃 Timer，先取消旧的 noteoff
            if midi_pitch in self._active_timers:
                self._active_timers[midi_pitch].cancel()
                # 不立即 noteoff，让新的 noteon 接管

            # 发声
            self.fs.noteon(self.channel, midi_pitch, velocity)

            # 延迟 noteoff（使用 release_sec 而非 duration_sec）
            def do_noteoff(pitch):
                self.fs.noteoff(self.channel, pitch)
                with self._timer_lock:
                    self._active_timers.pop(pitch, None)

            t = threading.Timer(release_sec, do_noteoff, args=[midi_pitch])
            t.daemon = True
            t.start()
            self._active_timers[midi_pitch] = t

    def _on_keypress(self, event):
        if event.event_type != keyboard.KEY_DOWN:
            return

        with self.lock:
            # auto skip all phrase_break
            while self.cursor < len(self.score):
                if self.score[self.cursor].get("type") == "phrase_break":
                    self.cursor += 1
                else:
                    break

            if self.cursor >= len(self.score):
                self.cursor = 0

            item = self.score[self.cursor]
            self.cursor = (self.cursor + 1) % len(self.score)

        duration = item.get("duration", 1.0)

        # ★ 读取 velocity，默认 90（中等力度）
        velocity = min(127, max(1,item.get("velocity", 90)))
        print(f"[Playing] {item}")

        for note_name in item["notes"]:
            if note_name == "R":
                continue
            midi_pitch = NOTE_TO_MIDI.get(note_name)
            if midi_pitch:
                self._play_note(midi_pitch, duration, velocity)

    def run(self):
        keyboard.hook(self._on_keypress)
        print("[Toccata] Listening • Any key to Play • ESC to Exit")
        keyboard.wait("esc")
        # 清理所有活跃 Timer
        with self._timer_lock:
            for t in self._active_timers.values():
                t.cancel()
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
        sf2_path = "fonts/Full Grand Piano.sf2",
        # 钢琴尾音延长 80%
        release_multiplier = 1.8

        # sf2_path = "scores/aaviolin.sf2"
    )
    toccata.run()