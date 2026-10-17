import pytest

from aei import data


@pytest.fixture(scope="session")
def ds():
    return data.load()
