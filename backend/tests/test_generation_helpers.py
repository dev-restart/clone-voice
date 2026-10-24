from app.services.generation_helpers import split_plain_tts_text


def test_split_plain_tts_text_preserves_line_and_paragraph_pauses():
    segments = split_plain_tts_text(
        "봉식오빠~~~~~!\n\n일어났어요?? 아직도 자는거 아니죠?\n연락도 없고.. 봉식오빠 보고 싶은데 ..",
        model_id="voxcpm",
        language="ko",
    )

    assert segments is not None
    assert [segment["text"] for segment in segments] == [
        "봉식오빠~~~~~!",
        "일어났어요?? 아직도 자는거 아니죠?",
        "연락도 없고.. 봉식오빠 보고 싶은데 ..",
    ]
    assert [segment["pause_after_ms"] for segment in segments] == [900, 480, 0]


def test_split_plain_tts_text_auto_chunks_only_long_voxcpm_text():
    long_text = "이 문장은 긴 본문 자동 분할을 검증하기 위한 문장입니다. " * 90
    segments = split_plain_tts_text(long_text, model_id="voxcpm", language="ko")

    assert segments is not None
    assert len(segments) > 1
    assert all(segment["text"] for segment in segments)
    assert segments[-1]["pause_after_ms"] == 0


def test_split_plain_tts_text_keeps_short_single_paragraph_as_one_model_call():
    assert split_plain_tts_text("짧은 한 문장입니다.", model_id="voxcpm", language="ko") is None


def test_split_plain_tts_text_auto_chunks_long_duration_even_under_korean_char_limit():
    text = (
        "여기 한 남자가 있습니다. "
        "오랫동안 코드를 만져온 베테랑, 머릿속엔 이미 완성된 앱의 설계도가 가득하죠. "
        "그가 만들려는 건 뜻밖에도 상장입니다. "
    ) * 12

    segments = split_plain_tts_text(text, model_id="voxcpm", language="ko", speed=0.8)

    assert segments is not None
    assert len(segments) > 1
    assert all(segment["text"] for segment in segments)
    assert segments[-1]["pause_after_ms"] == 0
