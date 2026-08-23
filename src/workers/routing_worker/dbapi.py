"""Small injected DB-API surface with explicit transaction ownership."""

from __future__ import annotations

from typing import Any, Callable, Protocol, TypeVar


class Cursor(Protocol):
    rowcount: int

    def execute(self, operation: str, parameters: tuple[Any, ...] = ()) -> Any: ...

    def fetchone(self) -> tuple[Any, ...] | None: ...

    def fetchall(self) -> list[tuple[Any, ...]]: ...

    def close(self) -> None: ...


class Connection(Protocol):
    def cursor(self) -> Cursor: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def close(self) -> None: ...


ConnectionFactory = Callable[[], Connection]
T = TypeVar("T")


class TransactionError(RuntimeError):
    pass


def transactional(factory: ConnectionFactory, operation: Callable[[Cursor], T]) -> T:
    """Run one serializable transaction and roll back every exceptional path."""

    connection = factory()
    cursor = connection.cursor()
    try:
        cursor.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        result = operation(cursor)
        connection.commit()
        return result
    except BaseException:
        connection.rollback()
        raise
    finally:
        try:
            cursor.close()
        finally:
            connection.close()


def read_only(factory: ConnectionFactory, operation: Callable[[Cursor], T]) -> T:
    """Run a read transaction and always roll it back to release the snapshot."""

    connection = factory()
    cursor = connection.cursor()
    try:
        cursor.execute("SET TRANSACTION READ ONLY")
        return operation(cursor)
    finally:
        try:
            connection.rollback()
        finally:
            try:
                cursor.close()
            finally:
                connection.close()
