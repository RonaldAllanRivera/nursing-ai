"""The Postgres image is pinned to one exact tag."""

import re

from conftest import compose_db_image


def test_db_image_is_an_exact_pgvector_pg17_tag() -> None:
    assert re.fullmatch(r"pgvector/pgvector:\d+\.\d+\.\d+-pg17-bookworm", compose_db_image())
