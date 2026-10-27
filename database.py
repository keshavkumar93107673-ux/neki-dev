import sqlite3
import turso_compat
import bcrypt
import secrets
import hashlib
from datetime import datetime, timedelta


# =========================================================
# DATABASE CONFIGURATION
# =========================================================

DATABASE_NAME = "neighbourhelp.db"


# =========================================================
# DATABASE CONNECTION
# =========================================================

def get_connection():
    """
    Creates and returns a connection to the SQLite database.
    """
    # sqlite backend: identical to the original behaviour.
    # turso backend (opt-in via secrets): pooled, sqlite3-compatible wrapper.
    return turso_compat.connect(DATABASE_NAME)


# =========================================================
# CREATE TABLES
# =========================================================

def create_tables():

    connection = get_connection()
    cursor = connection.cursor()

    # -----------------------------------------------------
    # USERS
    # -----------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            location TEXT,
            role TEXT DEFAULT 'User',
            trust_score REAL DEFAULT 50,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            session_token_hash TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    
    # -----------------------------------------------------
    # PASSWORD RESET TOKENS
    # -----------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)


    # -----------------------------------------------------
    # HELP REQUESTS
    # -----------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS help_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            category TEXT NOT NULL,
            location TEXT NOT NULL,
            status TEXT DEFAULT 'Pending',
            helper_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (user_id)
                REFERENCES users(id),

            FOREIGN KEY (helper_id)
                REFERENCES users(id)
        )
    """)

    # -----------------------------------------------------
    # RATINGS
    # -----------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER NOT NULL,
            giver_id INTEGER NOT NULL,
            receiver_id INTEGER NOT NULL,
            rating INTEGER NOT NULL,
            review TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (request_id)
                REFERENCES help_requests(id),

            FOREIGN KEY (giver_id)
                REFERENCES users(id),

            FOREIGN KEY (receiver_id)
                REFERENCES users(id)
        )
    """)

    # -----------------------------------------------------
    # REPORTS
    # -----------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reporter_id INTEGER NOT NULL,
            reported_user_id INTEGER,
            request_id INTEGER,
            reason TEXT NOT NULL,
            status TEXT DEFAULT 'Open',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (reporter_id)
                REFERENCES users(id),

            FOREIGN KEY (reported_user_id)
                REFERENCES users(id),

            FOREIGN KEY (request_id)
                REFERENCES help_requests(id)
        )
    """)

    # -----------------------------------------------------
    # NOTIFICATIONS
    # -----------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            related_request_id INTEGER,
            is_read INTEGER DEFAULT 0,
            rating_is_read INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (user_id)
                REFERENCES users(id),

            FOREIGN KEY (related_request_id)
                REFERENCES help_requests(id)
        )
    """)

    # -----------------------------------------------------
    # USER SKILLS
    # -----------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_skills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            skill TEXT NOT NULL COLLATE NOCASE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
                ON DELETE CASCADE,
            UNIQUE (user_id, skill)
        )
    """)

    connection.commit()
    connection.close()


# =========================================================
# REGISTER USER
# =========================================================

def register_user(name, email, password, location, phone):
    """
    Creates a new user account.

    Returns:
        (True, "success message") if registration succeeds
        (False, "error message") if registration fails
    """

    connection = get_connection()
    cursor = connection.cursor()

    # Clean the email
    email = email.strip().lower()

    # Check if email already exists
    cursor.execute(
        "SELECT id FROM users WHERE email = ?",
        (email,)
    )

    existing_user = cursor.fetchone()

    if existing_user:
        connection.close()
        return False, "An account with this email already exists."

    # Hash password
    hashed_password = bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt()
    ).decode("utf-8")

    # Insert user
    cursor.execute("""
        INSERT INTO users
        (name, email, password, location, phone, email_verified, trust_score)
        VALUES (?, ?, ?, ?, ?, 0, 50.0)
    """, (
        name.strip(),
        email,
        hashed_password,
        location.strip(),
        phone.strip()
    ))

    user_id = cursor.lastrowid


    connection.commit()

    token = create_verification_token(user_id)

    connection.close()

    return True, token





# =========================================================
# CREATE EMAIL VERIFICATION TOKEN
# =========================================================

def create_verification_token(user_id):

    token = secrets.token_urlsafe(32)

    expires_at = datetime.utcnow() + timedelta(hours=24)

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE users
        SET verification_token = ?,
            verification_expires_at = ?
        WHERE id = ?
    """, (
        token,
        expires_at,
        user_id
    ))

    connection.commit()
    connection.close()

    return token


# =========================================================
# VERIFY EMAIL TOKEN
# =========================================================

def verify_email_token(token):

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT id
        FROM users
        WHERE verification_token = ?
        AND verification_expires_at > ?
        AND email_verified = 0
    """, (
        token,
        datetime.utcnow()
    ))

    user = cursor.fetchone()

    if not user:
        connection.close()
        return False

    cursor.execute("""
        UPDATE users
        SET email_verified = 1,
            verification_token = NULL,
            verification_expires_at = NULL
        WHERE id = ?
    """, (user["id"],))

    connection.commit()
    connection.close()

    return True        


# =========================================================
# CREATE PASSWORD RESET TOKEN
# =========================================================

def create_password_reset_token(email):
    email = email.strip().lower()
    now = datetime.utcnow()
    expires_at = now + timedelta(hours=1)

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT id
        FROM users
        WHERE LOWER(email) = ?
        AND email_verified = 1
        """,
        (email,)
    )

    user = cursor.fetchone()

    if not user:
        connection.close()
        return None

    user_id = user["id"]
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()

    try:
        cursor.execute("BEGIN IMMEDIATE")

        # Invalidate any previous unused reset links.
        cursor.execute(
            """
            UPDATE password_reset_tokens
            SET used_at = ?
            WHERE user_id = ?
            AND used_at IS NULL
            """,
            (now.isoformat(), user_id)
        )

        cursor.execute(
            """
            INSERT INTO password_reset_tokens
                (user_id, token_hash, created_at, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                user_id,
                token_hash,
                now.isoformat(),
                expires_at.isoformat()
            )
        )

        connection.commit()
        return token

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


# =========================================================
# RESET PASSWORD USING A VALID TOKEN
# =========================================================

def reset_password_with_token(token, new_password):
    if not token or not new_password:
        return False

    token_hash = hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()

    now = datetime.utcnow().isoformat()

    connection = get_connection()
    cursor = connection.cursor()

    try:
        # Serializes competing reset attempts so a token
        # cannot successfully reset two passwords.
        cursor.execute("BEGIN IMMEDIATE")

        cursor.execute(
            """
            SELECT id, user_id
            FROM password_reset_tokens
            WHERE token_hash = ?
            AND expires_at > ?
            AND used_at IS NULL
            """,
            (token_hash, now)
        )

        reset_record = cursor.fetchone()

        if not reset_record:
            connection.rollback()
            return False

        hashed_password = bcrypt.hashpw(
            new_password.encode("utf-8"),
            bcrypt.gensalt()
        ).decode("utf-8")

        cursor.execute(
            """
            UPDATE users
            SET password = ?
            WHERE id = ?
            """,
            (hashed_password, reset_record["user_id"])
        )

        if cursor.rowcount != 1:
            connection.rollback()
            return False

        cursor.execute(
            """
            UPDATE password_reset_tokens
            SET used_at = ?
            WHERE id = ?
            AND used_at IS NULL
            AND expires_at > ?
            """,
            (now, reset_record["id"], now)
        )

        if cursor.rowcount != 1:
            connection.rollback()
            return False

        # Revoke existing sessions after a password change.
        cursor.execute(
            """
            DELETE FROM user_sessions
            WHERE user_id = ?
            """,
            (reset_record["user_id"],)
        )

        connection.commit()
        return True

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()



def is_password_reset_token_valid(token):
    """Check whether a reset token exists, is unused, and has not expired."""
    if not token:
        return False

    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = datetime.utcnow().isoformat()

    connection = get_connection()

    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT 1
            FROM password_reset_tokens
            WHERE token_hash = ?
            AND expires_at > ?
            AND used_at IS NULL
            LIMIT 1
            """,
            (token_hash, now),
        )
        return cursor.fetchone() is not None
    finally:
        connection.close()

# =========================================================
# PHONE VERIFICATION
# =========================================================

def create_phone_otp(user_id, phone):
    """
    Stores a new phone number and creates a 6-digit OTP.

    The OTP itself is never stored in the database.
    Only its bcrypt hash is stored.
    """

    otp = str(secrets.randbelow(900000) + 100000)

    otp_hash = bcrypt.hashpw(
        otp.encode("utf-8"),
        bcrypt.gensalt()
    ).decode("utf-8")

    expires_at = datetime.utcnow() + timedelta(minutes=10)

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE users
        SET phone = ?,
            phone_verified = 0,
            phone_otp_hash = ?,
            phone_otp_expires_at = ?,
            phone_otp_attempts = 0
        WHERE id = ?
    """, (
        phone.strip(),
        otp_hash,
        expires_at,
        user_id
    ))

    connection.commit()
    connection.close()

    return otp


def verify_phone_otp(user_id, otp):
    """
    Verifies the phone OTP.

    OTP:
        - expires after 10 minutes
        - allows a maximum of 5 attempts
        - is deleted after successful verification
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            phone_otp_hash,
            phone_otp_expires_at,
            phone_otp_attempts
        FROM users
        WHERE id = ?
    """, (user_id,))

    user = cursor.fetchone()

    if not user:
        connection.close()
        return False, "User not found."

    if not user["phone_otp_hash"]:
        connection.close()
        return False, "Please request a new OTP."

    if user["phone_otp_attempts"] >= 5:
        connection.close()
        return False, "Too many incorrect attempts. Please request a new OTP."

    if not user["phone_otp_expires_at"]:
        connection.close()
        return False, "OTP has expired. Please request a new OTP."

    try:
        expires_at = datetime.fromisoformat(
            str(user["phone_otp_expires_at"])
        )
    except ValueError:
        connection.close()
        return False, "Invalid OTP information. Please request a new OTP."

    if datetime.utcnow() > expires_at:
        cursor.execute("""
            UPDATE users
            SET phone_otp_hash = NULL,
                phone_otp_expires_at = NULL,
                phone_otp_attempts = 0
            WHERE id = ?
        """, (user_id,))

        connection.commit()
        connection.close()

        return False, "OTP has expired. Please request a new OTP."

    try:
        otp_matches = bcrypt.checkpw(
            otp.strip().encode("utf-8"),
            user["phone_otp_hash"].encode("utf-8")
        )
    except (ValueError, TypeError):
        otp_matches = False

    if not otp_matches:

        cursor.execute("""
            UPDATE users
            SET phone_otp_attempts = phone_otp_attempts + 1
            WHERE id = ?
        """, (user_id,))

        connection.commit()
        connection.close()

        return False, "Incorrect OTP."

    cursor.execute("""
        UPDATE users
        SET phone_verified = 1,
            phone_otp_hash = NULL,
            phone_otp_expires_at = NULL,
            phone_otp_attempts = 0
        WHERE id = ?
    """, (user_id,))

    connection.commit()
    connection.close()

    return True, "Phone number verified successfully."


def get_phone_verification_status(user_id):
    """
    Returns the current phone and verification status.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            phone,
            phone_verified
        FROM users
        WHERE id = ?
    """, (user_id,))

    user = cursor.fetchone()

    connection.close()

    if not user:
        return None, False

    return (
        user["phone"],
        bool(user["phone_verified"])
    )


    
# =========================================================
# GET USER BY EMAIL
# =========================================================

def get_user_by_email(email):
    """
    Finds a user using their email address.
    """

    connection = get_connection()
    cursor = connection.cursor()

    email = email.strip().lower()

    cursor.execute(
        "SELECT * FROM users WHERE email = ?",
        (email,)
    )

    user = cursor.fetchone()

    connection.close()

    return user


# =========================================================
# GET USER BY ID
# =========================================================

def get_user_by_id(user_id):
    """
    Finds a user using their ID.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        "SELECT * FROM users WHERE id = ?",
        (user_id,)
    )

    user = cursor.fetchone()

    connection.close()

    return user



# =========================================================
# VERIFY LOGIN
# =========================================================

def verify_login(email, password):

    user = get_user_by_email(email)

    if user is None:
        return None

    # -------------------------------------------------
    # PASSWORD CHECK
    # -------------------------------------------------

    stored_password = user["password"]

    try:
        password_matches = bcrypt.checkpw(
            password.encode("utf-8"),
            stored_password.encode("utf-8")
        )
    except (ValueError, TypeError):
        return None

    if not password_matches:
        return None

    # -------------------------------------------------
    # MODERATION STATUS
    # -------------------------------------------------

    moderation_status = user["moderation_status"]

    # -------------------------------------------------
    # TEMPORARY SUSPENSION
    # -------------------------------------------------

    if moderation_status == "Suspended":

        suspension_until = user["banned_until"]

        if suspension_until:

            try:
                suspension_until = datetime.fromisoformat(
                    str(suspension_until)
                )
            except (ValueError, TypeError):
                suspension_until = None

        # -------------------------------------------------
        # SUSPENSION STILL ACTIVE
        # -------------------------------------------------

        if (
            suspension_until is None
            or datetime.utcnow() < suspension_until
        ):

            return (
                "SUSPENDED",
                suspension_until,
                user["ban_reason"]
            )

        # -------------------------------------------------
        # SUSPENSION EXPIRED
        # -------------------------------------------------

        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("""
            UPDATE users
            SET
                moderation_status = 'Active',
                banned_until = NULL,
                ban_reason = NULL
            WHERE id = ?
        """, (user["id"],))

        connection.commit()
        connection.close()

        return get_user_by_id(user["id"])

    # -------------------------------------------------
    # PERMANENT BAN
    # -------------------------------------------------

    if moderation_status == "Banned":

        return (
            "BANNED",
            None,
            user["ban_reason"]
        )

    # -------------------------------------------------
    # ACTIVE USER
    # -------------------------------------------------

    return user


# =========================================================
# GET ALL USERS
# =========================================================

def get_all_users():
    """
    Returns all registered users.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            id,
            name,
            email,
            location,
            role,
            trust_score,
            created_at,
            moderation_status,
            banned_until,
            ban_reason
        FROM users
        ORDER BY created_at DESC
    """)

    users = cursor.fetchall()

    connection.close()

    return users


# =========================================================
# UPDATE USER PROFILE
# =========================================================

def update_user(user_id, name, location, phone=None):
    """
    Updates the user's basic profile information.
    Phone number is optional until SMS verification is available.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE users
        SET name = ?,
            location = ?,
            phone = ?
        WHERE id = ?
    """, (
        name.strip(),
        location.strip(),
        phone.strip() if phone else None,
        user_id
    ))

    connection.commit()

    updated = cursor.rowcount > 0

    connection.close()

    return updated




# =========================================================
# CREATE HELP REQUEST
# =========================================================

def create_help_request(
    user_id,
    title,
    description,
    category,
    location,
    budget_type,
    budget_amount=None,
    latitude=None,
    longitude=None
):
    """
    Creates a new help request with budget information.

    budget_type:
        Free / Volunteer
        Paid
        Negotiable

    budget_amount:
        Amount offered when budget_type is Paid.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO help_requests
        (
            user_id,
            title,
            description,
            category,
            location,
            budget_type,
            budget_amount,
            latitude,
            longitude
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        title.strip(),
        description.strip(),
        category,
        location.strip(),
        budget_type,
        budget_amount,
        latitude,
        longitude
    ))

    connection.commit()

    request_id = cursor.lastrowid

    connection.close()

    return request_id


# =========================================================
# GET USER'S HELP REQUESTS
# =========================================================

def get_user_requests(user_id):
    """
    Returns all help requests created by a specific user.

    Also returns the helper's name when a helper has
    accepted the request.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            help_requests.*,
            helper.name AS helper_name
        FROM help_requests
        LEFT JOIN users AS helper
            ON help_requests.helper_id = helper.id
        WHERE help_requests.user_id = ?
        ORDER BY help_requests.created_at DESC
    """, (user_id,))

    requests = cursor.fetchall()

    connection.close()

    return requests

# =========================================================
# REMOVE OWN HELP REQUEST
# =========================================================

def remove_own_request(request_id, user_id):
    """
    Allows a requester to remove their own pending request.

    Rules:
    - Only the request owner can remove it.
    - Only Pending requests can be removed.
    - The request is soft-removed, not permanently deleted.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE help_requests
        SET is_removed = 1,
            removed_reason = 'Removed by requester',
            removed_at = ?,
            removed_by_admin = NULL
        WHERE id = ?
        AND user_id = ?
        AND status = 'Pending'
        AND is_removed = 0
    """, (
        datetime.utcnow(),
        request_id,
        user_id
    ))

    connection.commit()

    updated = cursor.rowcount > 0

    connection.close()

    return updated


# =========================================================
# GET OPEN HELP REQUESTS
# =========================================================

def get_open_requests(user_id=None):
    """
    Returns pending help requests.

    If user_id is provided, that user's own requests
    are excluded.
    """

    connection = get_connection()
    cursor = connection.cursor()

    if user_id is not None:

        cursor.execute("""
            SELECT
                help_requests.*,
                users.name AS requester_name
            FROM help_requests
            JOIN users
                ON help_requests.user_id = users.id
            WHERE help_requests.status = 'Pending'
                AND help_requests.is_removed = 0
                AND help_requests.user_id != ?

                AND NOT EXISTS (
                    SELECT 1
                    FROM notifications
                    WHERE notifications.user_id = ?
                        AND notifications.related_request_id = help_requests.id
                        AND notifications.type = 'helper_offer_declined'
                )

            ORDER BY help_requests.created_at DESC
        """, (user_id, user_id))

    else:

        cursor.execute("""
            SELECT
                help_requests.*,
                users.name AS requester_name,
                users.id AS requester_id
            FROM help_requests
            JOIN users
                ON help_requests.user_id = users.id
            WHERE help_requests.status = 'Pending'
            AND help_requests.is_removed = 0
            ORDER BY help_requests.created_at DESC
        """)

    requests = cursor.fetchall()

    connection.close()

    return requests


# =========================================================
# GET RECENT COMMUNITY ACTIVITY
# =========================================================

def get_recent_community_activity(limit=5):
    """
    Returns the latest help requests from the community.

    Includes requests in all workflow states so the Dashboard
    reflects actual community activity.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            help_requests.id,
            help_requests.title,
            help_requests.location,
            help_requests.status,
            help_requests.created_at,
            users.name AS requester_name
        FROM help_requests
        JOIN users
            ON help_requests.user_id = users.id
        WHERE help_requests.is_removed = 0
        ORDER BY help_requests.created_at DESC
        LIMIT ?
    """, (limit,))

    activities = cursor.fetchall()

    connection.close()

    return activities

# =========================================================
# SEARCH HELP REQUESTS
# =========================================================

def search_help_requests(search_term, user_id=None):

    connection = get_connection()
    cursor = connection.cursor()

    search_term = search_term.strip()

    query = """
        SELECT
            help_requests.*,
            users.name AS requester_name
        FROM help_requests
        JOIN users
            ON help_requests.user_id = users.id
        WHERE help_requests.status = 'Pending'
        AND help_requests.is_removed = 0
    """

    params = []

    if user_id is not None:
        query += """
            AND help_requests.user_id != ?

            AND NOT EXISTS (
                SELECT 1
                FROM notifications
                WHERE notifications.user_id = ?
                AND notifications.related_request_id = help_requests.id
                AND notifications.type = 'helper_offer_declined'
            )
        """

        params.extend([
            user_id,
            user_id,
        ])

    if search_term:
        query += """
            AND (
                help_requests.title LIKE ?
                OR help_requests.description LIKE ?
                OR help_requests.category LIKE ?
                OR help_requests.location LIKE ?
            )
        """

        keyword = f"%{search_term}%"

        params.extend([
            keyword,
            keyword,
            keyword,
            keyword,
        ])

    query += """
        ORDER BY help_requests.created_at DESC
    """

    cursor.execute(query, params)

    requests = cursor.fetchall()

    connection.close()

    return requests


# =========================================================
# OFFER TO HELP REQUEST
# =========================================================

def accept_help_request(request_id, helper_id):
    """
    Creates a helper offer for a pending help request.
    Requester must approve the helper before the request
    becomes Accepted.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE help_requests
        SET helper_id = ?,
            status = 'Awaiting Requester Approval'
        WHERE id = ?
        AND status = 'Pending'
        AND is_removed = 0
        AND user_id != ?

        AND NOT EXISTS (
            SELECT 1
            FROM notifications
            WHERE notifications.user_id = ?
                AND notifications.related_request_id = help_requests.id
                AND notifications.type = 'helper_offer_declined'
        )
    """, (
        helper_id,
        request_id,
        helper_id,
        helper_id
    ))

    updated = cursor.rowcount > 0

    request = None

    if updated:
        cursor.execute("""
            SELECT title, user_id
            FROM help_requests
            WHERE id = ?
        """, (request_id,))

        request = cursor.fetchone()

    connection.commit()
    connection.close()

    if updated and request:
        create_notification(
            request["user_id"],
            "helper_offer",
            "New Helper Offer",
            f'A neighbour wants to help with your request "{request["title"]}". Review their profile and decide whether to accept the helper.',
            request_id
        )

    return updated


# =========================================================
# APPROVE HELPER
# =========================================================

def approve_helper(request_id, requester_id):
    """
    Requester approves the offered helper.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE help_requests
        SET status = 'Accepted'
        WHERE id = ?
        AND user_id = ?
        AND status = 'Awaiting Requester Approval'
        AND helper_id IS NOT NULL
        AND is_removed = 0
    """, (
        request_id,
        requester_id
    ))

    updated = cursor.rowcount > 0

    request = None

    if updated:
        cursor.execute("""
            SELECT title, helper_id
            FROM help_requests
            WHERE id = ?
        """, (request_id,))

        request = cursor.fetchone()

    connection.commit()
    connection.close()

    if updated and request and request["helper_id"]:
        create_notification(
            request["helper_id"],
            "helper_accepted",
            "Helper Offer Accepted",
            f'Your offer to help with "{request["title"]}" was accepted.',
            request_id
        )

    return updated


# =========================================================
# DECLINE HELPER / FIND ANOTHER HELPER
# =========================================================

def decline_helper(request_id, requester_id):
    """
    Requester declines the offered helper and reopens
    the request for another helper.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT title, helper_id
        FROM help_requests
        WHERE id = ?
        AND user_id = ?
        AND status = 'Awaiting Requester Approval'
        AND is_removed = 0
    """, (
        request_id,
        requester_id
    ))

    request = cursor.fetchone()

    if not request:
        connection.close()
        return False

    previous_helper_id = request["helper_id"]

    cursor.execute("""
        UPDATE help_requests
        SET helper_id = NULL,
            status = 'Pending'
        WHERE id = ?
        AND user_id = ?
        AND status = 'Awaiting Requester Approval'
        AND is_removed = 0
    """, (
        request_id,
        requester_id
    ))

    updated = cursor.rowcount > 0

    connection.commit()
    connection.close()

    if updated and previous_helper_id:
        create_notification(
            previous_helper_id,
            "helper_offer_declined",
            "Helper Offer Declined",
            f'Your offer to help with "{request["title"]}" was declined. The request is available for another helper.',
            request_id
        )

    return updated


# =========================================================
# GET ACCEPTED HELP REQUESTS
# =========================================================

def get_accepted_requests(helper_id):
    """
    Returns help requests accepted by a specific helper.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            help_requests.*,
            users.name AS requester_name
        FROM help_requests
        JOIN users
            ON help_requests.user_id = users.id
        WHERE help_requests.helper_id = ?
        AND help_requests.is_removed = 0
        ORDER BY help_requests.created_at DESC
    """, (helper_id,))

    requests = cursor.fetchall()

    connection.close()

    return requests


def get_journey_request(request_id, viewer_id):
    """Return a journey only to its requester or accepted helper."""
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            help_requests.*,
            requester.name AS requester_name,
            helper.name AS helper_name
        FROM help_requests
        JOIN users AS requester
            ON requester.id = help_requests.user_id
        LEFT JOIN users AS helper
            ON helper.id = help_requests.helper_id
        WHERE help_requests.id = ?
        AND help_requests.is_removed = 0
        AND help_requests.status IN (
            'Accepted', 'Help Provided', 'Completed'
        )
        AND (
            help_requests.user_id = ?
            OR help_requests.helper_id = ?
        )
    """, (request_id, viewer_id, viewer_id))

    request = cursor.fetchone()
    connection.close()
    return request


def update_journey_status(request_id, helper_id, new_status):
    """Only the accepted helper can advance journey progress."""
    transitions = {
        "In Progress": "Not Started",
        "Arrived": "In Progress",
    }

    previous_status = transitions.get(new_status)
    if previous_status is None:
        return False

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE help_requests
        SET journey_status = ?
        WHERE id = ?
        AND helper_id = ?
        AND status = 'Accepted'
        AND is_removed = 0
        AND COALESCE(journey_status, 'Not Started') = ?
    """, (
        new_status,
        request_id,
        helper_id,
        previous_status,
    ))

    updated = cursor.rowcount > 0
    connection.commit()
    connection.close()
    return updated


def update_journey_location(
    request_id, helper_id, latitude, longitude
):
    """Save the accepted helper's latest shared coordinates."""
    try:
        latitude = float(latitude)
        longitude = float(longitude)
    except (TypeError, ValueError):
        return False

    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return False

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE help_requests
        SET helper_latitude = ?,
            helper_longitude = ?,
            helper_location_updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        AND helper_id = ?
        AND status = 'Accepted'
        AND journey_status = 'In Progress'
        AND is_removed = 0
    """, (
        latitude,
        longitude,
        request_id,
        helper_id,
    ))

    updated = cursor.rowcount > 0
    connection.commit()
    connection.close()
    return updated


def get_request_messages(request_id, viewer_id):
    """Return messages only to participants in an accepted connection."""
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            messages.id,
            messages.message,
            messages.created_at,
            messages.sender_id,
            users.name AS sender_name
        FROM request_messages AS messages
        JOIN help_requests AS requests
            ON requests.id = messages.request_id
        JOIN users
            ON users.id = messages.sender_id
        WHERE messages.request_id = ?
        AND requests.is_removed = 0
        AND requests.status IN (
            'Accepted', 'Help Provided', 'Completed'
        )
        AND (
            requests.user_id = ?
            OR requests.helper_id = ?
        )
        ORDER BY messages.created_at ASC, messages.id ASC
    """, (request_id, viewer_id, viewer_id))

    messages = cursor.fetchall()
    connection.close()
    return messages


def send_request_message(request_id, sender_id, message):
    """Save a private message between connected users."""
    message = (message or "").strip()

    if not message or len(message) > 2000:
        return False

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO request_messages (
            request_id, sender_id, message
        )
        SELECT ?, ?, ?
        WHERE EXISTS (
            SELECT 1
            FROM help_requests
            WHERE id = ?
            AND is_removed = 0
            AND status IN (
                'Accepted', 'Help Provided', 'Completed'
            )
            AND (
                user_id = ?
                OR helper_id = ?
            )
        )
    """, (
        request_id,
        sender_id,
        message,
        request_id,
        sender_id,
        sender_id,
    ))

    saved = cursor.rowcount > 0
    connection.commit()
    connection.close()
    return saved


# =========================================================
# GET CONNECTED USER PROFILE
# =========================================================

def get_connected_profile(request_id, viewer_id):
    """
    Returns the other person's profile for an accepted
    help connection.

    A profile is only accessible when the logged-in user
    is either the requester or helper for that request.

    Contact information is never exposed for unrelated users.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            id,
            user_id,
            helper_id,
            status,
            is_removed
        FROM help_requests
        WHERE id = ?
    """, (request_id,))

    request = cursor.fetchone()

    if request is None:
        connection.close()
        return None

    if request["is_removed"] == 1:
        connection.close()
        return None    

    requester_id = request["user_id"]
    helper_id = request["helper_id"]
    status = request["status"]

    # -----------------------------------------------------
    # REQUEST MUST HAVE A HELPER
    # -----------------------------------------------------

    if helper_id is None:
        connection.close()
        return None

    # -----------------------------------------------------
    # ONLY REQUESTER OR HELPER CAN VIEW THE PROFILE
    # -----------------------------------------------------

    if viewer_id not in (requester_id, helper_id):
        connection.close()
        return None

    # -----------------------------------------------------
    # ONLY AFTER ACCEPTANCE
    # -----------------------------------------------------

    allowed_statuses = (
        "Awaiting Requester Approval",
        "Accepted",
        "Help Provided",
        "Completed",
    )

    if status not in allowed_statuses:
        connection.close()
        return None

    # -----------------------------------------------------
    # FIND THE OTHER PERSON
    # -----------------------------------------------------

    if viewer_id == requester_id:
        other_user_id = helper_id
    else:
        other_user_id = requester_id

    cursor.execute("""
        SELECT
            id,
            name,
            email,
            location,
            role,
            trust_score,
            phone,
            email_verified,
            phone_verified
        FROM users
        WHERE id = ?
    """, (other_user_id,))

    user = cursor.fetchone()

    connection.close()

    return user



# =========================================================
# GET PUBLIC MATCH PROFILE
# =========================================================

def get_match_profile(request_id, viewer_id):
    """
    Returns the public profile of the person involved in
    a help request before the connection is accepted.

    Private contact information is intentionally excluded.

    Rules:
    - On a Pending request, another user may view the
    requester's public profile before offering help.
    - During Awaiting Requester Approval, the requester
    may view the offered helper's public profile.
    - The offered helper may also view the requester's
    public profile.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            id,
            user_id,
            helper_id,
            status,
            is_removed
        FROM help_requests
        WHERE id = ?
    """, (request_id,))

    request = cursor.fetchone()

    if request is None:
        connection.close()
        return None

    if request["is_removed"] == 1:
        connection.close()
        return None

    requester_id = request["user_id"]
    helper_id = request["helper_id"]
    status = request["status"]

    # -----------------------------------------------------
    # PENDING REQUEST
    # -----------------------------------------------------
    # Any logged-in user except the requester may review
    # the requester's public profile before offering help.

    if status == "Pending":

        if viewer_id == requester_id:
            connection.close()
            return None

        other_user_id = requester_id

    # -----------------------------------------------------
    # HELPER OFFER PENDING REQUESTER APPROVAL
    # -----------------------------------------------------

    elif status == "Awaiting Requester Approval":

        if helper_id is None:
            connection.close()
            return None

        # Requester reviews the offered helper.
        if viewer_id == requester_id:
            other_user_id = helper_id

        # Offered helper reviews the requester.
        elif viewer_id == helper_id:
            other_user_id = requester_id

        else:
            connection.close()
            return None

    else:
        connection.close()
        return None

    # -----------------------------------------------------
    # PUBLIC PROFILE ONLY
    # -----------------------------------------------------

    cursor.execute("""
        SELECT
            id,
            name,
            location,
            role,
            trust_score
        FROM users
        WHERE id = ?
    """, (other_user_id,))

    user = cursor.fetchone()

    connection.close()

    return user

    
# =========================================================
# GET PEOPLE HELPED COUNT
# =========================================================

def get_people_helped_count(helper_id):
    """
    Returns the number of help requests that the user
    successfully completed as the helper.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT COUNT(*) AS people_helped
        FROM help_requests
        WHERE helper_id = ?
        AND status = 'Completed'
        AND is_removed = 0
    """, (
        helper_id,
    ))

    result = cursor.fetchone()

    connection.close()

    return result["people_helped"] or 0


# =========================================================
# GET DASHBOARD STATS
# =========================================================

def get_dashboard_stats(user_id):
    """
    Returns real dashboard statistics for the logged-in user.

    My Requests:
        Total requests created by the user.

    Help Given:
        Requests accepted by the user as helper.

    Completed:
        Requests completed by the user, either as requester
        or helper.
    """

    connection = get_connection()
    cursor = connection.cursor()

    # One statement instead of three (same three conditions as before).
    cursor.execute("""
        SELECT
            (SELECT COUNT(*) FROM help_requests
              WHERE user_id = ?) AS my_requests,
            (SELECT COUNT(*) FROM help_requests
              WHERE helper_id = ?
                AND is_removed = 0) AS help_given,
            (SELECT COUNT(*) FROM help_requests
              WHERE status = 'Completed'
                AND is_removed = 0
                AND (user_id = ? OR helper_id = ?)) AS completed
    """, (user_id, user_id, user_id, user_id))

    row = cursor.fetchone()

    my_requests = row["my_requests"] or 0
    help_given = row["help_given"] or 0
    completed = row["completed"] or 0

    connection.close()

    return {
        "my_requests": my_requests,
        "help_given": help_given,
        "completed": completed,
    }



# =========================================================
# PERFORMANCE HELPERS (one statement instead of several)
# =========================================================

def get_live_counts(user_id):
    """
    Both sidebar/live-refresh unread counts, plus the id of the user's
    newest notification, in ONE statement.
    Same conditions as get_unread_notification_count() and
    get_unread_rating_count(). The newest id lets the live refresh notice
    a new notification even when the unread counts happen to be equal.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            (SELECT COUNT(*) FROM notifications
              WHERE user_id = ?
                AND is_read = 0
                AND type != 'rating_received') AS unread_notifications,
            (SELECT COUNT(*) FROM notifications
              WHERE user_id = ?
                AND type = 'rating_received'
                AND rating_is_read = 0) AS unread_ratings,
            (SELECT COALESCE(MAX(id), 0) FROM notifications
              WHERE user_id = ?) AS latest_notification_id
    """, (user_id, user_id, user_id))

    result = cursor.fetchone()

    connection.close()

    return (
        result["unread_notifications"] or 0,
        result["unread_ratings"] or 0,
        result["latest_notification_id"] or 0,
    )


def get_helper_offer_summary(helper_id):
    """
    Everything the 'new helper offer' card needs in ONE statement:
    trust score, location, average rating, rating count and
    people-helped count (same conditions as get_user_by_id(),
    get_user_rating_stats() and get_people_helped_count()).
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            (SELECT trust_score FROM users WHERE id = ?) AS trust_score,
            (SELECT location FROM users WHERE id = ?) AS location,
            (SELECT COUNT(*) FROM users WHERE id = ?) AS user_exists,
            (SELECT AVG(rating) FROM ratings WHERE receiver_id = ?) AS average_rating,
            (SELECT COUNT(*) FROM ratings WHERE receiver_id = ?) AS total_ratings,
            (SELECT COUNT(*) FROM help_requests
              WHERE helper_id = ?
                AND status = 'Completed'
                AND is_removed = 0) AS people_helped
    """, (helper_id,) * 6)

    r = cursor.fetchone()

    connection.close()

    return {
        "user_exists": bool(r["user_exists"]),
        "trust_score": r["trust_score"],
        "location": r["location"],
        "average_rating": round(r["average_rating"] or 0, 1),
        "total_ratings": r["total_ratings"] or 0,
        "people_helped": r["people_helped"] or 0,
    }


def get_rated_request_ids(giver_id):
    """Ids of every request this user has already rated (ONE statement)."""

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT request_id
        FROM ratings
        WHERE giver_id = ?
    """, (giver_id,))

    ids = {row["request_id"] for row in cursor.fetchall()}

    connection.close()

    return ids

    
# =========================================================
# MARK HELP AS PROVIDED
# =========================================================

def mark_help_provided(request_id, helper_id):
    """
    Helper confirms that they have provided the requested help.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE help_requests
        SET status = 'Help Provided'
        WHERE id = ?
        AND helper_id = ?
        AND status = 'Accepted'
        AND is_removed = 0
    """, (
        request_id,
        helper_id
    ))

    updated = cursor.rowcount > 0

    request = None

    if updated:
        cursor.execute("""
            SELECT title, user_id
            FROM help_requests
            WHERE id = ?
        """, (request_id,))

        request = cursor.fetchone()

    # Finish database operation BEFORE creating notifications
    connection.commit()
    connection.close()

    # -----------------------------------------------------
    # CREATE NOTIFICATIONS AFTER DATABASE CONNECTION CLOSES
    # -----------------------------------------------------
    if updated and request:

        # Notify requester
        create_notification(
            request["user_id"],
            "help_provided",
            "Help Provided",
            f'Your helper has provided the requested help for "{request["title"]}".',
            request_id
        )

        

    return updated

# =========================================================
# CONFIRM HELP COMPLETED
# =========================================================

def confirm_help_completed(request_id, requester_id):
    """
    Requester confirms that the help was successfully completed.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE help_requests
        SET status = 'Completed'
        WHERE id = ?
        AND user_id = ?
        AND status = 'Help Provided'
        AND is_removed = 0
    """, (
        request_id,
        requester_id
    ))

    updated = cursor.rowcount > 0

    request = None

    if updated:
        cursor.execute("""
            SELECT title, helper_id
            FROM help_requests
            WHERE id = ?
        """, (request_id,))

        request = cursor.fetchone()

    # Finish the database update BEFORE creating notifications
    connection.commit()
    connection.close()

    # -----------------------------------------------------
    # CREATE NOTIFICATIONS AFTER DATABASE CONNECTION CLOSES
    # -----------------------------------------------------
    if updated and request:

        if request["helper_id"]:

            # Notify helper
            create_notification(
                request["helper_id"],
                "help_completed",
                "Help Completed",
                f'The requester confirmed that "{request["title"]}" has been completed.',
                request_id
            )

    

    return updated


# =========================================================
# SUBMIT RATING
# =========================================================

def submit_rating(
    request_id,
    giver_id,
    receiver_id,
    rating,
    review
):
    """
    Saves requester feedback for a completed help request.

    Rating:
        1-5 stars

    Trust Score:
        Separate 0-100 reputation score calculated from
        requester feedback received after completed help.
    """

    # -----------------------------------------------------
    # VALIDATE RATING
    # -----------------------------------------------------

    try:
        rating = int(rating)
    except (TypeError, ValueError):
        return False, "Rating must be between 1 and 5."

    if rating < 1 or rating > 5:
        return False, "Rating must be between 1 and 5."

    connection = get_connection()
    cursor = connection.cursor()

    # -----------------------------------------------------
    # GET REQUEST
    # -----------------------------------------------------

    cursor.execute("""
        SELECT
            id,
            user_id,
            helper_id,
            status,
            is_removed
        FROM help_requests
        WHERE id = ?
    """, (request_id,))

    request = cursor.fetchone()

    if request is None:
        connection.close()
        return False, "Help request not found."

    if request["is_removed"] == 1:
        connection.close()
        return False, "This request is no longer available for feedback."        

    # -----------------------------------------------------
    # ONLY THE REQUESTER CAN RATE THE HELPER
    # -----------------------------------------------------

    if request["user_id"] != giver_id:
        connection.close()
        return False, "Only the requester can submit feedback."

    # -----------------------------------------------------
    # MAKE SURE THE RECEIVER IS THE ACTUAL HELPER
    # -----------------------------------------------------

    if request["helper_id"] != receiver_id:
        connection.close()
        return False, "Invalid helper for this request."

    # -----------------------------------------------------
    # REQUEST MUST BE COMPLETED
    # -----------------------------------------------------

    if request["status"] != "Completed":
        connection.close()
        return False, "This request is not completed yet."

    # -----------------------------------------------------
    # PREVENT DUPLICATE RATING
    # -----------------------------------------------------

    cursor.execute("""
        SELECT id
        FROM ratings
        WHERE request_id = ?
        AND giver_id = ?
    """, (
        request_id,
        giver_id
    ))

    existing_rating = cursor.fetchone()

    if existing_rating:
        connection.close()
        return False, "You have already rated this request."

    # -----------------------------------------------------
    # SAVE RATING + REVIEW
    # -----------------------------------------------------

    cursor.execute("""
        INSERT INTO ratings
        (
            request_id,
            giver_id,
            receiver_id,
            rating,
            review
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        request_id,
        giver_id,
        receiver_id,
        rating,
        (review or "").strip()
    ))

    connection.commit()
    connection.close()

    # -----------------------------------------------------
    # RECALCULATE TRUST SCORE
    # -----------------------------------------------------

    update_trust_score(receiver_id)
    
    create_notification(
        receiver_id,
        "rating_received",
        "New Rating Received",
        "You received a new rating from a requester.",
        request_id
    )

    return True, "Rating submitted successfully."

# =========================================================
# UPDATE TRUST SCORE
# =========================================================

def update_trust_score(user_id):
    """
    Calculates the user's Trust Score on a 0-100 scale.

    Rules:
    - New users start at 50.
    - Trust Score is separate from the displayed 1-5 rating.
    - Only requester feedback stored in ratings is used.
    - More completed feedback gradually increases confidence.
    - Score is always clamped between 0 and 100.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            AVG(rating) AS average_rating,
            COUNT(*) AS rating_count
        FROM ratings
        WHERE receiver_id = ?
    """, (user_id,))

    result = cursor.fetchone()

    average_rating = result["average_rating"]
    rating_count = result["rating_count"]

    # -----------------------------------------------------
    # NO FEEDBACK = NEUTRAL TRUST SCORE
    # -----------------------------------------------------

    if rating_count == 0 or average_rating is None:
        trust_score = 50.0

    else:
        # -------------------------------------------------
        # MAP 1-5 RATING TO 0-100
        #
        # 1 star = 0
        # 3 stars = 50
        # 5 stars = 100
        # -------------------------------------------------

        rating_score = ((average_rating - 1) / 4) * 100

        # -------------------------------------------------
        # CONFIDENCE WEIGHT
        #
        # A single rating should not immediately make
        # someone extremely high or extremely low.
        #
        # More completed feedback = stronger confidence.
        # -------------------------------------------------

        confidence = rating_count / (rating_count + 5)

        # -------------------------------------------------
        # START FROM NEUTRAL 50 AND MOVE TOWARD
        # THE ACTUAL FEEDBACK SCORE
        # -------------------------------------------------

        trust_score = (
            50
            + (rating_score - 50) * confidence
        )

    # -----------------------------------------------------
    # SAFETY BOUNDARY
    # -----------------------------------------------------

    trust_score = max(0.0, min(100.0, trust_score))

    trust_score = round(trust_score, 1)

    cursor.execute("""
        UPDATE users
        SET trust_score = ?
        WHERE id = ?
    """, (
        trust_score,
        user_id
    ))

    connection.commit()
    connection.close()

    return trust_score    


# =========================================================
# CHECK EXISTING RATING
# =========================================================

def has_user_rated(request_id, giver_id):

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT id
        FROM ratings
        WHERE request_id = ?
        AND giver_id = ?
    """, (
        request_id,
        giver_id
    ))

    rating = cursor.fetchone()

    connection.close()

    return rating is not None


# =========================================================
# GET USER RATING STATS
# =========================================================

def get_user_rating_stats(user_id):

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            AVG(rating) AS average_rating,
            COUNT(*) AS total_ratings
        FROM ratings
        WHERE receiver_id = ?
    """, (user_id,))

    result = cursor.fetchone()

    connection.close()

    average_rating = result["average_rating"] or 0
    total_ratings = result["total_ratings"] or 0

    return round(average_rating, 1), total_ratings    


# =========================================================
# GET RECEIVED REVIEWS
# =========================================================

def get_received_reviews(user_id, limit=10):
    """
    Returns recent written reviews received by a helper.

    Only reviews submitted by requesters for completed
    help requests are returned.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            ratings.id,
            ratings.rating,
            ratings.review,
            ratings.created_at,
            users.name AS reviewer_name,
            help_requests.title AS request_title
        FROM ratings
        JOIN users
            ON ratings.giver_id = users.id
        JOIN help_requests
            ON ratings.request_id = help_requests.id
        WHERE ratings.receiver_id = ?
        AND ratings.review IS NOT NULL
        AND TRIM(ratings.review) != ''
        AND help_requests.status = 'Completed'
        ORDER BY ratings.created_at DESC
        LIMIT ?
    """, (
        user_id,
        limit
    ))

    reviews = cursor.fetchall()

    connection.close()

    return reviews




# -----------------------------------------------------
# MIGRATE DATABASE
# -----------------------------------------------------

def migrate_database():

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("PRAGMA table_info(users)")
    columns = [column["name"] for column in cursor.fetchall()]

    if "email_verified" not in columns:
        cursor.execute("""
            ALTER TABLE users
            ADD COLUMN email_verified INTEGER DEFAULT 0
        """)

    if "verification_token" not in columns:
        cursor.execute("""
            ALTER TABLE users
            ADD COLUMN verification_token TEXT
        """)

    if "verification_expires_at" not in columns:
        cursor.execute("""
            ALTER TABLE users
            ADD COLUMN verification_expires_at TIMESTAMP
        """)

    if "phone" not in columns:
        cursor.execute("""
            ALTER TABLE users
            ADD COLUMN phone TEXT
        """)

    if "phone_verified" not in columns:
        cursor.execute("""
            ALTER TABLE users
            ADD COLUMN phone_verified INTEGER DEFAULT 0
        """)

    if "phone_otp_hash" not in columns:
        cursor.execute("""
            ALTER TABLE users
            ADD COLUMN phone_otp_hash TEXT
        """)

    if "phone_otp_expires_at" not in columns:
        cursor.execute("""
            ALTER TABLE users
            ADD COLUMN phone_otp_expires_at TIMESTAMP
        """)

    if "phone_otp_attempts" not in columns:
        cursor.execute("""
            ALTER TABLE users
            ADD COLUMN phone_otp_attempts INTEGER DEFAULT 0
        """)

    # -----------------------------------------------------
    # MODERATION / BAN FIELDS
    # -----------------------------------------------------

    if "moderation_status" not in columns:
        cursor.execute("""
            ALTER TABLE users
            ADD COLUMN moderation_status TEXT DEFAULT 'Active'
        """)

    if "banned_until" not in columns:
        cursor.execute("""
            ALTER TABLE users
            ADD COLUMN banned_until TIMESTAMP
        """)

    if "ban_reason" not in columns:
        cursor.execute("""
            ALTER TABLE users
            ADD COLUMN ban_reason TEXT
        """)



    # -----------------------------------------------------
    # REQUEST MODERATION FIELDS
    # -----------------------------------------------------

    cursor.execute("PRAGMA table_info(help_requests)")
    request_columns = [
        column["name"]
        for column in cursor.fetchall()
    ]

    if "is_removed" not in request_columns:
        cursor.execute("""
            ALTER TABLE help_requests
            ADD COLUMN is_removed INTEGER DEFAULT 0
        """)

    if "removed_reason" not in request_columns:
        cursor.execute("""
            ALTER TABLE help_requests
            ADD COLUMN removed_reason TEXT
        """)

    if "removed_at" not in request_columns:
        cursor.execute("""
            ALTER TABLE help_requests
            ADD COLUMN removed_at TIMESTAMP
        """)

    if "removed_by_admin" not in request_columns:
        cursor.execute("""
            ALTER TABLE help_requests
            ADD COLUMN removed_by_admin INTEGER
        """)        

    # -----------------------------------------------------
    # REQUEST BUDGET FIELDS
    # -----------------------------------------------------

    if "budget_type" not in request_columns:
        cursor.execute("""
            ALTER TABLE help_requests
            ADD COLUMN budget_type TEXT DEFAULT 'Free / Volunteer'
        """)

    if "budget_amount" not in request_columns:
        cursor.execute("""
            ALTER TABLE help_requests
            ADD COLUMN budget_amount REAL
        """)

    # -----------------------------------------------------
    # REQUEST LOCATION COORDINATES
    # -----------------------------------------------------

    if "latitude" not in request_columns:
        cursor.execute("""
            ALTER TABLE help_requests
            ADD COLUMN latitude REAL
        """)

    if "longitude" not in request_columns:
        cursor.execute("""
            ALTER TABLE help_requests
            ADD COLUMN longitude REAL
        """)

    
    # -----------------------------------------------------
    # JOURNEY TRACKING FIELDS
    # -----------------------------------------------------

    if "journey_status" not in request_columns:
        cursor.execute("""
            ALTER TABLE help_requests
            ADD COLUMN journey_status TEXT DEFAULT 'Not Started'
        """)

    if "helper_latitude" not in request_columns:
        cursor.execute("""
            ALTER TABLE help_requests
            ADD COLUMN helper_latitude REAL
        """)

    if "helper_longitude" not in request_columns:
        cursor.execute("""
            ALTER TABLE help_requests
            ADD COLUMN helper_longitude REAL
        """)

    if "helper_location_updated_at" not in request_columns:
        cursor.execute("""
            ALTER TABLE help_requests
            ADD COLUMN helper_location_updated_at TEXT
        """)

    # -----------------------------------------------------
    # PRIVATE CONNECTION MESSAGES
    # -----------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS request_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER NOT NULL,
            sender_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (request_id) REFERENCES help_requests(id),
            FOREIGN KEY (sender_id) REFERENCES users(id)
        )
    """)


    # -----------------------------------------------------
    # ADMIN REPORT FIELDS
    # -----------------------------------------------------

    cursor.execute("PRAGMA table_info(reports)")
    report_columns = [
        column["name"]
        for column in cursor.fetchall()
    ]

    if "report_type" not in report_columns:
        cursor.execute("""
            ALTER TABLE reports
            ADD COLUMN report_type TEXT DEFAULT 'User'
        """)

    if "admin_note" not in report_columns:
        cursor.execute("""
            ALTER TABLE reports
            ADD COLUMN admin_note TEXT
        """)

    if "admin_action" not in report_columns:
        cursor.execute("""
            ALTER TABLE reports
            ADD COLUMN admin_action TEXT
        """)

    if "reviewed_at" not in report_columns:
        cursor.execute("""
            ALTER TABLE reports
            ADD COLUMN reviewed_at TIMESTAMP
        """)


    # -----------------------------------------------------
    # TRUST SCORE MIGRATION
    # -----------------------------------------------------
    #
    # Existing users may have Trust Scores stored using
    # the old 0-5 rating-based system.
    #
    # Recalculate them using the new 0-100 system.
    # Users without feedback remain at neutral 50.
    # -----------------------------------------------------

    cursor.execute("""
        SELECT id
        FROM users
    """)

    users = cursor.fetchall()

    for user in users:

        cursor.execute("""
            SELECT
                AVG(rating) AS average_rating,
                COUNT(*) AS rating_count
            FROM ratings
            WHERE receiver_id = ?
        """, (user["id"],))

        result = cursor.fetchone()

        average_rating = result["average_rating"]
        rating_count = result["rating_count"]

        if rating_count == 0 or average_rating is None:

            trust_score = 50.0

        else:

            # Convert 1-5 rating to 0-100
            rating_score = (
                (average_rating - 1) / 4
            ) * 100

            # Gradually increase confidence as
            # more feedback is received.
            confidence = (
                rating_count /
                (rating_count + 5)
            )

            trust_score = (
                50
                + (rating_score - 50)
                * confidence
            )

            # Never allow Trust Score outside 0-100
            trust_score = max(
                0.0,
                min(100.0, trust_score)
            )

        cursor.execute("""
            UPDATE users
            SET trust_score = ?
            WHERE id = ?
        """, (
            round(trust_score, 1),
            user["id"]
        ))


    # -----------------------------------------------------
    # RATING NOTIFICATION READ STATE
    # -----------------------------------------------------

    cursor.execute("PRAGMA table_info(notifications)")
    notification_columns = [
        column["name"]
        for column in cursor.fetchall()
    ]

    if "rating_is_read" not in notification_columns:
        cursor.execute("""
            ALTER TABLE notifications
            ADD COLUMN rating_is_read INTEGER DEFAULT 1
        """)

        cursor.execute("""
            UPDATE notifications
            SET rating_is_read = 0
            WHERE type = 'rating_received'
        """)    

    connection.commit()
    connection.close()


# =========================================================
# CREATE REPORT
# =========================================================

def create_report(
    reporter_id,
    reported_user_id=None,
    request_id=None,
    reason="",
    report_type="Profile"
):
    """
    Creates a new community report.

    Prevents the same user from repeatedly reporting
    the same request or profile.

    report_type:
        Profile -> report about a user's profile
        Request -> report about a specific help request
    """

    connection = get_connection()
    cursor = connection.cursor()

    # -------------------------------------------------
    # PREVENT DUPLICATE REPORTS
    # -------------------------------------------------

    if report_type == "Request":

        cursor.execute("""
            SELECT id
            FROM reports
            WHERE reporter_id = ?
            AND reported_user_id = ?
            AND request_id = ?
            AND report_type = 'Request'
            AND status != 'Resolved'
            LIMIT 1
        """, (
            reporter_id,
            reported_user_id,
            request_id
        ))

    else:

        cursor.execute("""
            SELECT id
            FROM reports
            WHERE reporter_id = ?
            AND reported_user_id = ?
            AND report_type = 'Profile'
            AND status != 'Resolved'
            LIMIT 1
        """, (
            reporter_id,
            reported_user_id
        ))

    existing_report = cursor.fetchone()

    if existing_report:
        connection.close()
        return None

    # -------------------------------------------------
    # CREATE NEW REPORT
    # -------------------------------------------------

    cursor.execute("""
        INSERT INTO reports
        (
            reporter_id,
            reported_user_id,
            request_id,
            reason,
            report_type
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        reporter_id,
        reported_user_id,
        request_id,
        reason.strip(),
        report_type
    ))

    connection.commit()

    report_id = cursor.lastrowid

    connection.close()

    return report_id

# =========================================================
# ADMIN STATISTICS
# =========================================================

def get_admin_statistics():
    """
    Returns basic statistics for the Admin Panel.
    """

    connection = get_connection()
    cursor = connection.cursor()

    # -----------------------------------------------------
    # TOTAL USERS
    # -----------------------------------------------------

    cursor.execute("""
        SELECT COUNT(*) AS total_users
        FROM users
    """)

    total_users = cursor.fetchone()["total_users"]

    # -----------------------------------------------------
    # TOTAL REQUESTS
    # -----------------------------------------------------

    cursor.execute("""
        SELECT COUNT(*) AS total_requests
        FROM help_requests
    """)

    total_requests = cursor.fetchone()["total_requests"]

    # -----------------------------------------------------
    # COMPLETED REQUESTS
    # -----------------------------------------------------

    cursor.execute("""
        SELECT COUNT(*) AS completed_requests
        FROM help_requests
        WHERE status = 'Completed'
    """)

    completed_requests = cursor.fetchone()["completed_requests"]

    # -----------------------------------------------------
    # TOTAL REPORTS
    # -----------------------------------------------------

    cursor.execute("""
        SELECT COUNT(*) AS total_reports
        FROM reports
    """)

    total_reports = cursor.fetchone()["total_reports"]

    connection.close()

    return {
        "total_users": total_users,
        "total_requests": total_requests,
        "completed_requests": completed_requests,
        "total_reports": total_reports,
    }

    


# =========================================================
# ADMIN REQUEST MONITORING
# =========================================================

def get_admin_requests():
    """
    Returns help requests for Admin monitoring.

    Privacy:
    - Does NOT expose requester name
    - Does NOT expose requester email
    - Does NOT expose requester phone
    - Does NOT expose helper name
    - Does NOT expose helper email
    - Does NOT expose helper phone

    Admin receives only information needed to
    monitor and moderate the request workflow.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            help_requests.id,
            help_requests.title,
            help_requests.description,
            help_requests.category,
            help_requests.location,
            help_requests.status,
            help_requests.helper_id,
            help_requests.created_at,
            help_requests.is_removed,
            help_requests.removed_reason,
            help_requests.removed_at,
            help_requests.removed_by_admin,
            help_requests.budget_type,
            help_requests.budget_amount
        FROM help_requests
        ORDER BY help_requests.created_at DESC
    """)

    requests = cursor.fetchall()

    connection.close()

    return requests


# =========================================================
# ADMIN USER MODERATION
# =========================================================

def get_admin_users():
    """
    Returns users for Admin moderation.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            id,
            name,
            email,
            role,
            trust_score,
            moderation_status,
            banned_until,
            ban_reason,
            created_at
        FROM users
        ORDER BY created_at DESC
    """)

    users = cursor.fetchall()

    connection.close()

    return users


# =========================================================
# SUSPEND USER
# =========================================================

def suspend_user(user_id, hours, reason):
    """
    Temporarily suspends a non-admin user.
    """

    try:
        hours = int(hours)
    except (TypeError, ValueError):
        return False

    if hours <= 0:
        return False

    banned_until = (
        datetime.utcnow()
        + timedelta(hours=hours)
    )

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE users
        SET moderation_status = 'Suspended',
            banned_until = ?,
            ban_reason = ?
        WHERE id = ?
        AND role != 'Admin'
    """, (
        banned_until,
        reason.strip(),
        user_id
    ))

    updated = cursor.rowcount > 0

    connection.commit()
    connection.close()

    # -----------------------------------------------------
    # NOTIFY USER AFTER DATABASE CONNECTION CLOSES
    # -----------------------------------------------------
    if updated:
        create_notification(
            user_id,
            "account_suspended",
            "Account Suspended",
            f"Your account has been suspended for {hours} hours. Reason: {reason.strip()}",
            None
        )

    return updated


# =========================================================
# PERMANENT BAN USER
# =========================================================

def ban_user(user_id, reason):
    """
    Permanently bans a non-admin user.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE users
        SET moderation_status = 'Banned',
            banned_until = NULL,
            ban_reason = ?
        WHERE id = ?
        AND role != 'Admin'
    """, (
        reason.strip(),
        user_id
    ))

    updated = cursor.rowcount > 0

    connection.commit()
    connection.close()

    # -----------------------------------------------------
    # NOTIFY USER AFTER DATABASE CONNECTION CLOSES
    # -----------------------------------------------------
    if updated:
        create_notification(
            user_id,
            "account_banned",
            "Account Permanently Banned",
            f"Your account has been permanently banned. Reason: {reason.strip()}",
            None
        )

    return updated

                                                            

# =========================================================
# RESTORE USER
# =========================================================

def restore_user(user_id):
    """
    Restores a suspended or banned user.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE users
        SET moderation_status = 'Active',
            banned_until = NULL,
            ban_reason = NULL
        WHERE id = ?
        AND role != 'Admin'
    """, (user_id,))

    updated = cursor.rowcount > 0

    connection.commit()
    connection.close()

    # -----------------------------------------------------
    # NOTIFY USER AFTER DATABASE CONNECTION CLOSES
    # -----------------------------------------------------
    if updated:
        create_notification(
            user_id,
            "account_restored",
            "Account Restored",
            "Your account has been restored by an Admin. You can now use Neki normally.",
            None
        )

    return updated


# =========================================================
# REMOVE REQUEST BY ADMIN
# =========================================================

def remove_admin_request(request_id, reason, admin_id=None):
    """
    Hides a suspicious request from the community.

    The original request status is NOT changed.
    """

    connection = get_connection()
    cursor = connection.cursor()

    # Get request details before removing it
    cursor.execute("""
        SELECT title, user_id
        FROM help_requests
        WHERE id = ?
        AND is_removed = 0
    """, (request_id,))

    request = cursor.fetchone()

    if not request:
        connection.close()
        return False

    cursor.execute("""
        UPDATE help_requests
        SET is_removed = 1,
            removed_reason = ?,
            removed_at = ?,
            removed_by_admin = ?
        WHERE id = ?
        AND is_removed = 0
    """, (
        reason.strip(),
        datetime.utcnow(),
        admin_id,
        request_id
    ))

    updated = cursor.rowcount > 0

    connection.commit()
    connection.close()

    # -----------------------------------------------------
    # NOTIFY REQUESTER AFTER DATABASE CONNECTION CLOSES
    # -----------------------------------------------------
    if updated:
        create_notification(
            request["user_id"],
            "request_removed",
            "Request Removed",
            f'Your request "{request["title"]}" was removed by an Admin. Reason: {reason.strip()}',
            request_id
        )

    return updated


# =========================================================
# RESTORE REQUEST BY ADMIN
# =========================================================

def restore_admin_request(request_id):
    """
    Restores a request removed by Admin.
    """

    connection = get_connection()
    cursor = connection.cursor()

    # Get request details before restoring
    cursor.execute("""
        SELECT title, user_id
        FROM help_requests
        WHERE id = ?
        AND is_removed = 1
    """, (request_id,))

    request = cursor.fetchone()

    if not request:
        connection.close()
        return False

    cursor.execute("""
        UPDATE help_requests
        SET is_removed = 0,
            removed_reason = NULL,
            removed_at = NULL,
            removed_by_admin = NULL
        WHERE id = ?
        AND is_removed = 1
    """, (request_id,))

    updated = cursor.rowcount > 0

    connection.commit()
    connection.close()

    # -----------------------------------------------------
    # NOTIFY REQUESTER AFTER DATABASE CONNECTION CLOSES
    # -----------------------------------------------------
    if updated:
        create_notification(
            request["user_id"],
            "request_restored",
            "Request Restored",
            f'Your request "{request["title"]}" has been restored by an Admin.',
            request_id
        )

    return updated 

# =========================================================
# ADMIN REPORTS
# =========================================================

def get_admin_reports():
    """
    Returns all reports for Admin review.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            reports.id,
            reports.reason,
            reports.status,
            reports.created_at,
            reports.reporter_id,
            reports.reported_user_id,
            reports.request_id,
            reports.report_type,
            reports.admin_note,
            reports.admin_action,
            reports.reviewed_at,

            reporter.name AS reporter_name,
            reported.name AS reported_user_name

        FROM reports

        LEFT JOIN users AS reporter
            ON reports.reporter_id = reporter.id

        LEFT JOIN users AS reported
            ON reports.reported_user_id = reported.id

        ORDER BY reports.created_at DESC
    """)

    reports = cursor.fetchall()

    connection.close()

    return reports


# =========================================================
# RESOLVE REPORT
# =========================================================

def resolve_admin_report(report_id, admin_note=None, admin_action=None):
    """
    Marks an open report as resolved and stores the Admin review.
    A resolved report cannot be resolved again.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE reports
        SET status = 'Resolved',
            admin_note = ?,
            admin_action = ?,
            reviewed_at = ?
        WHERE id = ?
        AND status != 'Resolved'
    """, (
        admin_note.strip() if admin_note else None,
        admin_action,
        datetime.utcnow(),
        report_id
    ))

    connection.commit()

    updated = cursor.rowcount > 0

    connection.close()

    return updated


# =========================================================
# TAKE ACTION ON REPORT
# =========================================================

def take_admin_report_action(report_id, action, reason):
    """
    Allows Admin to take moderation action on a report.

    Supported actions:
        Suspend User
        Ban User
        Remove Request
    """

    connection = get_connection()
    cursor = connection.cursor()

    # Get the report
    cursor.execute("""
        SELECT
            id,
            reporter_id,
            reported_user_id,
            request_id,
            report_type
        FROM reports
        WHERE id = ?
    """, (report_id,))

    report = cursor.fetchone()

    if not report:
        connection.close()
        return False

    reporter_id = report["reporter_id"]
    reported_user_id = report["reported_user_id"]
    request_id = report["request_id"]
    report_type = report["report_type"]

    connection.close()

    # -------------------------------------------------
    # SUSPEND USER
    # -------------------------------------------------

    if action.startswith("Suspend"):

        try:
            hours = int(
                action.replace("Suspend", "")
                .replace("hours", "")
                .strip()
            )
        except ValueError:
            return False

        success = suspend_user(
            reported_user_id,
            hours,
            reason
        )

        if success:

            resolve_admin_report(
                report_id,
                admin_note=reason,
                admin_action=action
            )

            # Notify report submitter
            if reporter_id and reporter_id != reported_user_id:
                create_notification(
                    reporter_id,
                    "report_reviewed",
                    "Report Reviewed",
                    f"Your report has been reviewed by an Admin. Action taken: {action}.",
                    request_id
                )

        return success

    # -------------------------------------------------
    # PERMANENT BAN USER
    # -------------------------------------------------

    if action == "Ban User":

        success = ban_user(
            reported_user_id,
            reason
        )

        if success:

            resolve_admin_report(
                report_id,
                admin_note=reason,
                admin_action=action
            )

            # Notify report submitter
            if reporter_id and reporter_id != reported_user_id:
                create_notification(
                    reporter_id,
                    "report_reviewed",
                    "Report Reviewed",
                    f"Your report has been reviewed by an Admin. Action taken: {action}.",
                    request_id
                )

        return success

    # -------------------------------------------------
    # REMOVE REQUEST
    # -------------------------------------------------

    if action == "Remove Request":

        # Only Request Reports can remove a request.
        if report_type != "Request":
            return False

        if not request_id:
            return False

        success = remove_admin_request(
            request_id,
            reason
        )

        if success:

            resolve_admin_report(
                report_id,
                admin_note=reason,
                admin_action=action
            )

            # Notify report submitter
            # Avoid duplicate notification if reporter is
            # also the request owner.
            if reporter_id and reporter_id != reported_user_id:
                create_notification(
                    reporter_id,
                    "report_reviewed",
                    "Report Reviewed",
                    f"Your report has been reviewed by an Admin. Action taken: {action}.",
                    request_id
                )

        return success

    return False


# =========================================================
# NOTIFICATIONS
# =========================================================

def create_notification(
    user_id,
    notification_type,
    title,
    message,
    related_request_id=None
):
    """
    Creates a notification for a user.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO notifications
        (
            user_id,
            type,
            title,
            message,
            related_request_id,
            rating_is_read
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        notification_type,
        title,
        message,
        related_request_id,
        0 if notification_type == "rating_received" else 1
    ))

    connection.commit()

    notification_id = cursor.lastrowid

    connection.close()

    return notification_id


def get_notifications(user_id, limit=50):
    """
    Returns the latest notifications for a user.
    Unread notifications appear first.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            id,
            user_id,
            type,
            title,
            message,
            related_request_id,
            is_read,
            created_at
        FROM notifications
        WHERE user_id = ?
            AND type != 'rating_received'
        ORDER BY is_read ASC, created_at DESC
        LIMIT ?
    """, (
        user_id,
        limit
    ))

    notifications = cursor.fetchall()

    connection.close()

    return notifications


def get_unread_notification_count(user_id):
    """
    Returns the number of unread notifications
    for a specific user.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT COUNT(*) AS unread_count
        FROM notifications
        WHERE user_id = ?
            AND is_read = 0
            AND type != 'rating_received'
    """, (user_id,))

    result = cursor.fetchone()

    connection.close()

    return result["unread_count"] or 0


def get_unread_rating_count(user_id):
    """
    Returns the number of unread rating notifications
    for a specific user.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT COUNT(*) AS unread_count
        FROM notifications
        WHERE user_id = ?
        AND type = 'rating_received'
        AND rating_is_read = 0
    """, (user_id,))

    result = cursor.fetchone()

    connection.close()

    return result["unread_count"] or 0


def mark_rating_notifications_read(user_id):
    """
    Marks rating notifications as read for My Ratings.
    Does not affect normal notification read state.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE notifications
        SET rating_is_read = 1
        WHERE user_id = ?
        AND type = 'rating_received'
        AND rating_is_read = 0
    """, (user_id,))

    connection.commit()

    updated = cursor.rowcount

    connection.close()

    return updated


def mark_notification_read(notification_id, user_id):
    """
    Marks one notification as read.

    The user can only update their own notification.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE notifications
        SET is_read = 1
        WHERE id = ?
        AND user_id = ?
    """, (
        notification_id,
        user_id
    ))

    connection.commit()

    updated = cursor.rowcount > 0

    connection.close()

    return updated


def mark_all_notifications_read(user_id):
    """
    Marks all notifications belonging to a user as read.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE notifications
        SET is_read = 1
        WHERE user_id = ?
        AND is_read = 0
    """, (user_id,))

    connection.commit()

    updated = cursor.rowcount

    connection.close()

    return updated


def create_login_session(user_id):
    import secrets
    import hashlib
    from datetime import datetime, timedelta

    session_token = secrets.token_urlsafe(48)

    token_hash = hashlib.sha256(
        session_token.encode("utf-8")
    ).hexdigest()

    created_at = datetime.utcnow()
    expires_at = created_at + timedelta(days=30)

    conn = get_connection()

    conn.execute(
        """
        INSERT INTO user_sessions (
            user_id,
            session_token_hash,
            created_at,
            expires_at
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            user_id,
            token_hash,
            created_at.isoformat(),
            expires_at.isoformat(),
        ),
    )

    conn.commit()
    conn.close()

    return session_token


def get_user_from_session(session_token):
    import hashlib
    from datetime import datetime

    if not session_token:
        return None

    token_hash = hashlib.sha256(
        session_token.encode("utf-8")
    ).hexdigest()

    conn = get_connection()

    row = conn.execute(
        """
        SELECT users.*
        FROM user_sessions
        JOIN users
            ON users.id = user_sessions.user_id
        WHERE user_sessions.session_token_hash = ?
        AND user_sessions.expires_at > ?
        """,
        (
            token_hash,
            datetime.utcnow().isoformat(),
        ),
    ).fetchone()

    conn.close()

    return row


def delete_login_session(session_token):
    import hashlib

    if not session_token:
        return

    token_hash = hashlib.sha256(
        session_token.encode("utf-8")
    ).hexdigest()

    conn = get_connection()

    conn.execute(
        """
        DELETE FROM user_sessions
        WHERE session_token_hash = ?
        """,
        (token_hash,),
    )

    conn.commit()
    conn.close()


# =========================================================
# USER SKILLS
# =========================================================

def get_user_skills(user_id):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT id, skill
        FROM user_skills
        WHERE user_id = ?
        ORDER BY skill COLLATE NOCASE
    """, (user_id,))

    skills = cursor.fetchall()
    connection.close()

    return skills


def add_user_skill(user_id, skill):
    skill = " ".join(skill.strip().split())

    if not skill or len(skill) > 40:
        return False

    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("""
            INSERT INTO user_skills (user_id, skill)
            VALUES (?, ?)
        """, (user_id, skill))

        connection.commit()
        return True

    except sqlite3.IntegrityError:
        return False

    finally:
        connection.close()


def delete_user_skill(user_id, skill_id):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        DELETE FROM user_skills
        WHERE id = ? AND user_id = ?
    """, (skill_id, user_id))

    deleted = cursor.rowcount > 0
    connection.commit()
    connection.close()

    return deleted
    
# =========================================================
# CREATE DATABASE
# =========================================================
turso_compat.init_schema(create_tables, migrate_database, get_connection)


# =========================================================
# TEST
# =========================================================

if __name__ == "__main__":
    print("NeighbourHelp database is ready.")
