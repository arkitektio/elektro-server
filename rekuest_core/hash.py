from .inputs.models import DefinitionInputModel
import hashlib
import json


def hash_definition(definition: DefinitionInputModel) -> str:
    """Hash a definition"""
    hash = hashlib.sha256(
        json.dumps(definition.dict(), sort_keys=True).encode()
    ).hexdigest()
    return hash
