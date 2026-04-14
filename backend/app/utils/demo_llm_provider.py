import json
import os
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("murmuroscope.demo")

class DemoLLMClient:
    """A deterministic stub client for Demo Mode.
    
    Reads pre-baked responses from JSON fixtures based on prompt routing.
    """
    
    def __init__(self, fixture_dir: str = "backend/fixtures/demo"):
        self.fixture_dir = Path(fixture_dir)
        self._cache = {}

    def _load_fixture(self, name: str) -> Optional[Dict[str, Any]]:
        if name in self._cache:
            return self._cache[name]
        
        path = self.fixture_dir / f"{name}.json"
        if not path.exists():
            logger.warning("Demo fixture not found: %s", path)
            return None
            
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self._cache[name] = data
                return data
        except Exception as e:
            logger.error("Failed to load demo fixture %s: %s", name, e)
            return None

    async def generate_response(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Route prompt to appropriate fixture and return a response."""
        p_lower = prompt.lower()
        
        # Routing logic based on common patterns in MurmuraScope
        if "entity" in p_lower or "extraction" in p_lower:
            fixture = self._load_fixture("entity_extraction")
            return json.dumps(fixture) if fixture else "[]"
        
        if "agent" in p_lower and ("profile" in p_lower or "identity" in p_lower):
            fixture = self._load_fixture("agent_profiles")
            return json.dumps(fixture) if fixture else "{}"

        if "deliberation" in p_lower or "debate" in p_lower:
            fixture = self._load_fixture("deliberation")
            return fixture.get("text", "No response") if fixture else "Sample deliberation"

        if "report" in p_lower or "summary" in p_lower:
            fixture = self._load_fixture("report_sections")
            return fixture.get("text", "No response") if fixture else "Sample report section"

        # Default fallback
        return "Demo mode response: LLM interaction is simulated."

    async def chat_completion(self, messages: list, **kwargs) -> Any:
        """Compatibility method for standard LLM client interface."""
        prompt = messages[-1]["content"] if messages else ""
        text = await self.generate_response(prompt)
        
        # Mocking an OpenAI-like response object if needed by callers
        class MockResponse:
            def __init__(self, content):
                self.choices = [type('Choice', (), {'message': type('Message', (), {'content': content})})]
        
        return MockResponse(text)

_demo_client = None

def get_demo_client() -> DemoLLMClient:
    global _demo_client
    if _demo_client is None:
        _demo_client = DemoLLMClient()
    return _demo_client
