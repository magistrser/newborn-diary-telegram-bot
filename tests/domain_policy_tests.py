from domain.policies import is_allowed, merge_compatible_payload_fields


def test_is_allowed_respects_chat_allowlist() -> None:
    assert is_allowed(
        chat_id=1,
        author='Mila',
        allowed_chat_ids=[2],
        allowed_authors=[],
    ) is False


def test_is_allowed_accepts_matching_chat_and_author() -> None:
    assert is_allowed(
        chat_id=2,
        author='Mila',
        allowed_chat_ids=[2],
        allowed_authors=['Mila'],
    ) is True


def test_merge_compatible_payload_fields_preserves_duration_only() -> None:
    merged = merge_compatible_payload_fields(
        {'kind': 'pee'},
        {'duration_min': 20, 'grams': 4200},
    )

    assert merged == {'kind': 'pee', 'duration_min': 20}
