"""Read persisted chat attachments without mistaking message or KB IDs for files."""

from urllib.parse import unquote, urlsplit

from open_webui.models.files import File


def chat_file_ids(payload) -> set[str]:
    if not isinstance(payload, dict):
        return set()

    ids = set()
    containers = [payload]
    messages = payload.get("messages")
    if isinstance(messages, list):
        containers.extend(messages)
    history = payload.get("history")
    if isinstance(history, dict):
        messages = history.get("messages")
        if isinstance(messages, dict):
            # Include branches that are absent from the visible message list.
            containers.extend(messages.values())
        elif isinstance(messages, list):
            containers.extend(messages)

    for container in containers:
        attachments = container.get("files") if isinstance(container, dict) else None
        if not isinstance(attachments, list):
            continue
        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            if attachment.get("type") in (
                "collection", "web_search", "text", "web", "youtube"
            ):
                # Some collection descriptors persist a snapshot of their files.
                data = attachment.get("data")
                values = data.get("file_ids") if isinstance(data, dict) else None
                if isinstance(values, list):
                    ids.update(value for value in values if isinstance(value, str) and value)
                continue
            file_id = attachment.get("id") or attachment.get("file_id")
            if isinstance(file_id, str) and file_id:
                ids.add(file_id)
            collection = attachment.get("collection_name")
            if isinstance(collection, str) and collection.startswith("file-"):
                ids.add(collection[5:])
            url = attachment.get("url")
            if isinstance(url, str) and "/api/v1/files/" in url:
                path = urlsplit(url).path
                file_id = path.split("/api/v1/files/", 1)[-1].split("/", 1)[0]
                if file_id:
                    ids.add(unquote(file_id))
    return ids


def lock_chat_files(db, payload, previous=None) -> set[str]:
    """Serialize new chat references with orphan deletion using File-first locks."""
    requested_ids = chat_file_ids(payload)
    if not requested_ids:
        return set()
    rows = (
        db.query(File.id)
        .filter(File.id.in_(sorted(requested_ids)))
        .order_by(File.id)
        .with_for_update()
        .all()
    )
    missing = requested_ids - {row.id for row in rows}
    # Existing chats may retain references to an explicitly deleted file.
    if missing - chat_file_ids(previous):
        raise ValueError("A chat attachment no longer exists")
    return missing
