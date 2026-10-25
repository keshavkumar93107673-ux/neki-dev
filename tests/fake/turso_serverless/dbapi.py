class Error(Exception): pass
class DatabaseError(Error): pass
class IntegrityError(DatabaseError): pass
class OperationalError(DatabaseError): pass
class ProgrammingError(DatabaseError): pass
