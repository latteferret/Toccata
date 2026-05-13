import pretty_midi
import json
from copy import deepcopy
from toccata import  MIDI_TO_NOTE

def quantize_to_grid(value_sec: float,
                     beat_duration: float,
                     subdivisions: int = 16) -> float:
    grid = beat_duration / subdivisions
    quatized = round(value_sec / grid) * grid
    return max(grid, quatized)

def filter_noise(notes: list,
                 min_duration: float = 0.05,
                 min_velocity: int = 50,
                 use_pitch_weighted_floor: bool = True) -> list:
    def pitch_floor(pitch: int) -> int:
        if not use_pitch_weighted_floor:
            return min_velocity
        if pitch < 48:  # C1~B2
            return 60
        elif pitch < 60:  # C3~B3
            return 55
        elif pitch < 84:  # C4~B5
            return min_velocity  # 使用传入值（默认50）
        else:  # C6+
            return 40

    return [
        n for n in notes
        if (n.end - n.start) >= min_duration
           and n.velocity >= pitch_floor(n.pitch)
    ]

def remove_decay_ghosts(
        notes: list,
        decay_window_sec: float = 2.0,
        velocity_drop_ratio: float = 0.60,
        min_velocity_abs: int = 40
) -> list:
    # decay_window_sec:   衰减窗口，钢琴低音区衰减慢可以调大到3.0
    # velocity_drop_ratio: 相对衰减比，0.75 意味着掉到75%以下才视为幻影
    # min_velocity_abs:   绝对最低力度，低于此值无条件删除

    from collections import defaultdict

    by_pitch = defaultdict(list)
    for note in notes:
        by_pitch[note.pitch].append(note)

    keep = set()

    for pitch, pitch_notes in by_pitch.items():
        pitch_notes.sort(key=lambda n: n.start)
        cluster_anchor = None

        for note in pitch_notes:
            if cluster_anchor is None:
                keep.add(id(note))
                cluster_anchor = note
                continue

            time_gap = note.start - cluster_anchor.start

            if time_gap > decay_window_sec:
                # 超出衰减窗口：视为全新的击键，开启新簇
                keep.add(id(note))
                cluster_anchor = note
                continue

            # 在衰减窗口内：OR 条件，满足任意一个即为幻影
            is_ghost = (
                    note.velocity < cluster_anchor.velocity * velocity_drop_ratio
                    or note.velocity < min_velocity_abs
            )

            if is_ghost:
                # 幻影：把它的时长归还给簇锚点
                if note.end > cluster_anchor.end:
                    cluster_anchor.end = note.end
                # cluster_anchor 不更新，继续以第一个真实击键为基准
            else:
                # 力度足够强：视为真实的新击键，开启新簇
                keep.add(id(note))
                cluster_anchor = note

    return [n for n in notes if id(n) in keep]

def merge_same_pitch_clusters(notes: list,
                               max_gap_sec: float = 0.25) -> list:
    from collections import defaultdict

    by_pitch = defaultdict(list)
    for note in notes:
        by_pitch[note.pitch].append(note)

    result = []
    for pitch, pitch_notes in by_pitch.items():
        pitch_notes.sort(key=lambda n: n.start)
        merged = [pitch_notes[0]]

        for note in pitch_notes[1:]:
            prev = merged[-1]
            gap = note.start - prev.end  # 上一个结束到这个开始的间隙

            if gap <= max_gap_sec:
                # 间隙极小：粘合，取较大 velocity，end 延伸到最晚
                prev.end = max(prev.end, note.end)
                prev.velocity = max(prev.velocity, note.velocity)
            else:
                merged.append(note)

        result.extend(merged)

    return result

def separate_voices(notes:list,
                   split_pitch: int = 60,
                   mode: str = "both") -> list:
    if mode == "treble":
        return [n for n in notes if n.pitch >= split_pitch]
    elif mode == "bass":
        return [n for n in notes if n.pitch < split_pitch]
    return notes

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
    for i, group in enumerate(chord_groups):
        result.append(group)
        if i < len(chord_groups) - 1:
            group_end  = max(n.end for n in group)
            next_start = chord_groups[i + 1][0].start
            gap_sec    = next_start - group_end
            if gap_sec > rest_threshold_beats * beats_duration:
                q_gap = quantize_to_grid(gap_sec, beats_duration, subdivisions)
                result.append({"rest":True,
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

        debug: bool = True
):
    midi = pretty_midi.PrettyMIDI(midi_path)

    # 1. get the bpm
    tempo_change_times, tempos = midi.get_tempo_changes()
    bpm = float(tempos[0]) if len(tempos) > 0 else 120.0
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
    all_notes = filter_noise(all_notes,
                             min_duration_sec,
                             min_velocity=50,
                             use_pitch_weighted_floor=True                             )

    if debug:
        print(f"[过滤后] 总音符数: {len(all_notes)}")

    before = len(all_notes)
    all_notes = remove_decay_ghosts(
        all_notes,
        decay_window_sec=2.0,
        velocity_drop_ratio=0.60,
        min_velocity_abs=40
    )
    if debug:
        print(f"[幻影清除] {before} → {len(all_notes)} 个音符 "
              f"(删除 {before - len(all_notes)} 个衰减幻影)")

    before = len(all_notes)
    all_notes = merge_same_pitch_clusters(all_notes, max_gap_sec=0.25)
    if debug:
        print(f"[同音高粘合] {before} → {len(all_notes)}（合并 {before - len(all_notes)} 个碎片）")

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
            score.append({"notes": ["R"], "duration": item["duration_beats"]})
            continue

        group = item
        names = []
        for note in group:
            name = MIDI_TO_NOTE.get(note.pitch, f"UNK{note.pitch}")
            if name.startswith("UNK"):
                unknown.add(note.pitch)
            names.append(name)

        raw_dur = max(n.end - n.start for n in group)
        dur_beats = round(raw_dur / beat_duration, 3)

        # ★ velocity：取组内最大值，映射到 1~127
        velocity = min(127, max(1, max(n.velocity for n in group)))

        score.append({"notes": names, "duration": dur_beats, "velocity": velocity})

    # 9. output
    output = {"bpm": round(bpm, 2), "score": score}
    with open(output_path, "w", encoding="utf-8") as f:
        # 元数据单独一行，score 数组每条一行（便于阅读）
        f.write('{\n')
        f.write(f'  "bpm": {round(bpm, 2)},\n')
        f.write('  "score": [\n')
        for i, item in enumerate(score):
            comma = "," if i < len(score) - 1 else ""
            f.write(f'    {json.dumps(item, ensure_ascii=False)}{comma}\n')
        f.write('  ]\n}\n')

    if debug:
        chords = sum(1 for s in score if len(s["notes"]) > 1)
        rests = sum(1 for s in score if s["notes"] == ["R"])
        print(f"\n[完成] {len(score)} 个事件 → {output_path}")
        print(f"  单音:{len(score) - chords - rests}  和弦:{chords}  休止:{rests}")
        if unknown:
            print(f"  未识别音高:{sorted(unknown)}")

    return bpm

def merge_consecutive_same_notes(score: list, short_rest_threshold: float = 0.25) -> list:
    if not score:
        return score

    result = [deepcopy(score[0])]

    for curr in score[1:]:
        prev = result[-1]

        # 情况1：穿透短休止
        if (prev["notes"] == ["R"]
                and prev.get("type") != "phrase_break"
                and prev["duration"] < short_rest_threshold
                and len(result) >= 2):
            anchor = result[-2]
            if anchor["notes"] != ["R"]:
                anchor_set = set(anchor["notes"])
                curr_set = set(curr["notes"])
                if anchor_set == curr_set:
                    anchor["duration"] = round(
                        anchor["duration"] + prev["duration"] + curr["duration"], 3)
                    # velocity 取较大值
                    anchor["velocity"] = max(
                        anchor.get("velocity", 80), curr.get("velocity", 80))
                    result.pop()
                    continue
                if anchor_set.issubset(curr_set) and len(curr_set - anchor_set) <= 2:
                    anchor["notes"] = sorted(curr_set)
                    anchor["duration"] = round(max(anchor["duration"], curr["duration"]), 3)
                    anchor["velocity"] = max(anchor.get("velocity", 80), curr.get("velocity", 80))
                    result.pop()
                    continue
                if curr_set.issubset(anchor_set) and len(anchor_set - curr_set) <= 2:
                    anchor["duration"] = round(
                        anchor["duration"] + prev["duration"] + curr["duration"], 3)
                    result.pop()
                    continue

        # 情况2：直接相邻音符
        if prev["notes"] != ["R"] and curr["notes"] != ["R"]:
            prev_set = set(prev["notes"])
            curr_set = set(curr["notes"])
            if prev_set == curr_set:
                prev["duration"] = round(prev["duration"] + curr["duration"], 3)
                prev["velocity"] = max(prev.get("velocity", 80), curr.get("velocity", 80))
                continue
            if prev_set.issubset(curr_set) and len(curr_set - prev_set) <= 2:
                prev["notes"] = sorted(curr_set)
                prev["duration"] = round(max(prev["duration"], curr["duration"]), 3)
                prev["velocity"] = max(prev.get("velocity", 80), curr.get("velocity", 80))
                continue
            if curr_set.issubset(prev_set) and len(prev_set - curr_set) <= 2:
                prev["duration"] = round(prev["duration"] + curr["duration"], 3)
                continue

        result.append(deepcopy(curr))
    return result

def classify_and_clean_rests(
    score: list,
    short_rest_threshold: float = 0.5,
    long_rest_threshold: float = 2.0,
) -> list:
    result = []
    for item in score:
        if item["notes"] != ["R"]:
            result.append(item)
            continue
        dur = item["duration"]
        if dur < short_rest_threshold:
            if result and result[-1]["notes"] != ["R"]:
                result[-1]["duration"] = round(
                    result[-1]["duration"] + dur, 3
                )
            continue
        elif dur > long_rest_threshold:
            result.append({
                "notes": ["R"],
                "duration": dur,
                "type": "phrase_break"
            })
        else:
            result.append(item)
    return result

def normalize_score(
        score: list,
        merge_duplicates: bool = True,
        short_rest_threshold: float = 0.5,
        long_rest_threshold: float = 2.0,
        min_note_duration: float = 0.2,
        debug: bool = True
) -> list:
    original_len = len(score)

    # 1. filter the short notes
    score = [
        s for s in score
        if s["notes"] == ["R"] or s["duration"] >= min_note_duration
    ]

    # 2. classify and clean rests
    score = classify_and_clean_rests(score, short_rest_threshold, long_rest_threshold)

    # 3. merge the same notes
    if merge_duplicates:
        score = merge_consecutive_same_notes(score, short_rest_threshold)

    # 4. clean rest again
    score = classify_and_clean_rests(score, short_rest_threshold, long_rest_threshold)

    if debug:
        pb = sum(1 for s in score if s.get("type") == "phrase_break")
        rests = sum(1 for s in score if s["notes"] != ["R"] and s.get("type") != "phrase_break")
        notes = sum(1 for s in score if s["notes"] != ["R"])
        print(f"[normalize] {original_len} -> {len(score)}")
        print(f"notes/chord:{notes} rest:{rests} phrase:{pb}")
    return score

def remove_rests_keep_phrase(score: list) -> list:
    return [s for s in score
            if not (s["notes"] == ["R"] and s.get("type") != "phrase_break")]

if __name__ == "__main__":
    # bpm = midi_to_score_quantized(
    #     midi_path="midis/Call of Silence [钢琴].mid",
    #     output_path="scores_raw/Call of Silence [钢琴].json",
    #     voice_mode="treble",       # 只要高音区
    #     split_pitch=60,            # C4 以上
    #     subdivisions=16,
    #     debug=True
    # )

    bpm = midi_to_score_quantized(
        midi_path="midis/Call of Silence [钢琴].mid",
        output_path="scores_raw/Call of Silence [钢琴].json",
        voice_mode="both",
        split_pitch=60,
        subdivisions=16,
        debug=True
    )

    with open("scores_raw/Call of Silence [钢琴].json", "r") as f:
        wrapper = json.load(f)

    raw     = wrapper["score"]
    cleaned = normalize_score(
        raw,
        merge_duplicates=True,
        short_rest_threshold=0.5,
        long_rest_threshold=2.0,
        min_note_duration=0.2
    )

    # cleaned = [s for s in cleaned if s["notes"] != ["R"]]
    cleaned = remove_rests_keep_phrase(cleaned)
    output  = {"bpm": round(bpm, 2), "score": cleaned}

    with open("scores/Call of Silence [钢琴].json", "w", encoding="utf-8") as f:
        f.write('{\n')
        f.write(f'  "bpm": {round(bpm, 2)},\n')
        f.write('  "score": [\n')
        for i, item in enumerate(cleaned):
            comma = "," if i < len(cleaned) - 1 else ""
            f.write(f'    {json.dumps(item, ensure_ascii=False)}{comma}\n')
        f.write('  ]\n}\n')
    print(f"[写出] scores/Call of Silence [钢琴].json  BPM={bpm:.1f}")