"""Disposable SQLite mailbox store for the email-assistant demo."""
import sqlite3


class SQLiteEmailStore:
    def __init__(self, path: str = ':memory:'):
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute('''CREATE TABLE IF NOT EXISTS emails (
            email_id INTEGER PRIMARY KEY, tenant_id INTEGER NOT NULL,
            sender TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL)''')
        self.connection.execute('''CREATE TABLE IF NOT EXISTS sent (
            sent_id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id INTEGER NOT NULL,
            recipient TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL)''')
        self.connection.commit()

    def seed(self, emails):
        self.connection.executemany(
            'INSERT INTO emails(email_id, tenant_id, sender, subject, body) '
            'VALUES(:email_id,:tenant_id,:sender,:subject,:body)', emails)
        self.connection.commit()

    def get_email(self, email_id: int):
        row = self.connection.execute('SELECT * FROM emails WHERE email_id=?', (email_id,)).fetchone()
        return dict(row) if row else None

    def delete_email(self, email_id: int, tenant_id: int):
        cur = self.connection.execute('DELETE FROM emails WHERE email_id=? AND tenant_id=?', (email_id, tenant_id))
        self.connection.commit()
        return cur.rowcount

    def send_email(self, tenant_id: int, recipient: str, subject: str, body: str):
        cur = self.connection.execute(
            'INSERT INTO sent(tenant_id, recipient, subject, body) VALUES(?,?,?,?)',
            (tenant_id, recipient, subject, body))
        self.connection.commit()
        return cur.lastrowid
