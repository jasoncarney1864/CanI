"""Whitelist validation for list_documents' sort/order params (docs/21 §1.3). These raise
before touching the connection, so no database is needed — docs-api maps the ValueError to
a 400 (§1.2)."""

import pytest
from cani_shared.db.repositories import list_documents


def test_invalid_sort_rejected():
    with pytest.raises(ValueError, match="invalid sort"):
        list_documents(None, "owner-1", sort="not_a_column")


def test_invalid_order_rejected():
    with pytest.raises(ValueError, match="invalid order"):
        list_documents(None, "owner-1", order="sideways")


def test_valid_sort_and_order_do_not_raise_before_touching_the_connection():
    # A bogus but valid-shaped sort/order must pass validation and only fail once it
    # actually needs a connection — proves validation happens first, not that it's skipped.
    with pytest.raises(AttributeError):
        list_documents(None, "owner-1", sort="title", order="asc")
