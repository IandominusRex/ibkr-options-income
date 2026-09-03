"""The symbol-directory provider follows the existing src/data Protocol pattern."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from src.data.protocols import SymbolDirectoryProvider, SymbolRecord


def test_symbol_record_shape() -> None:
    r = SymbolRecord(symbol="AAPL", cik="0000320193", name="Apple Inc.", exchange="Nasdaq")
    assert r.symbol == "AAPL"
    assert r.cik == "0000320193"


def test_a_stub_satisfies_the_protocol_structurally() -> None:
    class Stub:
        def list_symbols(self) -> list[SymbolRecord]:
            return [SymbolRecord(symbol="AAPL", cik="0000320193", name="Apple Inc.")]

    assert isinstance(Stub(), SymbolDirectoryProvider)


def test_symbol_record_is_a_pydantic_model() -> None:
    assert issubclass(SymbolRecord, BaseModel)


def test_factory_rejects_an_unknown_backend() -> None:
    from src.data.factory import _make_symbol_directory_provider

    with pytest.raises(ValueError, match="Unknown data.symbol_directory_provider"):
        _make_symbol_directory_provider("nope")
