import pytest

from aei import config as C
from aei import data


@pytest.fixture(scope="session")
def ds():
    if not (C.DATA_DIR / "isolates.csv").is_file():
        pytest.skip(f"no dataset in {C.DATA_DIR}: put the 6 CSVs in data/ or set AEI_DATA_DIR")
    return data.load()
