from unittest.mock import MagicMock

from app.db import insert_rows_batched


def _mock_connection():
    conn = MagicMock()
    cursor = MagicMock()
    # conn.cursor() as cur: -- MagicMock's context-manager protocol needs
    # __enter__/__exit__ wired explicitly since conn.cursor() itself is
    # just another MagicMock call, not a real contextmanager.
    conn.cursor.return_value.__enter__.return_value = cursor
    return conn, cursor


def test_insert_rows_batched_is_a_noop_for_no_rows():
    conn, cursor = _mock_connection()
    insert_rows_batched(conn, 'ratings', ['medium', 'station'], [])
    cursor.execute.assert_not_called()


def test_insert_rows_batched_sends_one_statement_when_under_batch_size():
    conn, cursor = _mock_connection()
    rows = [('TV', 'TVC'), ('TV', 'AIT')]
    insert_rows_batched(conn, 'ratings', ['medium', 'station'], rows, batch_size=1000)

    cursor.execute.assert_called_once()
    sql, params = cursor.execute.call_args[0]
    assert sql == 'INSERT INTO ratings (medium, station) VALUES (%s, %s), (%s, %s)'
    assert params == ['TV', 'TVC', 'TV', 'AIT']


def test_insert_rows_batched_splits_into_multiple_statements_above_batch_size():
    conn, cursor = _mock_connection()
    rows = [('TV', f'Station {i}') for i in range(2500)]
    insert_rows_batched(conn, 'ratings', ['medium', 'station'], rows, batch_size=1000)

    # 2500 rows at 1000/batch -> 3 statements (1000, 1000, 500), not 2500
    # round trips -- the whole point of this helper.
    assert cursor.execute.call_count == 3
    sizes = [len(call.args[1]) for call in cursor.execute.call_args_list]
    assert sizes == [2000, 2000, 1000]  # params per batch = rows_in_batch * 2 columns

    all_params = [value for call in cursor.execute.call_args_list for value in call.args[1]]
    assert all_params == [value for row in rows for value in row]


def test_insert_rows_batched_keeps_row_order_across_batch_boundaries():
    conn, cursor = _mock_connection()
    rows = [(i,) for i in range(1001)]  # one past a single batch at batch_size=1000
    insert_rows_batched(conn, 'ratings', ['week'], rows, batch_size=1000)

    first_batch_params = cursor.execute.call_args_list[0].args[1]
    second_batch_params = cursor.execute.call_args_list[1].args[1]
    assert first_batch_params == list(range(1000))
    assert second_batch_params == [1000]
