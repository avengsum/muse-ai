import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import memory_service
from app.database import Base
from app.models import UserMemory


class MemoryServiceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    def run_extractor(self, content, messages):
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )
        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=AsyncMock(return_value=response))
            ),
            close=AsyncMock(),
        )
        with (
            patch.object(memory_service, "SessionLocal", self.session_factory),
            patch.object(memory_service, "create_llm_client", return_value=client),
            patch.object(memory_service, "get_llm_model_name", return_value="gemini-test"),
            patch.object(memory_service, "get_llm_provider", return_value="gemini"),
        ):
            asyncio.run(
                memory_service.extract_and_persist_memories("user-1", messages)
            )
        return client

    def test_saves_and_deduplicates_gemini_memories(self):
        response = json.dumps(
            {
                "has_memories": True,
                "memories": [
                    {
                        "category": "dietary",
                        "fact": "Prefers vegetarian food",
                        "action": "add",
                        "importance": 5,
                    }
                ],
            }
        )
        messages = [{"role": "user", "content": "I prefer vegetarian food."}]

        client = self.run_extractor(response, messages)
        self.run_extractor(response, messages)

        request = client.chat.completions.create.await_args.kwargs
        self.assertEqual(
            request["response_format"]["type"],
            "json_schema",
        )
        self.assertTrue(request["response_format"]["json_schema"]["strict"])

        with self.session_factory() as database:
            memories = database.scalars(select(UserMemory)).all()

        self.assertEqual(len(memories), 1)
        self.assertEqual(memories[0].importance, 5)

    def test_updates_and_deactivates_superseded_fact(self):
        self.run_extractor(
            json.dumps(
                {
                    "has_memories": True,
                    "memories": [
                        {
                            "category": "location",
                            "fact": "Lives in Indiranagar",
                            "action": "add",
                        }
                    ],
                }
            ),
            [{"role": "user", "content": "I live in Indiranagar."}],
        )
        self.run_extractor(
            json.dumps(
                {
                    "has_memories": True,
                    "memories": [
                        {
                            "category": "location",
                            "fact": "Lives in Koramangala",
                            "action": "update",
                            "supersedes": "Indiranagar",
                        }
                    ],
                }
            ),
            [{"role": "user", "content": "I moved to Koramangala."}],
        )

        with self.session_factory() as database:
            memories = database.scalars(
                select(UserMemory).order_by(UserMemory.id)
            ).all()

        self.assertEqual(len(memories), 2)
        self.assertFalse(memories[0].is_active)
        self.assertTrue(memories[1].is_active)


if __name__ == "__main__":
    unittest.main()
