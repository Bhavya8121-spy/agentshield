"""Oracle-backed ticket operations. Mutations always filter by tenant."""
from database.oracle import connect


class OracleTicketStore:
    def __init__(self, connection=None, commit_mutations=True):
        self.connection = connection if connection is not None else connect()
        self.owns_connection = connection is None
        self.commit_mutations = commit_mutations

    def close(self):
        if self.owns_connection:
            self.connection.close()

    def get_ticket(self, ticket_id):
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT ticket_id, tenant_id, customer_id, title, description, status "
                "FROM support_tickets WHERE ticket_id = :id", {"id": ticket_id}
            )
            row = cursor.fetchone()
            if row is None:
                return None
            description = row[4]
            if hasattr(description, 'read'):
                description = description.read()
            return dict(zip(
                ('ticket_id', 'tenant_id', 'customer_id', 'title', 'description', 'status'),
                (int(row[0]), int(row[1]), int(row[2]), row[3], description, row[5])
            ))

    def update_status(self, ticket_id, tenant_id, status):
        with self.connection.cursor() as cursor:
            cursor.execute(
                'UPDATE support_tickets SET status=:status '
                'WHERE ticket_id=:ticket_id AND tenant_id=:tenant_id',
                {'status': status, 'ticket_id': ticket_id, 'tenant_id': tenant_id}
            )
            count = cursor.rowcount
        if self.commit_mutations:
            self.connection.commit()
        return count

    def delete_ticket(self, ticket_id, tenant_id):
        with self.connection.cursor() as cursor:
            cursor.execute(
                'DELETE FROM support_tickets WHERE ticket_id=:ticket_id AND tenant_id=:tenant_id',
                {'ticket_id': ticket_id, 'tenant_id': tenant_id}
            )
            count = cursor.rowcount
        if self.commit_mutations:
            self.connection.commit()
        return count
