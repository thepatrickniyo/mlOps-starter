from datetime import timedelta

from app import app, get_db


class FakeResult:
    def fetchone(self):
        return (timedelta(seconds=4.2),)


class FakeSession:
    async def execute(self, *_args, **_kwargs):
        return FakeResult()


async def fake_get_db():
    yield FakeSession()


app.dependency_overrides[get_db] = fake_get_db
