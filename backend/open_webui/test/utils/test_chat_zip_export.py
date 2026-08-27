from open_webui.routers.chats import (
    _export_timestamp,
    _linear_messages,
    _session_start,
)


class FakeChat:
    def __init__(self, id, title, chat, created_at=0):
        self.id = id
        self.title = title
        self.chat = chat
        self.created_at = created_at


def message(role, content, timestamp, parent_id=None):
    return {
        "role": role,
        "content": content,
        "timestamp": timestamp,
        "parentId": parent_id,
    }


class TestExportTimestamp:
    """
    A bad timestamp must not raise. The merge sorts on this key and the caller
    turns any exception into a skipped group, so one malformed message would
    drop a whole student out of the ZIP.
    """

    def test_numbers_pass_through(self):
        assert _export_timestamp({"timestamp": 100}) == 100.0
        assert _export_timestamp({"timestamp": 12.5}) == 12.5

    def test_numeric_string_is_coerced(self):
        assert _export_timestamp({"timestamp": "1700000000"}) == 1700000000.0

    def test_missing_and_malformed_sort_first(self):
        assert _export_timestamp({}) == 0.0
        assert _export_timestamp({"timestamp": None}) == 0.0
        assert _export_timestamp({"timestamp": "later"}) == 0.0
        assert _export_timestamp({"timestamp": True}) == 0.0

    def test_mixed_values_are_sortable(self):
        messages = [{"timestamp": 200}, {"timestamp": None}, {"timestamp": 100}]
        assert [m["timestamp"] for m in sorted(messages, key=_export_timestamp)] == [
            None,
            100,
            200,
        ]


class TestLinearMessages:
    """
    `chat["messages"]` is only rewritten when the browser saves the chat, so the
    export reads the history the way the frontend does. Anything else loses the
    turns of every session that ended without a save.
    """

    def test_history_wins_over_a_stale_flat_list(self):
        history = {
            "currentId": "m4",
            "messages": {
                "m1": message("user", "q1", 100),
                "m2": message("assistant", "a1", 110, "m1"),
                "m3": message("user", "q2", 200, "m2"),
                "m4": message("assistant", "a2", 220, "m3"),
            },
        }
        chat = FakeChat(
            "c1",
            "Session",
            {"messages": [history["messages"]["m1"]], "history": history},
        )
        assert [m["content"] for m in _linear_messages(chat)] == ["q1", "a1", "q2", "a2"]

    def test_only_the_current_branch_is_exported(self):
        history = {
            "currentId": "m3",
            "messages": {
                "m1": message("user", "q1", 100),
                "m2": message("assistant", "superseded", 110, "m1"),
                "m3": message("assistant", "regenerated", 130, "m1"),
            },
        }
        chat = FakeChat("c2", "Session", {"history": history})
        assert [m["content"] for m in _linear_messages(chat)] == ["q1", "regenerated"]

    def test_unusable_current_id_falls_back_to_every_message(self):
        history = {
            "currentId": "missing",
            "messages": {
                "m2": message("assistant", "a1", 110, "m1"),
                "m1": message("user", "q1", 100),
            },
        }
        chat = FakeChat("c3", "Session", {"history": history})
        assert [m["content"] for m in _linear_messages(chat)] == ["q1", "a1"]

    def test_legacy_chat_without_history_uses_the_flat_list(self):
        chat = FakeChat("c4", "Session", {"messages": [message("user", "legacy", 5)]})
        assert [m["content"] for m in _linear_messages(chat)] == ["legacy"]

    def test_empty_chat_yields_no_messages(self):
        assert _linear_messages(FakeChat("c5", "Session", {})) == []

    def test_cyclic_parent_chain_terminates(self):
        history = {
            "currentId": "m2",
            "messages": {
                "m1": message("user", "q1", 1, "m2"),
                "m2": message("assistant", "a1", 2, "m1"),
            },
        }
        chat = FakeChat("c6", "Session", {"history": history})
        assert [m["content"] for m in _linear_messages(chat)] == ["q1", "a1"]


def merge(chats):
    """The session merge from export_chats_as_zip, kept in step with the router."""
    sessions = []
    for chat in chats:
        messages = _linear_messages(chat)
        started_at = _session_start(messages, chat)
        sessions.append((started_at, chat, messages))
    sessions.sort(key=lambda session: (session[0], session[1].created_at or 0))

    merged = []
    for started_at, chat, messages in sessions:
        if len(sessions) > 1:
            merged.append(
                {
                    "role": "system",
                    "content": f"--- Chat Session: {chat.title} ---",
                    "timestamp": started_at,
                }
            )
        if not messages:
            merged.append(
                {
                    "role": "system",
                    "content": f"_(No messages stored for chat session: {chat.title})_",
                    "timestamp": started_at,
                }
            )
        merged.extend(messages)
    return merged


class TestSessionMerge:
    def test_overlapping_sessions_stay_contiguous(self):
        """
        Sorting the merged list by timestamp interleaves sessions that overlap in
        time, which files the later turns of one chat under the header of
        another and reads as a missing conversation.
        """
        a = FakeChat(
            "a",
            "Session A",
            {
                "messages": [
                    message("user", "A-q1", 100),
                    message("assistant", "A-a1", 110),
                    message("user", "A-q2", 300),
                    message("assistant", "A-a2", 310),
                ]
            },
        )
        b = FakeChat(
            "b",
            "Session B",
            {
                "messages": [
                    message("user", "B-q1", 200),
                    message("assistant", "B-a1", 210),
                ]
            },
        )

        assert [m["content"] for m in merge([a, b])] == [
            "--- Chat Session: Session A ---",
            "A-q1",
            "A-a1",
            "A-q2",
            "A-a2",
            "--- Chat Session: Session B ---",
            "B-q1",
            "B-a1",
        ]

    def test_every_selected_chat_is_represented(self):
        a = FakeChat("a", "Session A", {"messages": [message("user", "A-q1", 100)]})
        empty = FakeChat("e", "Session Empty", {"messages": []}, created_at=250)

        contents = [m["content"] for m in merge([a, empty])]
        assert "--- Chat Session: Session Empty ---" in contents
        assert "_(No messages stored for chat session: Session Empty)_" in contents

    def test_a_lone_session_gets_no_header(self):
        a = FakeChat("a", "Session A", {"messages": [message("user", "A-q1", 100)]})
        assert [m["content"] for m in merge([a])] == ["A-q1"]

    def test_regenerated_reply_stays_with_its_question(self):
        """
        Regeneration hangs a new reply off the same user message. It carries the
        time it was regenerated, or none at all when the backend wrote it, so
        ordering a session by timestamp files the answer away from its question.
        The parent chain is the order the user saw and must survive intact.
        """
        history = {
            "currentId": "a2b",
            "messages": {
                "q1": {"role": "user", "content": "Q1", "timestamp": 100},
                "a1": {"role": "assistant", "content": "A1", "timestamp": 110, "parentId": "q1"},
                "q2": {"role": "user", "content": "Q2", "timestamp": 200, "parentId": "a1"},
                "a2": {"role": "assistant", "content": "A2 old", "timestamp": 210, "parentId": "q2"},
                # Persisted by the backend: model and content, but no timestamp.
                "a2b": {"role": "assistant", "content": "A2 new", "parentId": "q2"},
            },
        }
        chat = FakeChat("c", "Session", {"history": history})

        assert [m["content"] for m in merge([chat])] == ["Q1", "A1", "Q2", "A2 new"]

    def test_a_late_regenerated_reply_is_not_moved_to_the_end(self):
        # The reply to Q1 was regenerated after the rest of the chat already
        # existed, so it carries a timestamp later than every message that
        # follows it in the conversation.
        history = {
            "currentId": "a2",
            "messages": {
                "q1": {"role": "user", "content": "Q1", "timestamp": 100},
                "a1b": {"role": "assistant", "content": "A1 new", "timestamp": 9999, "parentId": "q1"},
                "q2": {"role": "user", "content": "Q2", "timestamp": 200, "parentId": "a1b"},
                "a2": {"role": "assistant", "content": "A2", "timestamp": 210, "parentId": "q2"},
            },
        }
        chat = FakeChat("c", "Session", {"history": history})

        assert [m["content"] for m in merge([chat])] == ["Q1", "A1 new", "Q2", "A2"]

    def test_session_without_timestamps_does_not_jump_the_export(self):
        """A session start of 0 would drag it above every dated session."""
        early = FakeChat(
            "early", "Early", {"messages": [message("user", "early", 100)]}
        )
        undated = FakeChat(
            "undated",
            "Undated",
            {"messages": [{"role": "user", "content": "undated"}]},
            created_at=500,
        )

        contents = [m["content"] for m in merge([undated, early])]
        assert contents.index("early") < contents.index("undated")

    def test_missing_timestamps_do_not_abort_the_merge(self):
        a = FakeChat("a", "Session A", {"messages": [message("user", "A-q1", 100)]})
        b = FakeChat(
            "b", "Session B", {"messages": [{"role": "user", "content": "B-q1"}]}
        )

        contents = [m["content"] for m in merge([a, b])]
        assert "A-q1" in contents
        assert "B-q1" in contents
