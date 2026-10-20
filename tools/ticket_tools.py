"""SQLite demo store; Oracle store uses the same executor contract later."""
import sqlite3
from pathlib import Path

class SQLiteTicketStore:
    def __init__(self, path: str = ':memory:'):
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute('''CREATE TABLE IF NOT EXISTS tickets (
            ticket_id INTEGER PRIMARY KEY, tenant_id INTEGER NOT NULL,
            customer_id INTEGER NOT NULL, title TEXT NOT NULL,
            description TEXT, status TEXT NOT NULL
        )''')
        self.connection.commit()

    def seed(self, tickets: list[dict]):
        self.connection.executemany(
            'INSERT INTO tickets(ticket_id, tenant_id, customer_id, title, description, status) VALUES(:ticket_id,:tenant_id,:customer_id,:title,:description,:status)', tickets)
        self.connection.commit()

    def get_ticket(self, ticket_id: int):
        row = self.connection.execute('SELECT * FROM tickets WHERE ticket_id=?', (ticket_id,)).fetchone()
        return dict(row) if row else None

    def update_status(self, ticket_id: int, tenant_id: int, status: str):
        cursor = self.connection.execute('UPDATE tickets SET status=? WHERE ticket_id=? AND tenant_id=?', (status, ticket_id, tenant_id))
        self.connection.commit()
        return cursor.rowcount

    def delete_ticket(self, ticket_id: int, tenant_id: int):
        cursor = self.connection.execute('DELETE FROM tickets WHERE ticket_id=? AND tenant_id=?', (ticket_id, tenant_id))
        self.connection.commit()
        return cursor.rowcount
