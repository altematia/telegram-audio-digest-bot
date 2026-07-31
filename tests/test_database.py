from datetime import UTC, datetime, timedelta

from app.database import Database


def test_recording_and_output_round_trip(tmp_path) -> None:
    database = Database(tmp_path / "bot.sqlite3")
    database.initialize()

    recording_id = database.add_recording(
        chat_id=10, user_id=20, source_name="voice.ogg", transcript="Привет, мир"
    )
    database.save_output(recording_id, "short", "Коротко")

    recording = database.get_recording(recording_id)
    assert recording is not None
    assert recording.chat_id == 10
    assert recording.user_id == 20
    assert recording.transcript == "Привет, мир"
    assert database.get_output(recording_id, "short") == "Коротко"


def test_purge_removes_expired_recordings(tmp_path) -> None:
    database = Database(tmp_path / "bot.sqlite3")
    database.initialize()
    recording_id = database.add_recording(
        chat_id=1, user_id=2, source_name="old.mp3", transcript="Старый текст"
    )
    old_time = (datetime.now(UTC) - timedelta(days=40)).isoformat()
    with database._connect() as connection:
        connection.execute(
            "UPDATE recordings SET created_at = ? WHERE id = ?", (old_time, recording_id)
        )

    assert database.purge_older_than(30) == 1
    assert database.get_recording(recording_id) is None


def test_secret_authorized_user_atomically_claims_bot(tmp_path) -> None:
    database = Database(tmp_path / "bot.sqlite3")
    database.initialize()

    assert database.get_owner() is None
    assert database.claim_owner(123) == 123
    assert database.claim_owner(456) == 123
    assert database.get_owner() == 123
