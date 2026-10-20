"""Oracle connectivity and synthetic fixture seeding."""
import json
import os
from pathlib import Path
import oracledb
from dotenv import load_dotenv

load_dotenv()

def connect():
    return oracledb.connect(user=os.environ['DB_USER'], password=os.environ['DB_PASSWORD'], dsn=os.environ['DB_DSN'])

def seed_fixtures():
    path = Path(__file__).resolve().parents[1] / 'fixtures' / 'tickets.json'
    tickets = json.loads(path.read_text())
    with connect() as connection:
        with connection.cursor() as cursor:
            for ticket in tickets:
                cursor.execute('''MERGE INTO support_tickets t USING
                    (SELECT :ticket_id AS ticket_id FROM dual) s
                    ON (t.ticket_id=s.ticket_id)
                    WHEN NOT MATCHED THEN INSERT
                    (ticket_id,tenant_id,customer_id,title,description,status)
                    VALUES (:ticket_id,:tenant_id,:customer_id,:title,:description,:status)''', ticket)
        connection.commit()
    print(f'Seeded {len(tickets)} synthetic tickets (existing IDs unchanged).')

if __name__ == '__main__':
    seed_fixtures()
