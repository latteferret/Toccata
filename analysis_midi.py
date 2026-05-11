import pretty_midi
import json

from toccata import NOTE_TO_MIDI, group_notes_into_chords, insert_rests, MIDI_TO_NOTE

def quantize_to_grid(value_sec: float,
                     beat_duration: float,
                     subdivisions: int = 16) -> float:
    grid = beat_duration / subdivisions
    quatized = round(value_sec / grid) * grid
    return max(grid, quatized)

def second_to_note_name(duration_sec: float, beat_duration: float) -> str:
    ratio = duration_sec / beat_duration
    table = {4.0:"全音符", 3.0:"附点二分", 2.0:"二分音符",
             1.5:"附点四分", 1.0:"四分音符", 0.75:"附点八分",
             0.5:"八分音符", 0.25:"十六分音符", 0.125:"三十二分"}
    closest = min(table.keys(), key=lambda x: abs(x - ratio))
    return table[closest] if abs(closest - ratio) < 0.15 else f"{ratio:.2f} beats"

def separate_voices(notes:list,
                   split_pitch: int = 60,
                   mode: str = "both") -> list:
    if mode == "treble":
        return [n for n in notes if n.pitch >= split_pitch]
    elif mode == "bass":
        return [n for n in notes if n.pitch < split_pitch]
    return notes

def filter_noise(notes: list,
                 min_duration: float = 0.05,
                 min_velocity: int = 20) -> list:
    return [n for n in notes
            if (n.end - n.start) >= min_duration
            and n.velocity >= min_velocity]

def group_into_chords(notes: list, tolerance_beats: float = 0.1) -> list:
    if not notes:
        return []
    sorted_notes = sorted(notes, key=lambda n: n.start)
    group, current = [], [sorted_notes[0]]
    for note in sorted_notes[1:]:
        if note.start - current[0].start <= tolerance_beats:
            current.append(note)
        else:
            group.append(current)
            current = [note]
    group.append(current)
    return group

def insert_rests_quantized(chord_groups: list,
                           beats_duration: float,
                           subdivisions: int = 16,
                           rest_threshold_beats: float = 0.25) -> list:
    result = []
    grid = beats_duration / subdivisions
    for i, group in enumerate(chord_groups):
        result.append(group)
        if i < len(chord_groups) - 1:
            group_end  = max(n.end for n in group)
            next_start = chord_groups[i + 1][0].start
            gap_sec    = next_start - group_end

            if gap_sec > rest_threshold_beats * beats_duration:
                q_gap = quantize_to_grid(gap_sec, beats_duration, subdivisions)
                result.append({"rest":True,
                               "duration_sec":q_gap,
                               "duration_beats": round(q_gap / beats_duration, 3)})
    return result


def midi_to_score_quantized(
        midi_path: str,
        output_path: str,

        voice_mode:str = "both",
        split_pitch: int = 60,

        subdivisions: int = 16,
        chord_tolerance_beats: float = 0.12,
        rest_threshold_beats: float = 0.25,

        min_duration_sec: float = 0.05,
        min_velocity: int = 15,

        duration_format: str = "beats",
        debug: bool = True
):
    midi = pretty_midi.PrettyMIDI(midi_path)

    # 1. get the bpm
    tempo_times, tempos = midi.get_tempo_changes()
    bpm = tempos[0] if len(tempos) > 0 else 120.0
    beat_duration = 60.0 / bpm

    if debug:
        print(f"[量化] 检测 BPM: {bpm:.1f}  →  一拍 = {beat_duration:.4f}s")
        print(f"[量化] 十六分音符网格 = {beat_duration / subdivisions * 1000:.1f}ms")

    # 2. combine the percussion
    all_notes = []
    for inst in midi.instruments:
        if not inst.is_drum:
            all_notes.extend(inst.notes)

    if debug:
        print(f"[过滤前] 总音符数: {len(all_notes)}")

    # 3. filter out noise
    all_notes = filter_noise(all_notes, min_duration_sec, min_velocity)

    if debug:
        print(f"[过滤后] 总音符数: {len(all_notes)}")

    # 4. vocal separation
    all_notes = separate_voices(all_notes, split_pitch, voice_mode)

    if debug:
        print(f"[声部({voice_mode})] 音符数: {len(all_notes)}")

    # 5. quantitative alignment
    grid = beat_duration / subdivisions
    for note in all_notes:
        note.start = round(note.start / grid) * grid
        # end 至少保留一个网格长度
        raw_dur = note.end - note.start
        q_dur   = max(grid, round(raw_dur / grid) * grid)
        note.end = note.start + q_dur

    # 6. chord group
    tol_sec = chord_tolerance_beats * beat_duration
    chord_groups = group_into_chords(all_notes, tol_sec)

    # 7. insert quantitative rest
    events = insert_rests_quantized(
        chord_groups, beat_duration, subdivisions, rest_threshold_beats
    )

    # 8. build score list
    score = []
    unknown = set()

    for item in events:
        if isinstance(item, dict) and item.get("rest"):
            dur = (item["duration_beats"] if duration_format == "beats"
                   else round(item["duration_sec"], 3))
            score.append({"notes": ["R"], "duration": dur})
            continue

        group = item
        names = []
        for note in group:
            name = MIDI_TO_NOTE.get(note.pitch, f"UNK{note.pitch}")
            if name.startswith("UNK"):
                unknown.add(note.pitch)
            names.append(name)

        raw_dur = max(n.end - n.start for n in group)
        if duration_format == "beats":
            dur = round(raw_dur / beat_duration, 3)
        else:
            dur = round(raw_dur, 3)

        score.append({"notes": names, "duration": dur})

    # 9. output
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("[\n")
        for i, item in enumerate(score):
            line = json.dumps(item, ensure_ascii=False)
            if i < len(score) - 1:
                f.write(f"  {line},\n")
            else:
                f.write(f"  {line}\n")
        f.write("]\n")

    if debug:
        chords = sum(1 for s in score if len(s["notes"]) > 1)
        rests = sum(1 for s in score if s["notes"] == ["R"])
        single = len(score) - chords - rests
        print(f"\n[完成] → {output_path}")
        print(f"  单音: {single}  和弦: {chords}  休止: {rests}")
        print(f"  时长格式: {duration_format}"
              f"{'  (1.0 = 一拍)' if duration_format == 'beats' else ''}")
        if unknown:
            print(f"  未识别音高: {sorted(unknown)}")

    return bpm

def midi_to_score(midi_path: str,
                  output_path: str,
                  track_index: int = None,
                  chord_tolerance: float = 0.05,
                  rest_threshold: float = 0.1,
                  melody_only: bool = False):
    midi = pretty_midi.PrettyMIDI(midi_path)

    non_drum_tracks = [inst for inst in midi.instruments if not inst.is_drum]
    if not non_drum_tracks:
        raise ValueError("MIDI no drum tracks found")

    if track_index is not None:
        target_track = non_drum_tracks[track_index]
    else:
        target_track = max(non_drum_tracks, key=lambda t: len(t.notes))

    print(f"target_track: {target_track.name or 'unknown'},"
          f"total_tracks: {len(target_track.notes)}")

    # group notes into chords
    chord_groups = group_notes_into_chords(target_track.notes, chord_tolerance)

    # group note with rests
    groups_with_rests = insert_rests(chord_groups, rest_threshold)

    # build the score list
    score = []
    unknown_piches = set()

    for item in groups_with_rests:
        if isinstance(item, dict) and item.get("rest"):
            score.append({"notes": ["R"], "duration": item["duration"]})
            continue

        note_group = item

        if melody_only:
            note_group = [max(note_group, key=lambda n: n.pitch)]

        note_names = []
        for note in note_group:
            name = MIDI_TO_NOTE.get(note.pitch)
            if name is None:
                name = f"UNK{note.pitch}"
                unknown_piches.add(note.pitch)
            note_names.append(name)

        duration = round(max(n.end - n.start for n in note_group), 3)

        score.append({"notes": note_names, "duration": duration})

    # with open(output_path, "w", encoding="utf-8") as f:
    #     json.dump(score, f, ensure_ascii=False, indent=2, separators=(",", ":"))

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("[\n")
        for i, item in enumerate(score):
            line = json.dumps(item, ensure_ascii=False)
            if i < len(score) - 1:
                f.write(f"  {line},\n")
            else:
                f.write(f"  {line}\n")
        f.write("]\n")

    chord_count = sum(1 for s in score if len(s["notes"]) > 1)
    rest_count = sum(1 for s in score if s["notes"] == ["R"])

    print(f"[transcription completed] total {len(score)} notes")
    print(f"monophonic : {len(score) - chord_count - rest_count} ")
    print(f"chord : {chord_count}")
    print(f"rest: {rest_count}")

    if unknown_piches:
        print(f"unknown piches: {sorted(unknown_piches)}")
    print(f" -> {output_path}")



# midi_to_score(
#     midi_path="midis/Call of Silence [钢琴].mid",
#     output_path="scores/score-Call of Silence [钢琴].json",
#     chord_tolerance=0.05,
#     rest_threshold=0.1,
#     melody_only=False
# )

midi_to_score_quantized(
        midi_path="midis/Call of Silence [钢琴].mid",
        output_path="scores/score-Call of Silence [钢琴].json",
        voice_mode="treble",       # 只要高音区
        split_pitch=60,            # C4 以上
        subdivisions=16,
        duration_format="beats",
        debug=True
)

# midi_to_score_quantized(
#         midi_path="midis/Call of Silence [钢琴].mid",
#         output_path="scores/score-Call of Silence [钢琴].json",
#         voice_mode="both",
#         chord_tolerance_beats=0.12,
#         rest_threshold_beats=0.25,
#         duration_format="beats",
#         debug=True
# )