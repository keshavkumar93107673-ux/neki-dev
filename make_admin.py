
import database

EMAIL = input("Enter Keshav's registered email: ").strip().lower()

conn = database.get_connection()

try:
    user = conn.execute(
        "SELECT id, name, email, role FROM users WHERE lower(email) = ?",
        (EMAIL,)
    ).fetchone()

    if not user:
        print("No account found with that email.")
    else:
        conn.execute(
            "UPDATE users SET role = 'Admin' WHERE id = ?",
            (user["id"],)
        )
        conn.commit()

        updated = conn.execute(
            "SELECT name, email, role FROM users WHERE id = ?",
            (user["id"],)
        ).fetchone()

        print("Updated account:")
        print("Name:", updated["name"])
        print("Email:", updated["email"])
        print("Role:", updated["role"])
finally:
    conn.close()
