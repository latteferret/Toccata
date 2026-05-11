import os.path
from pathlib import Path
import pretty_midi
import json
from itertools import groupby
from numba.core.types import unknown

from toccata import NOTE_TO_MIDI, group_notes_into_chords, insert_rests, MIDI_TO_NOTE


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

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(score, f, ensure_ascii=False, indent=2)

    chord_count = sum(1 for s in score if len(s["notes"]) > 1)
    rest_count = sum(1 for s in score if s["notes"] == ["R"])

    print(f"[transcription completed] total {len(score)} notes")
    print(f"monophonic : {len(score) - chord_count - rest_count} ")
    print(f"chord : {chord_count}")
    print(f"rest: {rest_count}")

    if unknown_piches:
        print(f"unknown piches: {sorted(unknown_piches)}")
    print(f" -> {output_path}")

# def midi_to_score(midi_path:str, output_path:str,
#                   tempo_bpm:float = None):
#     midi = pretty_midi.PrettyMIDI(midi_path)
#
#     #
#     melody_track = next(
#         inst for inst in midi.instruments if not inst.is_drum
#     )
#
#     MIDI_TO_NOTE = {v: k for k, v in NOTE_TO_MIDI.items()}
#
#     score = []
#
#     for note in melody_track.notes:
#         note_name = MIDI_TO_NOTE.get(note.pitch, f"UNK{note.pitch}")
#         duration = round(note.end - note.start, 3)
#         score.append({"note": note_name, "duration": duration})
#
#     midi_filename = Path(midi_path).stem
#     if midi_filename.startswith("midi-"):
#         score_filename = "scores-" + midi_filename[5:]
#     else:
#         score_filename = "scores-" + midi_filename
#
#     if output_path:
#         output_dir = os.path.join(output_path, f"{score_filename}.json")
#     else:
#         output_dir = f"{score_filename}.json"
#
#     with open(output_dir, "w", encoding="utf-8") as f:
#         json.dump(score, f, ensure_ascii=False, indent=2)
#
#     print(f"Successfully transcribed, total {len(score)} notes")


# midi_to_score("midis/顾彬 - 梁祝（钢琴 b曲）.mid", "scores")

midi_to_score(
    midi_path="midis/顾彬 - 梁祝（钢琴 b曲）.mid",
    output_path="scores/scores-顾彬 - 梁祝（钢琴 b曲）.json",
    chord_tolerance=0.05,
    rest_threshold=0.1,
    melody_only=False
)