"""Apply ARI's narrow Letta 0.9.1 SQLite/SQLAlchemy compatibility fixes.

Agent creation flushes a row with server-default timestamps and immediately
serializes it.  Current SQLAlchemy expires those defaults; serialization then
performs forbidden implicit async IO and raises ``MissingGreenlet``.  An
explicit async refresh keeps the exact transaction while loading the defaults
through the supported awaitable path.
"""

from __future__ import annotations

import importlib.metadata
import inspect
from pathlib import Path


def main() -> int:
    if importlib.metadata.version("letta") != "0.9.1":
        raise RuntimeError("compatibility patch is valid only for letta==0.9.1")

    from letta.services import agent_manager

    path = Path(inspect.getsourcefile(agent_manager) or "")
    if not path.is_file():
        raise RuntimeError("cannot locate Letta agent_manager.py")
    source = path.read_text(encoding="utf-8")
    marker = "# ARI compatibility: load server defaults before async serialization."
    if marker in source:
        pass
    else:
        before = """                session.add(new_agent)\n                await session.flush()\n                aid = new_agent.id\n"""
        after = """                session.add(new_agent)\n                await session.flush()\n                # ARI compatibility: load server defaults before async serialization.\n                await session.refresh(new_agent)\n                aid = new_agent.id\n"""
        if source.count(before) != 1:
            raise RuntimeError(
                "Letta agent creation source differs from the reviewed 0.9.1 layout"
            )
        path.write_text(source.replace(before, after), encoding="utf-8")

    # RHEL 9 ships SQLite 3.34, one release before UPDATE ... RETURNING.  Letta
    # comments that it has an older-SQLite fallback, but the syntax error is
    # raised before its ``result is None`` branch.  Reserve sequence numbers in
    # the surrounding transaction using portable SELECT then UPDATE instead.
    from letta.orm import message

    message_path = Path(inspect.getsourcefile(message) or "")
    message_source = message_path.read_text(encoding="utf-8")
    sequence_marker = "# ARI compatibility: SQLite <3.35 has no RETURNING."
    replacements = (
        (
            """            # Atomically reserve a range of sequence values for this batch\n            result = session.execute(\n                text(\n                    \"\"\"\n                UPDATE message_sequence\n                SET next_val = next_val + :count\n                WHERE id = 1\n                RETURNING next_val - :count\n            \"\"\"\n                ),\n                {\"count\": records_count},\n            )\n\n            start_sequence_id = result.scalar()\n            if start_sequence_id is None:\n                # Fallback if RETURNING doesn't work (older SQLite versions)\n                session.execute(\n                    text(\n                        \"\"\"\n                    UPDATE message_sequence\n                    SET next_val = next_val + :count\n                    WHERE id = 1\n                \"\"\"\n                    ),\n                    {\"count\": records_count},\n                )\n                start_sequence_id = session.execute(\n                    text(\n                        \"\"\"\n                    SELECT next_val - :count FROM message_sequence WHERE id = 1\n                \"\"\"\n                    ),\n                    {\"count\": records_count},\n                ).scalar()\n""",
            """            # ARI compatibility: SQLite <3.35 has no RETURNING.\n            start_sequence_id = session.execute(\n                text(\"SELECT next_val FROM message_sequence WHERE id = 1\")\n            ).scalar()\n            session.execute(\n                text(\"UPDATE message_sequence SET next_val = next_val + :count WHERE id = 1\"),\n                {\"count\": records_count},\n            )\n""",
        ),
        (
            """        # Atomically get the next sequence value\n        result = connection.execute(\n            text(\n                \"\"\"\n            UPDATE message_sequence\n            SET next_val = next_val + 1\n            WHERE id = 1\n            RETURNING next_val - 1\n        \"\"\"\n            )\n        )\n\n        sequence_id = result.scalar()\n        if sequence_id is None:\n            # Fallback if RETURNING doesn't work (older SQLite versions)\n            connection.execute(\n                text(\n                    \"\"\"\n                UPDATE message_sequence\n                SET next_val = next_val + 1\n                WHERE id = 1\n            \"\"\"\n                )\n            )\n            sequence_id = connection.execute(\n                text(\n                    \"\"\"\n                SELECT next_val - 1 FROM message_sequence WHERE id = 1\n            \"\"\"\n                )\n            ).scalar()\n""",
            """        # ARI compatibility: SQLite <3.35 has no RETURNING.\n        sequence_id = connection.execute(\n            text(\"SELECT next_val FROM message_sequence WHERE id = 1\")\n        ).scalar()\n        connection.execute(\n            text(\"UPDATE message_sequence SET next_val = next_val + 1 WHERE id = 1\")\n        )\n""",
        ),
    )
    if sequence_marker not in message_source:
        for before, after in replacements:
            if message_source.count(before) != 1:
                raise RuntimeError(
                    "Letta message sequence source differs from the reviewed 0.9.1 layout"
                )
            message_source = message_source.replace(before, after)
        message_path.write_text(message_source, encoding="utf-8")

    # MessageManager asks batch_create_async not to re-query flushed messages,
    # then immediately serializes server-default ``updated_at``.  Re-querying
    # is the existing supported branch and prevents the second MissingGreenlet.
    from letta.services import message_manager

    manager_path = Path(inspect.getsourcefile(message_manager) or "")
    manager_source = manager_path.read_text(encoding="utf-8")
    before = (
        "created_messages = await MessageModel.batch_create_async(orm_messages, "
        "session, actor=actor, no_commit=True, no_refresh=True)"
    )
    after = (
        "created_messages = await MessageModel.batch_create_async(orm_messages, "
        "session, actor=actor, no_commit=True, no_refresh=False)"
        "  # ARI compatibility: load server-default timestamps"
    )
    if after not in manager_source:
        if manager_source.count(before) != 1:
            raise RuntimeError(
                "Letta message manager source differs from the reviewed 0.9.1 layout"
            )
        manager_path.write_text(
            manager_source.replace(before, after), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
