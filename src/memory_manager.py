import json
from typing import List, Dict

class MemoryManager:
    def __init__(self):
        self.memory: List[Dict[str, str]] = []

    def add_interaction(self, user_input: str, assistant_response: str):
        self.memory.append({
            "user": user_input,
            "assistant": assistant_response
        })

    def get_memory(self) -> str:
        return json.dumps(self.memory, indent=2)
