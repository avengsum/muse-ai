import json

from .models import MessageArtifact


def artifact_data(database, message_id: int):
    artifact = database.get(MessageArtifact, message_id)
    if artifact is None:
        return None
    try:
        return json.loads(artifact.data_json)
    except json.JSONDecodeError:
        return None


def schedule_artifact(database, message_id: int):
    artifact = database.get(MessageArtifact, message_id)
    if artifact is None or artifact.kind != "schedule_confirmation":
        return None
    return artifact_data(database, message_id)
