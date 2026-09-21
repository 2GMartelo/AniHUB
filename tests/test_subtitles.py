from anihub.services import subtitles as st

VTT = """WEBVTT

1
00:00:01.000 --> 00:00:03.500 align:middle
Привет,<i> мир</i>

00:01:02.250 --> 00:01:04.000
Вторая
строка
"""
SRT = "1\n00:00:05,000 --> 00:00:06,500\nHello &amp; bye\n\n2\n00:00:07,000 --> 00:00:08,000\n{\\an8}Top line\n"
ASS = r"""[Script Info]
Title: x

[V4+ Styles]
Format: Name, Fontname
Style: Default,Arial

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:10.00,0:00:12.50,Default,,0,0,0,,{\i1}Привет, мир{\i0}\Nвторая, со строка
Dialogue: 0,0:00:11.00,0:00:13.00,Sign,,0,0,0,,Надпись
Comment: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,ignored
"""


def test_vtt_cues_are_plain_text_with_times():
    cues = st.parse(VTT)
    assert [(c.start, c.end, c.text) for c in cues] == [(1000, 3500, "Привет, мир"), (62250, 64000, "Вторая\nстрока")]


def test_srt_entities_and_tags():
    cues = st.parse(SRT)
    assert [c.text for c in cues] == ["Hello & bye", "Top line"] and cues[0].start == 5000 and cues[1].end == 8000


def test_ass_dialogue_with_commas_in_the_text_and_overlapping_lines():
    cues = st.parse(ASS)
    assert [(c.start, c.end) for c in cues] == [(10000, 12500), (11000, 13000)]
    assert cues[0].text == "Привет, мир\nвторая, со строка"
    track = st.Track(cues)
    assert track.at(9999) == [] and track.at(10000) == ["Привет, мир\nвторая, со строка"]
    assert track.at(11500) == ["Привет, мир\nвторая, со строка", "Надпись"]                  # both lines at once
    assert track.at(12500) == ["Надпись"] and track.at(13000) == []


def test_junk_gives_no_cues_and_track_is_falsy():
    assert st.parse("nothing here") == [] and not st.Track([])
