import html
import streamlit as st
import folium
from folium.plugins import LocateControl
import requests
import time
import json
from datetime import datetime, timezone
from streamlit_session_browser_storage import SessionStorage
import streamlit.components.v1 as components
import extra_streamlit_components as stx
from pathlib import Path

from landing_page import render_landing_page
from streamlit_folium import st_folium

from database import (
    register_user,
    verify_login,
    create_login_session,
    get_user_from_session,
    delete_login_session,
    update_user,
    get_user_by_id,
    get_user_by_email,
    create_help_request,
    get_user_requests,
    remove_own_request,
    get_open_requests,
    accept_help_request,
    approve_helper,
    decline_helper,
    get_accepted_requests,
    get_connected_profile,
    get_match_profile,
    get_people_helped_count,
    get_dashboard_stats,
    get_recent_community_activity,
    mark_help_provided,
    confirm_help_completed,
    submit_rating,
    has_user_rated,
    get_user_rating_stats,
    get_received_reviews,
    search_help_requests,
    create_verification_token,
    verify_email_token,
    create_password_reset_token,
    reset_password_with_token,
    is_password_reset_token_valid,
    create_phone_otp,
    verify_phone_otp,
    get_phone_verification_status,
    get_admin_statistics,
    get_all_users,
    get_admin_requests,
    get_admin_reports,
    resolve_admin_report,
    create_report,
    take_admin_report_action,
    restore_admin_request,
    restore_user,
    suspend_user,
    ban_user,
    get_notifications,
    get_unread_notification_count,
    get_unread_rating_count,
    mark_notification_read,
    mark_all_notifications_read,
    mark_rating_notifications_read,

    get_journey_request,
    update_journey_status,
    update_journey_location,
    get_request_messages,
    send_request_message,
    get_user_skills,
    add_user_skill,
    delete_user_skill,
    
    
)

from email_config import (
    send_verification_email,
    send_password_reset_email,
)
from sms_config import send_phone_otp


# =========================================================
# LOCATION GEOCODING
# =========================================================

def geocode_location(location_text):
    """
    Converts a location name into approximate latitude and longitude.
    Used for area-search fallback.
    """

    if not location_text or not location_text.strip():
        return None

    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": location_text.strip(),
                "format": "json",
                "limit": 1,
                "countrycodes": "in",
            },
            headers={
                "User-Agent": "Neki Community Help Platform"
            },
            timeout=5,
        )

        response.raise_for_status()
        results = response.json()

        if not results:
            return None

        return (
            float(results[0]["lat"]),
            float(results[0]["lon"]),
        )

    except Exception:
        return None


def reverse_geocode_area(latitude, longitude):
    """
    Converts a selected map point into a privacy-friendly
    area/locality name.

    Exact house numbers and street-level details are intentionally
    not used as the saved location label.
    """

    if latitude is None or longitude is None:
        return None

    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={
                "lat": latitude,
                "lon": longitude,
                "format": "json",
                "zoom": 16,
                "addressdetails": 1,
            },
            headers={
                "User-Agent": "Neki Community Help Platform"
            },
            timeout=5,
        )

        response.raise_for_status()

        result = response.json()
        address = result.get("address", {})

        area_parts = []

        for key in [
            "neighbourhood",
            "suburb",
            "city_district",
            "town",
            "city",
            "village",
        ]:

            value = address.get(key)

            if value and value not in area_parts:
                area_parts.append(value)

        state = address.get("state")

        if state and state not in area_parts:
            area_parts.append(state)

        if area_parts:
            return ", ".join(area_parts[:3])

        return result.get("display_name")

    except Exception:
        return None


@st.cache_data(ttl=60, show_spinner=False)
def get_driving_route(start_lat, start_lon, end_lat, end_lon):
    """Get road-route geometry, distance and ETA from OSRM."""
    try:
        url = (
            "https://router.project-osrm.org/route/v1/driving/"
            f"{start_lon},{start_lat};{end_lon},{end_lat}"
        )

        response = requests.get(
            url,
            params={
                "overview": "full",
                "geometries": "geojson",
            },
            timeout=10,
        )
        response.raise_for_status()

        data = response.json()
        routes = data.get("routes", [])

        if not routes:
            return None

        route = routes[0]
        coordinates = route["geometry"]["coordinates"]

        return {
            "coordinates": [
                (lat, lon) for lon, lat in coordinates
            ],
            "distance_km": route["distance"] / 1000,
            "duration_min": route["duration"] / 60,
        }

    except (requests.RequestException, KeyError, ValueError, TypeError):
        return None

neki_journey_map = components.declare_component(
    "neki_journey_map",
    path=str(Path(__file__).parent / "journey_map"),
)

neki_gps_tracker = components.declare_component(
    "neki_gps_tracker",
    path=str(Path(__file__).parent / "gps_tracker"),
)
# =========================================================
# PAGE CONFIG
# =========================================================

st.set_page_config(
    page_title="Neki",
    page_icon="🌱",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =========================================================
# LOAD NEKI CSS
# =========================================================

def load_neki_css():
    with open("assets/neki.css", "r", encoding="utf-8") as f:
        st.markdown(
            f"<style>{f.read()}</style>",
            unsafe_allow_html=True,
        )


load_neki_css()

try:
    import turso_compat
    turso_compat.render_timing_panel()   # no-op unless [debug] db_timing = true
except Exception:
    pass


# =========================================================
# PASSWORD RESET LINK
# =========================================================

reset_token = st.query_params.get("reset")

if reset_token:
    with st.container(key="password_reset_page"):

        # Validate the link BEFORE displaying password fields.
        try:
            token_is_valid = is_password_reset_token_valid(
                reset_token
            )
        except Exception:
            logging.exception(
                "Password-reset token validation failed."
            )
            token_is_valid = False

        if not token_is_valid:
            st.markdown("## Reset your Neki password")

            st.error(
                "This password-reset link has expired, "
                "has already been used, or is invalid."
            )

            st.write(
                "For your security, reset links expire after "
                "one hour and can only be used once."
            )

            st.info(
                "Please return to Login and request a new "
                "password-reset link."
            )

            if st.button(
                "← Back to Login",
                key="expired_reset_back_to_login",
                use_container_width=True,
            ):
                st.query_params.clear()
                st.session_state["page"] = "Login"
                st.rerun()

        else:
            st.markdown("## Reset your Neki password")
            st.write("Create a new password for your account.")

            with st.form("password_reset_form"):
                new_password = st.text_input(
                    "New Password",
                    type="password",
                    key="reset_new_password",
                )

                confirm_password = st.text_input(
                    "Confirm New Password",
                    type="password",
                    key="reset_confirm_password",
                )

                reset_submitted = st.form_submit_button(
                    "Reset Password",
                    type="primary",
                    use_container_width=True,
                )

            if reset_submitted:
                if not new_password or not confirm_password:
                    st.error(
                        "Please complete both password fields."
                    )

                elif new_password != confirm_password:
                    st.error("The passwords do not match.")

                elif len(new_password) < 8:
                    st.error(
                        "Your password must contain at least "
                        "8 characters."
                    )

                else:
                    try:
                        reset_success = reset_password_with_token(
                            reset_token,
                            new_password,
                        )

                        if reset_success:
                            st.query_params.clear()

                            st.session_state["page"] = "Login"
                            st.session_state["login_message"] = (
                                "Your password has been reset "
                                "successfully. Please log in "
                                "using your new password."
                            )

                            st.rerun()

                        else:
                            st.error(
                                "This link is no longer valid. "
                                "It may have expired or already "
                                "been used. Please request a new "
                                "reset link."
                            )

                    except Exception:
                        logging.exception(
                            "Password-reset submission failed."
                        )
                        st.error(
                            "We couldn't reset your password "
                            "right now. Please try again later."
                        )

            if st.button(
                "Back to Login",
                key="reset_back_to_login",
            ):
                st.query_params.clear()
                st.session_state["page"] = "Login"
                st.rerun()

    st.stop()


# =========================================================
# EMAIL VERIFICATION LINK
# =========================================================

verification_token = st.query_params.get("verify")

if verification_token:
    verification_result = verify_email_token(verification_token)

    if verification_result:
        st.success("Your email has been verified successfully! 🎉")
        st.info("You can now log in to your Neki account.")

    else:
        st.error(
            "This verification link is invalid or has expired."
        )

    # Remove the verification token from the URL
    st.query_params.clear()

    st.stop()

# =========================================================
# BROWSER LOGIN STORAGE
# =========================================================

# Every browser tab gets its own identifier.
# This is important because Duplicate Tab can copy
# sessionStorage from the original tab.

def _ensure_browser_tab_id():

    components.html(
        """
        <script>
        (() => {

            const parentWindow = window.parent;

            // IMPORTANT:
            // The URL is NOT the source of truth.
            // A copied/new tab can inherit the URL.
            // window.name belongs to the browsing context.
            let tabId = parentWindow.name;

            // New browser tab/window:
            // create a completely new ID.
            if (
                !tabId ||
                !tabId.startsWith("neki-tab-")
            ) {

                tabId =
                    "neki-tab-" +
                    crypto.randomUUID();

                parentWindow.name = tabId;
            }

            const url = new URL(
                parentWindow.location.href
            );

            // Keep URL synchronized with THIS tab's ID.
            // If another tab's URL was copied here,
            // overwrite it with this tab's own ID.
            if (
                url.searchParams.get("neki_tab")
                !== tabId
            ) {

                url.searchParams.set(
                    "neki_tab",
                    tabId
                );

                parentWindow.history.replaceState(
                    {},
                    "",
                    url.toString()
                );

                parentWindow.location.reload();
            }

        })();
        </script>
        """,
        height=0,
        width=0,
    )

    # Read the ID only AFTER JavaScript has placed
    # this tab's own ID into the URL.
    current_id = st.query_params.get(
        "neki_tab"
    )

    if (
        not current_id
        or not current_id.startswith(
            "neki-tab-"
        )
    ):
        st.stop()

    return current_id


TAB_INSTANCE_ID = _ensure_browser_tab_id()

session_storage = SessionStorage()

# Active login session key for THIS browser tab only.
TAB_SESSION_KEY = f"neki_tab_session_{TAB_INSTANCE_ID}"


# Persistent remembered-account storage.
# CookieManager survives browser/tab closing and reopening.
if "_neki_cookie_manager" not in st.session_state:
    st.session_state["_neki_cookie_manager"] = stx.CookieManager(
        key="neki_cookie_manager"
    )

cookie_manager = st.session_state["_neki_cookie_manager"]

# =========================================================
# SESSION STATE
# =========================================================

defaults = {
    "logged_in": False,
    "user_id": None,
    "user_role": "User",
    "page": "Landing",
    "post_login_page": None,
    "theme": "dark",
    "user_name": "Neighbour",
    "persistent_login_checked": False,
    "browser_storage_checked": False,
    "browser_storage_attempts": 0,
    "tab_storage_attempts": 0,
    "remembered_accounts": [],
    "show_account_chooser": False,
    "profile_view_user_id": None,
    "profile_return_page": "My Requests",
    "profile_view_request_id": None,
    "profile_is_public": False,
    "request_status_id": None,
    "request_status_return_page": "My Requests",
    "request_latitude": None,
    "request_longitude": None,
    "request_map_latitude": 20.5937,
    "request_map_longitude": 78.9629,
    "request_map_zoom": 5,
    "request_location_text": "",
    "selected_map_request_id": None,
    "notification_last_checked": 0,
    "notification_unread_count": 0,
    "rating_unread_count": 0,
    "new_notification_alert": False,
    "new_rating_alert": False,
    "notification_alert_message": "",
    "notification_alert_icon": "🔔",
    "global_refresh_last_run": 0,
    "scroll_to_top": False,
}

for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value

# =========================================================
# BROWSER LOGIN HELPERS
# =========================================================


REMEMBERED_ACCOUNT_COOKIE_PREFIX = "neki_remembered_account_"
REMEMBERED_ACCOUNT_MAX_AGE = 30 * 24 * 60 * 60


def remembered_account_cookie(user_id):
    return f"{REMEMBERED_ACCOUNT_COOKIE_PREFIX}{user_id}"


def save_remembered_account(account):

    if not account or not account.get("user_id"):
        return

    cookie_manager.set(
        remembered_account_cookie(account["user_id"]),
        json.dumps(account),
        key=f"remembered_account_save_{account['user_id']}",
        path="/",
        max_age=REMEMBERED_ACCOUNT_MAX_AGE,
        same_site="lax",
    )

    accounts = st.session_state.get(
        "remembered_accounts",
        []
    )

    updated_accounts = [
        item
        for item in accounts
        if item.get("user_id") != account["user_id"]
    ]

    updated_accounts.append(account)

    st.session_state.remembered_accounts = updated_accounts


def remove_remembered_account(user_id):

    if not user_id:
        return

    cookie_name = remembered_account_cookie(user_id)

    # CookieManager can sometimes not have the cookie
    # in its current in-memory cookie dictionary even
    # though the account exists in session state.
    # Never let logout crash because of that.
    try:
        raw_cookies = cookie_manager.get_all(
            key=f"remembered_accounts_before_delete_{user_id}"
        )

        if (
            isinstance(raw_cookies, dict)
            and cookie_name in raw_cookies
        ):
            cookie_manager.delete(
                cookie_name,
                key=f"remembered_account_delete_{user_id}",
            )

    except (KeyError, TypeError, AttributeError):
        # Cookie is already absent from CookieManager.
        # Continue logout normally.
        pass

    accounts = st.session_state.get(
        "remembered_accounts",
        []
    )

    st.session_state.remembered_accounts = [
        item
        for item in accounts
        if item.get("user_id") != user_id
    ]

def load_remembered_accounts():

    raw_cookies = cookie_manager.get_all(
        key="remembered_accounts_get_all"
    )

    # CookieManager may initially return {} before
    # the browser has returned the actual cookies.
    # Do NOT treat {} as "no remembered accounts".
    if raw_cookies is None:
        return None

    if not isinstance(raw_cookies, dict):
        return None

    if raw_cookies == {}:
        return None

    accounts = []

    for cookie_name, raw_value in raw_cookies.items():

        if not cookie_name:
            continue

        if not cookie_name.startswith(
            REMEMBERED_ACCOUNT_COOKIE_PREFIX
        ):
            continue

        try:

            if isinstance(raw_value, str):
                account = json.loads(raw_value)

            elif isinstance(raw_value, dict):
                account = raw_value

            else:
                continue

            if (
                isinstance(account, dict)
                and account.get("user_id")
                and account.get("persistent_token")
            ):
                accounts.append(account)

        except Exception:
            continue

    return accounts  


def restore_logged_in_user(user):
    st.session_state.logged_in = True
    st.session_state.user_id = user["id"]
    st.session_state.user_name = user["name"]
    st.session_state.user_role = user["role"]
    st.session_state.page = "Dashboard"


# =========================================================
# RESTORE TAB / BROWSER LOGIN
# =========================================================

@st.fragment(run_every="0.5s")
def restore_browser_login():

    if (
        st.session_state.logged_in
        or st.session_state.persistent_login_checked
    ):
        return

   

    # =====================================================
    # 1. RESTORE THIS TAB'S ACTIVE SESSION
    # =====================================================

    tab_token = session_storage.getItem(
        TAB_SESSION_KEY
    )

    # SessionStorage may need a few reruns after a
    # browser refresh before the value becomes available.
    # Do NOT fall back to remembered accounts too early.

    if tab_token is None:

        st.session_state.tab_storage_attempts += 1

        if st.session_state.tab_storage_attempts < 10:
            return

    else:

        # SessionStorage has responded.
        st.session_state.tab_storage_attempts = 0

        if tab_token:

            user = get_user_from_session(
                tab_token
            )

            if user:

                restore_logged_in_user(user)

                st.session_state.persistent_login_checked = True
                st.session_state.browser_storage_checked = True

                st.rerun()

            # Token exists but is invalid/expired.
            session_storage.deleteItem(
                TAB_SESSION_KEY
            )

    # =====================================================
    # 2. READ PERSISTENT REMEMBERED ACCOUNTS
    # =====================================================

    remembered_accounts = load_remembered_accounts()

    if remembered_accounts is None:

        st.session_state.browser_storage_attempts += 1

        if (
            st.session_state.browser_storage_attempts
            >= 10
        ):
            st.session_state.persistent_login_checked = True
            st.session_state.browser_storage_checked = True

        return

    st.session_state.browser_storage_attempts = 0

    # =====================================================
    # 3. VALIDATE EVERY REMEMBERED ACCOUNT
    # =====================================================

    valid_accounts = []

    for account in remembered_accounts:

        persistent_token = account.get(
            "persistent_token"
        )

        if not persistent_token:
            continue

        user = get_user_from_session(
            persistent_token
        )

        if user:

            valid_accounts.append({
                "user_id": user["id"],
                "name": user["name"],
                "email": user["email"],
                "persistent_token": persistent_token,
            })

        else:

            remove_remembered_account(
                account.get("user_id")
            )

    st.session_state.remembered_accounts = valid_accounts

    # =====================================================
    # 4. ONE ACCOUNT → AUTO LOGIN
    # =====================================================

    if len(valid_accounts) == 1:

        account = valid_accounts[0]

        user = get_user_from_session(
            account["persistent_token"]
        )

        if user:

            new_tab_token = create_login_session(
                user["id"]
            )

            session_storage.setItem(
                TAB_SESSION_KEY,
                new_tab_token
            )

            restore_logged_in_user(user)

            st.session_state.persistent_login_checked = True
            st.session_state.browser_storage_checked = True

            st.rerun()

    # =====================================================
    # 5. MULTIPLE ACCOUNTS → WELCOME BACK
    # =====================================================

    elif len(valid_accounts) > 1:

        st.session_state.show_account_chooser = True
        st.session_state.persistent_login_checked = True
        st.session_state.browser_storage_checked = True

        st.rerun()

    # =====================================================
    # 6. RESTORE CHECK COMPLETE
    # =====================================================

    st.session_state.persistent_login_checked = True
    st.session_state.browser_storage_checked = True


restore_browser_login()

# =========================================================
# REPORT UI
# =========================================================

def render_report_action(
    *,
    report_key,
    reported_user_id,
    request_id=None,
    report_type="Request",
):
    """
    Displays a clean report action for a user or request.
    """

    if reported_user_id == st.session_state.user_id:
        return

    show_key = f"show_report_{report_key}"

    # -----------------------------------------------------
    # REPORT BUTTON
    # -----------------------------------------------------

    if st.button(
        "🚨 Report",
        key=f"report_button_{report_key}",
        use_container_width=True,
    ):
        st.session_state[show_key] = True

    # -----------------------------------------------------
    # REPORT FORM
    # -----------------------------------------------------

    if st.session_state.get(show_key, False):

        title = (
            "🚨 Report this request"
            if report_type == "Request"
            else "🚨 Report this profile"
        )

        with st.container(border=True):

            st.markdown(
                f"### {title}"
            )

            reason = st.text_area(
                "Why are you reporting this?",
                placeholder="Please explain the issue clearly...",
                key=f"report_reason_{report_key}",
                height=140,
            )

            col1, col2 = st.columns(2)

            with col1:

                if st.button(
                    "Submit Report",
                    type="primary",
                    use_container_width=True,
                    key=f"submit_report_{report_key}",
                ):

                    if not reason.strip():

                        st.error(
                            "Please provide a reason."
                        )

                    else:

                        report_id = create_report(
                            reporter_id=st.session_state.user_id,
                            reported_user_id=reported_user_id,
                            request_id=request_id,
                            reason=reason,
                            report_type=report_type,
                        )

                        if report_id is None:

                            st.warning(
                                "You have already submitted a report for this "
                                "item. Our admin team will review it."
                            )

                        else:

                            st.session_state[show_key] = False

                            st.success(
                                "✓ Report submitted successfully. "
                                "Our admin team will review it."
                            )

                        st.rerun()

            with col2:

                if st.button(
                    "Cancel",
                    use_container_width=True,
                    key=f"cancel_report_{report_key}",
                ):

                    st.session_state[show_key] = False

                    st.rerun()

# =========================================================
# EMAIL VERIFICATION
# =========================================================

verification_token = st.query_params.get("verify")

if verification_token:

    verified = verify_email_token(verification_token)

    if verified:
        st.session_state.email_verification_message = (
            "Email verified successfully! You can now login. ✅"
        )
    else:
        st.session_state.email_verification_message = (
            "This verification link is invalid or has expired."
        )

    st.query_params.clear()
    st.session_state.page = "Login"
    st.rerun()        


# =========================================================
# HELPERS
# =========================================================

def format_request_age(created_at):
    """
    Returns a compact relative time for a help request.
    Example: Just now, 12 min ago, 4 hours ago, 2 days ago.
    """

    if not created_at:
        return ""

    try:
        created = datetime.strptime(
            str(created_at),
            "%Y-%m-%d %H:%M:%S",
        ).replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)

        seconds = max(
            0,
            int((now - created).total_seconds())
        )

    except (ValueError, TypeError):
        return ""

    if seconds < 60:
        return "Just now"

    minutes = seconds // 60

    if minutes < 60:
        return f"{minutes} min ago"

    hours = minutes // 60

    if hours < 24:
        return f"{hours} hr ago"

    days = hours // 24

    if days < 7:
        return f"{days} day ago" if days == 1 else f"{days} days ago"

    weeks = days // 7

    if weeks < 5:
        return f"{weeks} week ago" if weeks == 1 else f"{weeks} weeks ago"

    return created.strftime("%d %b %Y")

def go_to(page):

    if page == "Request Help" and st.session_state.page != "Request Help":

        st.session_state["request_latitude"] = None
        st.session_state["request_longitude"] = None

        st.session_state["request_location_text"] = ""

        st.session_state["request_map_latitude"] = 20.5937
        st.session_state["request_map_longitude"] = 78.9629
        st.session_state["request_map_zoom"] = 5

    st.session_state.page = page

    st.rerun()

def scroll_to_top():
    st.markdown(
        """
        <script>
            const main = window.parent.document.querySelector(
                'section.main'
            );

            if (main) {
                main.scrollTo({
                    top: 0,
                    behavior: "instant"
                });
            }

            window.parent.scrollTo({
                top: 0,
                behavior: "instant"
            });
        </script>
        """,
        unsafe_allow_html=True,
    )

# =========================================================
# GLOBAL LIVE REFRESH
# =========================================================

# Pages where automatic full-app refreshing is safe.
# Form-heavy pages are intentionally excluded so user input
# is not unnecessarily interrupted while typing.
AUTO_REFRESH_PAGES = {
    "Dashboard",
    "Find Help",
    "My Requests",
    "Ratings",
    "Notifications",
    "Connection Profile",
    "Admin",
    "Request Status",
}


@st.fragment(run_every="5s")
def global_live_refresh():

    if not st.session_state.logged_in:
        return

    current_time = time.time()

    # -----------------------------------------------------
    # NOTIFICATION COUNTS
    # -----------------------------------------------------

    previous_notification_count = (
        st.session_state.notification_unread_count
    )

    previous_rating_count = (
        st.session_state.rating_unread_count
    )

    unread_notification_count = (
        get_unread_notification_count(
            st.session_state.user_id
        )
    )

    unread_rating_count = (
        get_unread_rating_count(
            st.session_state.user_id
        )
    )

    # -----------------------------------------------------
    # NEW NORMAL NOTIFICATION
    # -----------------------------------------------------

    if unread_notification_count > previous_notification_count:

        st.session_state.new_notification_alert = True

        notifications = get_notifications(
            st.session_state.user_id,
            limit=50,
        )

        for notification in notifications:

            if (
                notification["is_read"] == 0
                and notification["type"] != "rating_received"
            ):

                st.session_state.notification_alert_message = (
                    notification["message"]
                )

                st.session_state.notification_alert_icon = "🔔"

                break

    # -----------------------------------------------------
    # NEW RATING
    # -----------------------------------------------------

    if unread_rating_count > previous_rating_count:

        st.session_state.new_rating_alert = True

    # -----------------------------------------------------
    # UPDATE COUNTS
    # -----------------------------------------------------

    st.session_state.notification_unread_count = (
        unread_notification_count
    )

    st.session_state.rating_unread_count = (
        unread_rating_count
    )

    


global_live_refresh()



if st.session_state.get("new_notification_alert", False):

    st.toast(
        st.session_state.get(
            "notification_alert_message",
            "You have a new notification."
        ),
        icon=st.session_state.get(
            "notification_alert_icon",
            "🔔"
        )
    )

    st.session_state.new_notification_alert = False
    st.session_state.notification_alert_message = ""


if st.session_state.get("new_rating_alert", False):

    st.toast(
        "⭐ You received a new rating!",
        icon="⭐"
    )

    st.session_state.new_rating_alert = False




def open_connection_profile(request_id):
    """
    Opens the profile of the other person involved
    in an accepted help connection.
    """

    profile = get_connected_profile(
        request_id=request_id,
        viewer_id=st.session_state.user_id,
    )

    if profile is None:
        st.error(
            "This profile is not available for this connection."
        )
        return

    st.session_state.profile_view_user_id = profile["id"]
    st.session_state.profile_return_page = "My Requests"
    st.session_state.profile_view_request_id = request_id
    st.session_state.profile_is_public = False
    st.session_state.page = "Connection Profile"
    st.rerun()

def open_request_status(request_id, return_page="My Requests"):
    st.session_state.request_status_id = request_id
    st.session_state.request_status_return_page = return_page
    st.session_state.page = "Request Status"
    st.rerun()


def open_match_profile(request_id):
    """
    Opens the public profile used during the matching stage.
    No private contact information is shown.
    """

    profile = get_match_profile(
        request_id=request_id,
        viewer_id=st.session_state.user_id,
    )

    if profile is None:
        st.error(
            "This profile is no longer available for this request."
        )
        return

    st.session_state.profile_view_user_id = profile["id"]
    st.session_state.profile_view_request_id = request_id
    st.session_state.profile_is_public = True
    st.session_state.profile_return_page = st.session_state.page
    st.session_state.page = "Connection Profile"
    st.rerun()


def require_login(page):
    if not st.session_state.logged_in:
        st.session_state.page = "Login"
        st.session_state.login_message = (
            "Please login to access this feature."
        )
        st.rerun()
    else:
        go_to(page)

def landing_login():
    st.session_state.post_login_page = None
    st.session_state.page = "Login"
    st.rerun()


def landing_register():
    st.session_state.post_login_page = None
    st.session_state.page = "Register"
    st.rerun()


def landing_request_help():
    if not st.session_state.logged_in:
        st.session_state.post_login_page = "Request Help"
        st.session_state.page = "Login"
        st.session_state.login_message = (
            "Login or create an account to request help from your neighbours."
        )
        st.rerun()

    go_to("Request Help")


def landing_find_help():
    if not st.session_state.logged_in:
        st.session_state.post_login_page = "Find Help"
        st.session_state.page = "Login"
        st.session_state.login_message = (
            "Login or create an account to discover neighbours who need help."
        )
        st.rerun()

    go_to("Find Help")


def toggle_theme():
    if st.session_state.theme == "dark":
        st.session_state.theme = "light"
    else:
        st.session_state.theme = "dark"

    st.rerun()

def page_header(title, subtitle=None, show_back=True):
    top_left, top_right = st.columns([8, 1.4])

    with top_left:
        st.markdown(
            f'<div class="page-title">{title}</div>',
            unsafe_allow_html=True,
        )
        if subtitle:
            st.markdown(
                f'<div class="page-subtitle">{subtitle}</div>',
                unsafe_allow_html=True,
            )

    with top_right:
        if show_back and st.session_state.page != "Dashboard":
            if st.button(
                "← Back",
                key=f"back_{st.session_state.page}",
                use_container_width=True,
            ):
                go_to("Dashboard")




st.markdown(
    f'<div class="neki-theme {st.session_state.theme}"></div>',
    unsafe_allow_html=True,
)

theme_class = st.session_state.theme

st.markdown(
    f"""
    <style>
        :root {{
            color-scheme: {theme_class};
        }}
    </style>
    """,
    unsafe_allow_html=True,
)

# =========================================================
# TOP NAVIGATION
# =========================================================
#
# Navigation is now handled entirely through the Neki sidebar.
# Keeping a second navigation bar here created duplicate
# navigation and reduced the available content space.
#
# Theme control has also been moved into the sidebar.
# =========================================================


# =========================================================
# SIDEBAR
# =========================================================

with st.sidebar:

    st.markdown(
        """
        <div class="sidebar-brand">
            <div class="sidebar-brand-mark">N</div>
            <div class="sidebar-brand-content">
                <div class="sidebar-brand-name">
                    Neki
                </div>
                <div class="sidebar-brand-line">
                    Neighbours helping neighbours
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    

    st.divider()

    if st.session_state.logged_in:

        st.markdown(
            '<div class="sidebar-section">Workspace</div>',
            unsafe_allow_html=True,
        )

        rating_label = "⭐  My Ratings"

        if st.session_state.rating_unread_count > 0:
            rating_label += "  🔴"

        sidebar_items = [
            ("🏠  Dashboard", "Dashboard"),
            ("🙋  Request Help", "Request Help"),
            ("🤝  Find Help", "Find Help"),
            ("📋  My Requests", "My Requests"),
            (rating_label, "Ratings"),
        ]

        unread_count = st.session_state.notification_unread_count

        notification_label = "🔔  Notifications"

        if unread_count > 0:
            notification_label += f"  ({unread_count})"

        sidebar_items.append(
            (notification_label, "Notifications")
        )

        for label, page in sidebar_items:
            if st.button(
                label,
                key=f"side_{page}",
                use_container_width=True,
                type="primary" if st.session_state.page == page else "secondary",
            ):
                go_to(page)

        st.markdown(
            '<div class="sidebar-section">Account</div>',
            unsafe_allow_html=True,
        )

        if st.button(
            "👤  Profile",
            key="side_profile",
            use_container_width=True,
            type="primary" if st.session_state.page == "Profile" else "secondary",
        ):
            go_to("Profile")

        if st.session_state.user_role == "Admin":

            st.markdown(
                '<div class="sidebar-section">Administration</div>',
                unsafe_allow_html=True,
            )

            if st.button(
                "🛡️  Admin Panel",
                key="side_admin",
                use_container_width=True,
                type="primary" if st.session_state.page == "Admin" else "secondary",
            ):
                go_to("Admin")

        # -----------------------------------------------------
        # THEME
        # -----------------------------------------------------

        if st.button(
            "Theme",
            key="side_theme",
            icon=":material/dark_mode:" if st.session_state.theme == "dark" else ":material/light_mode:",
            icon_position="left",
            use_container_width=True,
        ):
            toggle_theme()

        st.markdown(
            f"""
            <div class="sidebar-user">
                <div class="sidebar-user-name">👋 {st.session_state.user_name}</div>
                <div class="sidebar-user-role">{st.session_state.user_role} account</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("")

        if st.button(
            "🚪  Logout",
            key="side_logout",
            use_container_width=True,
        ):

            # -----------------------------------------------------
            # DELETE ONLY THIS TAB'S ACTIVE SESSION
            # -----------------------------------------------------

            saved_token = session_storage.getItem(
                TAB_SESSION_KEY
            )

            if saved_token:

                delete_login_session(
                    saved_token
                )

            session_storage.deleteItem(
                TAB_SESSION_KEY
            )

            # -----------------------------------------------------
            # IMPORTANT:
            # Logout ONLY this browser tab.
            #
            # Do NOT delete the persistent remembered account.
            # Another tab may still be logged into the same account.
            # -----------------------------------------------------

            current_user_id = st.session_state.user_id

            # Keep the remembered account/token intact.
            # It is browser-wide and may be needed by another tab.
            

            st.session_state.logged_in = False
            st.session_state.user_id = None
            st.session_state.user_role = "User"
            st.session_state.user_name = "Neighbour"
            st.session_state.page = "Login"

            st.session_state.persistent_login_checked = True
            
            st.rerun()

    else:

        st.markdown(
            '<div class="sidebar-section">Get Started</div>',
            unsafe_allow_html=True,
        )

        if st.button(
            "Login",
            key="side_login",
            use_container_width=True,
            type="primary" if st.session_state.page == "Login" else "secondary",
        ):
            go_to("Login")

        if st.button(
            "Create Account",
            key="side_register",
            use_container_width=True,
            type="primary" if st.session_state.page == "Register" else "secondary",
        ):
            go_to("Register")

        st.html(
            """
            <div class="sidebar-user landing-community-card">

                <div class="landing-community-icon">
                    N
                </div>

                <div class="landing-community-content">
                    <div class="sidebar-user-name">
                        Community first.
                    </div>

                    <div class="sidebar-user-role">
                        Small acts. Stronger neighbourhoods.
                    </div>
                </div>

            </div>
            """
        )
        if st.button(
            "Theme",
            key="side_theme_public",
            icon=":material/dark_mode:" if st.session_state.theme == "dark" else ":material/light_mode:",
            icon_position="left",
            use_container_width=True,
        ):
            toggle_theme()


# =========================================================
# LANDING PAGE
# =========================================================

if st.session_state.page == "Landing":

    render_landing_page(
        on_login=landing_login,
        on_register=landing_register,
        on_request_help=landing_request_help,
        on_find_help=landing_find_help,
    )


# =========================================================
# LOGIN
# =========================================================

elif st.session_state.page == "Login":

    # =========================================================
    # LOGIN — WELCOME HEADER
    # =========================================================

    login_intro = st.container(
        key="login_intro"
    )

    with login_intro:

        st.html(
            """
            <div class="auth-card auth-login-hero">

                <div class="auth-hero-mark">
                    N
                </div>

                <div class="auth-eyebrow">
                    YOUR NEKI SPACE
                </div>

                <div class="auth-title">
                    Welcome back 👋
                </div>

                <div class="auth-subtitle">
                    Your neighbourhood is waiting for you.
                </div>

                <div class="auth-description">
                    Sign in to ask for help, offer help, and stay connected
                    with the people around you.
                </div>

            </div>
            """
        )

    if "login_message" in st.session_state:
        st.info(st.session_state.login_message)
        del st.session_state.login_message

    if "email_verification_message" in st.session_state:
        st.info(st.session_state.email_verification_message)
        del st.session_state.email_verification_message  

    if st.session_state.get(
        "show_account_chooser",
        False
    ):

        # =====================================================
        # REMEMBERED ACCOUNTS
        # =====================================================

        accounts_panel = st.container(
            key="remembered_accounts_panel"
        )

        with accounts_panel:

            st.html(
                """
                <div class="auth-section-heading">

                    <div class="auth-section-kicker">
                        QUICK SIGN IN
                    </div>

                    <div class="auth-section-title">
                        Choose your account
                    </div>

                    <div class="auth-section-text">
                        Your remembered accounts are ready.
                        Pick one to continue instantly.
                    </div>

                </div>
                """
            )

        remembered_accounts = (
            st.session_state.get(
                "remembered_accounts",
                []
            )
        )
        # Immediate browser-side feedback for remembered-account login.
        # This appears before Streamlit finishes the login round-trip.
        components.html(
            """
            <script>
            (() => {
                const parent = window.parent;

                // After this long, tell the user the sign-in is slow.
                // The lock is NOT released: the server may still be
                // finishing the first login.
                const SLOW_NOTICE_MS = 30000;

                function showLoginLoading(button) {
                    if (
                        !button ||
                        button.dataset.nekiLoginLoading === "1"
                    ) {
                        return;
                    }

                    button.dataset.nekiLoginLoading = "1";
                    button.disabled = true;
                    
                    // Lock ONLY the other controls of the remembered-accounts
                    // panel (the other account buttons and "Login with
                    // another account") so a second click cannot interfere
                    // with the login that is already in progress.
                    const others = Array.from(
                        parent.document.querySelectorAll(
                            '.st-key-remembered_accounts_panel ' +
                            '[class*="st-key-remembered_account_"] button, ' +
                            '.st-key-remembered_accounts_panel ' +
                            '.st-key-login_another_account button'
                        )
                    ).filter((b) => b !== button && !b.disabled);

                    others.forEach((b) => { b.disabled = true; });

                    let watch = null;
                    let timer = null;

                    function unlock() {
                        clearInterval(watch);
                        clearTimeout(timer);
                        others.forEach((b) => { b.disabled = false; });
                    }

                    // The server answered by redrawing the page without the
                    // clicked account (login finished, or its expired
                    // session was removed): release the other controls.
                    watch = setInterval(() => {
                        if (!parent.document.contains(button)) {
                            unlock();
                        }
                    }, 500);

                    // Still no answer: keep everything locked (a second
                    // attempt could compete with the first one) and tell
                    // the user what to do. Refreshing the page starts a
                    // new Streamlit session, which the old attempt cannot
                    // change.
                    timer = setTimeout(() => {
                        if (parent.document.contains(button)) {
                            button.innerHTML = button.innerHTML.replace(
                                "Signing you in...",
                                "Still working... refresh the page if this does not finish"
                            );
                        }
                    }, SLOW_NOTICE_MS);

                    button.innerHTML =
                        '<span style="display:inline-flex;align-items:center;gap:9px;">' +
                        '<span style="' +
                        'width:15px;' +
                        'height:15px;' +
                        'border:2px solid rgba(255,255,255,.28);' +
                        'border-top-color:#55D88A;' +
                        'border-radius:50%;' +
                        'display:inline-block;' +
                        'animation:nekiLoginSpin .75s linear infinite;' +
                        '"></span>' +
                        '<span>Signing you in...</span>' +
                        '</span>';

                    if (
                        !parent.document.getElementById(
                            "neki-login-spin-style"
                        )
                    ) {
                        const style =
                            parent.document.createElement("style");

                        style.id = "neki-login-spin-style";

                        style.textContent = `
                            @keyframes nekiLoginSpin {
                                to {
                                    transform: rotate(360deg);
                                }
                            }
                        `;

                        parent.document.head.appendChild(style);
                    }
                }

                function attach() {
                    const buttons =
                        parent.document.querySelectorAll(
                            'button[data-testid="stBaseButton-secondary"]'
                        );

                    buttons.forEach((button) => {

                        const text =
                            (button.innerText || "").trim();

                        if (
                            !text ||
                            text.includes(
                                "Login with another account"
                            ) ||
                            !text.includes("·")
                        ) {
                            return;
                        }

                        if (
                            button.dataset.nekiLoginBound === "1"
                        ) {
                            return;
                        }

                        button.dataset.nekiLoginBound = "1";

                        button.addEventListener(
                            "click",
                            () => {
                                showLoginLoading(button);
                            },
                            { once: true }
                        );
                    });
                }

                attach();

                const observer =
                    new MutationObserver(attach);

                observer.observe(
                    parent.document.body,
                    {
                        childList: true,
                        subtree: true
                    }
                );

                setTimeout(attach, 100);
                setTimeout(attach, 500);
            })();
            </script>
            """,
            height=0,
            width=0,
        )

        for account in remembered_accounts:

            account_label = (
                f"👤  {account['name']}  ·  "
                f"{account['email']}"
            )

            if accounts_panel.button(
                account_label,
                key=f"remembered_account_{account['user_id']}",
                use_container_width=True,
            ):

                user = get_user_from_session(
                    account["persistent_token"]
                )

                if user:

                    new_tab_token = create_login_session(
                        user["id"]
                    )

                    # Save the new session for THIS browser tab.
                    session_storage.setItem(
                        TAB_SESSION_KEY,
                        new_tab_token,
                    )

                    # Keep the login state in this Streamlit session.
                    restore_logged_in_user(user)

                    st.session_state.show_account_chooser = False

                    st.session_state.persistent_login_checked = True
                    st.session_state.browser_storage_checked = True
                    
                    # Same finish as the normal login form: give the browser
                    # a moment to write this tab's session token, then
                    # redraw the app as logged in.
                    time.sleep(1.5)
                    st.rerun()

                else:

                    remove_remembered_account(
                        account["user_id"]
                    )

                    st.rerun()

        with accounts_panel:

            st.html(
                """
                <div class="auth-or">
                    <span></span>
                    <small>or</small>
                    <span></span>
                </div>
                """
            )

        if accounts_panel.button(
            "＋  Login with another account",
            key="login_another_account",
            use_container_width=True,
        ):

            st.session_state.show_account_chooser = False
            st.rerun()     

    else:

        # =========================================================
        # NORMAL LOGIN FORM
        # =========================================================    
        login_form_panel = st.container(
            key="login_form_panel"
        )

        col1, col2, col3 = login_form_panel.columns(
            [1, 1.6, 1]
        )

        with col2:

            email = st.text_input(
                "Email",
                placeholder="you@example.com",
                key="login_email",
                type="default",
            )

            password = st.text_input(
                "Password",
                type="password",
                placeholder="Enter your password",
                key="login_password",
            )
            
            
            if st.button(
                "Forgot password?",
                key="open_forgot_password",
                type="tertiary",
            ):
                st.session_state.page = "Forgot Password"
                st.rerun()



            if st.button(
                "Sign in  →",
                key="login_submit",
                type="primary",
                use_container_width=True,
            ):

                if not email or not password:

                    st.error(
                        "Please enter your email and password."
                    )

                else:

                    user = verify_login(
                        email,
                        password
                    )

                    if isinstance(user, tuple) and user[0] == "SUSPENDED":

                        _, suspension_until, moderation_reason = user

                        st.warning(
                            "⚠️ Your account is temporarily suspended."
                        )

                        if suspension_until:
                            st.info(
                                f"Your suspension ends at: {suspension_until}"
                            )

                        if moderation_reason:
                            st.info(
                                f"Reason: {moderation_reason}"
                            )


                    elif isinstance(user, tuple) and user[0] == "BANNED":

                        _, _, moderation_reason = user

                        st.error(
                            "🚫 Your account has been permanently banned."
                        )

                        if moderation_reason:
                            st.info(
                                f"Reason: {moderation_reason}"
                            )


                    elif user:

                        if not user["email_verified"]:

                            st.warning(
                                "Please verify your email before logging in."
                            )

                            st.info(
                                "Check your inbox for the NeighbourHelp "
                                "verification email."
                            )

                        else:
                            # -----------------------------------------------------
                            # CREATE A UNIQUE SESSION FOR THIS TAB
                            # -----------------------------------------------------

                            session_token = create_login_session(
                                user["id"]
                            )

                            session_storage.setItem(
                                TAB_SESSION_KEY,
                                session_token,
                            )

                            # -----------------------------------------------------
                            # CREATE A SEPARATE LONG-LIVED REMEMBERED LOGIN
                            # -----------------------------------------------------

                            persistent_token = create_login_session(
                                user["id"]
                            )

                            remembered_account = {
                                "user_id": user["id"],
                                "name": user["name"],
                                "email": user["email"],
                                "persistent_token": persistent_token,
                            }

                            save_remembered_account(
                                remembered_account
                            )

                        

                            st.session_state.logged_in = True
                            st.session_state.user_id = user["id"]
                            st.session_state.user_name = user["name"]
                            st.session_state.user_role = user["role"]
                            st.session_state.page = (
                                st.session_state.get("post_login_page")
                                or "Dashboard"
                            )

                            st.session_state.post_login_page = None

                            st.session_state.persistent_login_checked = True
                            st.session_state.browser_storage_checked = True
                            st.session_state.show_account_chooser = False
                            

                            st.success("Login successful!")

                            time.sleep(1.5)

                            st.rerun()


                    else:

                        st.error(
                            "Invalid email or password."
                        )
    

   

    # =========================================================
    # EMAIL VERIFICATION
    # =========================================================

    verification_panel = st.container(
        key="verification_panel"
    )

    with verification_panel:

        st.html(
            """
            <div class="verification-card">

                <div class="verification-icon">
                    ✉
                </div>

                <div class="verification-title">
                    Didn't receive your verification email?
                </div>

                <div class="verification-text">
                    Enter your registered email and we'll send
                    you a fresh verification link.
                </div>

            </div>
            """
        )

    resend_email = verification_panel.text_input(
        "Registered email",
        placeholder="you@example.com",
        key="resend_email",
    )

    if verification_panel.button(
        "📧  Resend verification email",
        key="resend_verification",
        use_container_width=True,
    ):

        resend_user = get_user_by_email(
            resend_email.strip().lower()
        )

        if resend_user is None:

            verification_panel.error(
                "No account was found with this email."
            )

        elif resend_user["email_verified"]:

            verification_panel.success(
                "Your email is already verified. "
                "You can login."
            )

        else:

            new_token = create_verification_token(
                resend_user["id"]
            )

            try:

                send_verification_email(
                    recipient=resend_user["email"],
                    token=new_token,
                )

                verification_panel.success(
                    "Verification email sent! 📧"
                )

            except Exception as e:

                verification_panel.error(
                    f"Unable to send the verification email: {e}"
                )

    verification_panel.caption(
        "Your account details are securely verified "
        "through the database."
    )
    


elif st.session_state.page == "Forgot Password":

    forgot_page = st.container(key="forgot_password_page")

    with forgot_page:
        page_header(
            "Forgot Password",
            "Reset your password to get back to Neki.",
            show_back=False,
        )

        st.write(
            "Enter your registered email address. "
            "If your account is eligible, we'll send you "
            "a password-reset link."
        )

        with st.form("forgot_password_form"):
            reset_email = st.text_input(
                "Email address",
                placeholder="you@example.com",
                key="forgot_password_email",
            )

            forgot_submitted = st.form_submit_button(
                "Send Reset Link",
                type="primary",
                use_container_width=True,
            )

        if forgot_submitted:
            if not reset_email.strip():
                st.error("Please enter your email address.")
            else:
                try:
                    reset_email_token = create_password_reset_token(
                        reset_email.strip()
                    )

                    if reset_email_token:
                        send_password_reset_email(
                            reset_email.strip(),
                            reset_email_token,
                        )

                except Exception:
                    import logging
                    logging.exception(
                        "Password-reset email processing failed."
                    )

                st.success(
                    "If an eligible account exists for that email, "
                    "a password-reset link will be sent. "
                    "Please check your inbox."
                )

        if st.button(
            "← Back to Login",
            key="forgot_back_to_login",
            use_container_width=True,
        ):
            st.session_state.page = "Login"
            st.rerun()


        

# =========================================================
# REGISTER
# =========================================================

elif st.session_state.page == "Register":

    page_header(
        "Create your account",
        "Join your community and start helping others.",
        show_back=True,
    )

    register_shell = st.container(
        key="register_shell"
    )

    # -----------------------------------------------------
    # REGISTER INTRO
    # -----------------------------------------------------

    with register_shell:

        st.html(
            """
            <div class="register-hero">

                <div class="register-mark">
                    N
                </div>

                <div class="register-eyebrow">
                    WELCOME TO NEKI
                </div>

                <div class="register-title">
                    Join your neighbourhood ✨
                </div>

                <div class="register-subtitle">
                    One account to ask for help, offer help,
                    and build trust around you.
                </div>

            </div>
            """
        )
    register_cols = register_shell.columns(
        [0.55, 3.0, 0.55]
    )

    register_card = register_cols[1].container(
        key="register_form_card"
    )

    # -----------------------------------------------------
    # YOUR DETAILS
    # -----------------------------------------------------

    with register_card:

        st.html(
            """
            <div class="register-section">

                <div class="register-section-kicker">
                    01 · YOUR DETAILS
                </div>

                <div class="register-section-title">
                    Tell us a little about you
                </div>

                <div class="register-section-text">
                    We'll use this to identify you within the
                    Neki community.
                </div>

            </div>
            """
        )

    name = register_card.text_input(
        "Full Name",
        placeholder="Enter your full name",
        key="register_name",
    )

    email = register_card.text_input(
        "Email",
        placeholder="you@example.com",
        key="register_email",
    )
    phone = register_card.text_input(
        "Phone Number",
        placeholder="+91XXXXXXXXXX",
        key="register_phone",
    )

    # -----------------------------------------------------
    # SECURITY
    # -----------------------------------------------------

    with register_card:

        st.html(
            """
            <div class="register-section register-section-spaced">

                <div class="register-section-kicker">
                    02 · ACCOUNT SECURITY
                </div>

                <div class="register-section-title">
                    Keep your account secure
                </div>

            </div>
            """
        )

    password = register_card.text_input(
        "Password",
        type="password",
        placeholder="Create a password",
        key="register_password",
    )

    with register_card:

        st.html(
            """
            <div class="password-guide">

                <div class="password-guide-title">
                    Password requirement
                </div>

                <div class="password-rule">
                    <span>✓</span>
                    At least 6 characters
                </div>

                <div class="password-rule">
                    <span>•</span>
                    Choose a password that's easy for you to remember
                    but difficult for others to guess.
                </div>

            </div>
            """
        )

    confirm_password = register_card.text_input(
        "Confirm Password",
        type="password",
        placeholder="Re-enter your password",
        key="register_confirm_password",
    )

    # -----------------------------------------------------
    # COMMUNITY
    # -----------------------------------------------------

    with register_card:

        st.html(
            """
            <div class="register-section register-section-spaced">

                <div class="register-section-kicker">
                    03 · YOUR COMMUNITY
                </div>

                <div class="register-section-title">
                    Where are you based?
                </div>

                <div class="register-section-text">
                    This helps Neki connect you with nearby
                    requests and neighbours.
                </div>

            </div>
            """
        )

    location = register_card.text_input(
        "Neighbourhood / Location",
        placeholder="e.g. Rohini, Noida, Gurgaon",
        key="register_location",
    )

    with register_card:

        st.html(
            """
            <div class="register-location-note">
                📍 You can use your neighbourhood, locality,
                or city.
            </div>
            """
        )

    # -----------------------------------------------------
    # CREATE ACCOUNT
    # -----------------------------------------------------

    if register_card.button(
        "Create my Neki account  →",
        key="register_submit",
        type="primary",
        use_container_width=True,
    ):

        if (
            not name
            or not email
            or not phone
            or not password
            or not location
        ):

            register_card.error(
                "Please fill in all the required fields."
            )

        elif not phone.startswith("+"):

            register_card.error(
                "Please enter your phone number with country code, "
                "for example +91XXXXXXXXXX."
            )

        elif not phone[1:].isdigit():

            register_card.error(
                "Please enter a valid phone number."
            )    

        elif password != confirm_password:

            register_card.error(
                "Passwords do not match."
            )

        elif len(password) < 6:

            register_card.error(
                "Password must contain at least 6 characters."
            )

        else:

            success, token = register_user(
                name,
                email,
                password,
                location,
                phone,
            )

            if success:

                try:

                    send_verification_email(
                        recipient=email.strip().lower(),
                        token=token,
                    )

                    register_card.success(
                        "Account created successfully! 🎉"
                    )

                    register_card.info(
                        "We've sent a verification link to your email. "
                        "Please verify your email before logging in."
                    )

                    register_card.caption(
                        "The verification link expires in 24 hours."
                    )

                except Exception as e:

                    register_card.error(
                        f"Unable to send the verification email: {e}"
                    )

            else:

                register_card.error(token)


# =========================================================
# DASHBOARD
# =========================================================

elif st.session_state.page == "Dashboard":

    page_header(
        "Dashboard",
        "Your community activity at a glance.",
        show_back=False,
    )

    current_user = get_user_by_id(
        st.session_state.user_id
    )

    trust_score = (
        current_user["trust_score"]
        if current_user
        else 50
    )

    dashboard_stats = get_dashboard_stats(
        st.session_state.user_id
    )

    activities = get_recent_community_activity(
        limit=5
    )

    # -----------------------------------------------------
    # WELCOME
    # -----------------------------------------------------

    st.html(
        f"""
        <div class="dashboard-welcome">

            <div class="dashboard-welcome-main">

                <div class="dashboard-eyebrow">
                    YOUR NEKI SPACE
                </div>

                <div class="dashboard-welcome-title">
                    Welcome back, {st.session_state.user_name} 👋
                </div>

                <div class="dashboard-welcome-text">
                    Ask for help when you need it.
                    Offer help when you can.
                    Every small connection makes the community stronger.
                </div>

            </div>

            <div class="dashboard-welcome-badge">
                <span>🤝</span>
                <div>
                    <strong>Ask. Help. Connect.</strong>
                    <small>Your neighbourhood, together.</small>
                </div>
            </div>

        </div>
        """
    )

    # -----------------------------------------------------
    # STATS
    # -----------------------------------------------------

    stats = [
        (
            "📋",
            "My Requests",
            str(dashboard_stats["my_requests"]),
            "Requests you've created",
        ),
        (
            "🤝",
            "Help Given",
            str(dashboard_stats["help_given"]),
            "People you've helped",
        ),
        (
            "✓",
            "Completed",
            str(dashboard_stats["completed"]),
            "Successfully completed",
        ),
        (
            "🛡️",
            "Trust Score",
            f"{trust_score:.1f}",
            "Out of 100",
        ),
    ]

    st.html(
        '<div class="dashboard-section-label">YOUR ACTIVITY</div>'
    )

    stat_cols = st.columns(4)

    for col, (icon, title, number, caption) in zip(
        stat_cols,
        stats,
    ):
        with col:
            st.html(
                f"""
                <div class="dashboard-stat-card">

                    <div class="dashboard-stat-top">
                        <span class="dashboard-stat-icon">
                            {icon}
                        </span>
                        <span class="dashboard-stat-caption">
                            {caption}
                        </span>
                    </div>

                    <div class="dashboard-stat-number">
                        {number}
                    </div>

                    <div class="dashboard-stat-title">
                        {title}
                    </div>

                </div>
                """
            )

    # -----------------------------------------------------
    # QUICK ACTIONS
    # -----------------------------------------------------

    st.html(
        """
        <div class="dashboard-section-heading">
            <div>
                <div class="dashboard-section-label">
                    YOUR NEXT STEP
                </div>
                <div class="dashboard-section-title">
                    How would you like to help today?
                </div>
            </div>
        </div>
        """
    )

    action_col1, action_col2 = st.columns(2)

    with action_col1:

        st.html(
            """
            <div class="dashboard-action-card dashboard-action-help">

                <div class="dashboard-action-icon">
                    🙋
                </div>

                <div class="dashboard-action-content">

                    <div class="dashboard-action-title">
                        I need a hand
                    </div>

                    <div class="dashboard-action-text">
                        Ask your neighbours for a little help
                        when you need it.
                    </div>

                </div>

            </div>
            """
        )

        if st.button(
            "Ask for Help →",
            key="dashboard_request",
            type="primary",
            use_container_width=True,
        ):
            require_login("Request Help")

    with action_col2:

        st.html(
            """
            <div class="dashboard-action-card dashboard-action-helping">

                <div class="dashboard-action-icon">
                    🤝
                </div>

                <div class="dashboard-action-content">

                    <div class="dashboard-action-title">
                        I can help
                    </div>

                    <div class="dashboard-action-text">
                        See where someone nearby could use
                        an extra hand today.
                    </div>

                </div>

            </div>
            """
        )

        if st.button(
            "Find Someone to Help →",
            key="dashboard_find",
            type="primary",
            use_container_width=True,
        ):
            require_login("Find Help")

    # -----------------------------------------------------
    # RECENT COMMUNITY ACTIVITY
    # -----------------------------------------------------

    st.html(
        """
        <div class="dashboard-section-heading dashboard-activity-heading">
            <div>
                <div class="dashboard-section-label">
                    COMMUNITY
                </div>

                <div class="dashboard-section-title">
                    What's happening nearby
                </div>
            </div>

            <div class="dashboard-activity-count">
                Latest community updates
            </div>
        </div>
        """
    )

    if not activities:

        st.html(
            """
            <div class="dashboard-empty-state">

                <div class="dashboard-empty-icon">
                    🌱
                </div>

                <div class="dashboard-empty-title">
                    Your community is just getting started.
                </div>

                <div class="dashboard-empty-text">
                    New help requests and community activity
                    will appear here.
                </div>

            </div>
            """
        )

    else:

        for activity in activities:

            title = activity["title"]
            location = activity["location"]
            status = activity["status"]

            status_class = {
                "Pending": "status-pending",
                "Accepted": "status-accepted",
                "Help Provided": "status-accepted",
                "Completed": "status-completed",
            }.get(
                status,
                "status-accepted",
            )

            status_icon = {
                "Pending": "⏳",
                "Accepted": "🤝",
                "Help Provided": "🙌",
                "Completed": "✓",
            }.get(
                status,
                "•",
            )

            st.html(
                f"""
                <div class="dashboard-activity-card">

                    <div class="dashboard-activity-icon">
                        {status_icon}
                    </div>

                    <div class="dashboard-activity-content">

                        <div class="dashboard-activity-title">
                            {title}
                        </div>

                        <div class="dashboard-activity-meta">
                            📍 {location}
                        </div>

                    </div>

                    <div class="dashboard-activity-status">
                        <span class="status {status_class}">
                            {status}
                        </span>
                    </div>

                </div>
                """
            )


# =========================================================
# REQUEST HELP
# =========================================================

elif st.session_state.page == "Request Help":

    page_header(
        "Request Help",
        "Tell your community what you need assistance with.",
        show_back=True,
    )

    with st.container(
        border=True,
        key="request_help_form",
    ):

        st.markdown(
            """<div class="request-section-heading">
        <div class="request-section-kicker">01 · REQUEST DETAILS</div>
        <div class="request-section-title">Tell us what you need</div>
        <div class="request-section-text">Share a clear description so your neighbours know exactly how they can help.</div>
        </div>""",
            unsafe_allow_html=True,
        )

        title = st.text_input(
            "What do you need help with?",
            placeholder="e.g. Need someone to collect my notes",
        )

        category = st.selectbox(
            "Category",
            [
                "Academic",
                "Grocery",
                "Transportation",
                "Elderly Support",
                "Technology",
                "Household",
                "Other",
            ],
        )

        description = st.text_area(
            "Describe your request",
            placeholder=(
                "Explain what kind of help you need, "
                "when you need it, and any useful details."
            ),
            height=130,
        )

        # =========================================================
        # LOCATION
        # =========================================================

        with st.container(key="request_location_section"):

            st.markdown(
                """<div class="request-section-heading request-location-heading">
            <div class="request-section-kicker">02 · HELP LOCATION</div>
            <div class="request-section-title">Where should the help happen?</div>
            <div class="request-section-text">Choose an approximate area. You don't need to share your exact home address.</div>
            </div>""",
                unsafe_allow_html=True,
            )

        # ---------------------------------------------------------
        # MANUAL LOCATION SEARCH
        # ---------------------------------------------------------

        location = st.text_input(
            "Area / locality",
            value=st.session_state.get(
                "request_location_text",
                "",
            ),
            placeholder="e.g. Sector 14, Gurgaon",
            key="request_location_text_input",
        )

        find_location_col, _ = st.columns([1.5, 4])

        with find_location_col:

            if st.button(
                "📍 Find on Map",
                key="request_find_location",
                use_container_width=True,
            ):

                coordinates = geocode_location(location)

                if coordinates:

                    latitude, longitude = coordinates

                    st.session_state["request_latitude"] = latitude
                    st.session_state["request_longitude"] = longitude

                    st.session_state["request_map_latitude"] = latitude
                    st.session_state["request_map_longitude"] = longitude
                    st.session_state["request_map_zoom"] = 13

                    st.success(
                        "✓ Location found. You can adjust the exact "
                        "approximate point on the map."
                    )

                    st.rerun()

                else:

                    st.warning(
                        "Location not found. Try entering a nearby "
                        "area, locality, sector, or city."
                    )

        


        # ---------------------------------------------------------
        # MAP
        # ---------------------------------------------------------

        location_map = folium.Map(
            location=[
                st.session_state["request_map_latitude"],
                st.session_state["request_map_longitude"],
            ],
            zoom_start=st.session_state["request_map_zoom"],

            # Keep OpenStreetMap
            tiles="OpenStreetMap",

            # Better map boundaries / controls
            min_zoom=3,
            max_zoom=19,
            control_scale=True,
            zoom_control=True,

            # Smoother Leaflet interaction
            zoom_animation=True,
            fade_animation=True,
            marker_zoom_animation=True,

            # Avoid unnecessary vector rendering overhead
            prefer_canvas=True,
        )


        # ---------------------------------------------------------
        # CURRENT LOCATION CONTROL
        # ---------------------------------------------------------

        LocateControl(
            position="topleft",
            auto_start=False,
            flyTo=True,
            keepCurrentZoomLevel=False,
            drawMarker=True,
            drawCircle=True,
            showCompass=True,

            icon="neki-current-location-icon",
            iconLoading="neki-current-location-spinner",

            strings={
                "title": "Use my current location",
                "popup": "Your current location",
                "outsideMapBoundsMsg": "Your location is outside the map area.",
            },
        ).add_to(location_map)

        # ---------------------------------------------------------
        # NEKI CURRENT LOCATION CONTROL STYLING
        # ---------------------------------------------------------

        location_map.get_root().header.add_child(
            folium.Element(
                """
                <style>

                /* -----------------------------------------------
                Current location button
                ----------------------------------------------- */

                .leaflet-control-locate {
                    margin-top: 7px !important;
                    margin-left: 7px !important;
                }

                .leaflet-control-locate a {

                    width: 32px !important;
                    height: 32px !important;

                    display: flex !important;
                    align-items: center !important;
                    justify-content: center !important;

                    background: #FFFFFF !important;

                    border: 1px solid rgba(0,0,0,0.12) !important;
                    border-radius: 6px !important;

                    box-shadow:
                        0 2px 6px rgba(0,0,0,0.18) !important;

                    position: relative !important;

                    transition:
                        transform 0.18s ease,
                        box-shadow 0.18s ease !important;
                }

                .leaflet-control-locate a:hover {
                    background: #FFFFFF !important;

                    transform: translateY(-1px);

                    box-shadow:
                        0 4px 10px rgba(0,0,0,0.22) !important;
                }

                .leaflet-control-locate a:active {
                    transform: scale(0.96);
                }


                /* -----------------------------------------------
                Green target / current location icon
                ----------------------------------------------- */

                /* -----------------------------------------------
                Neki custom current-location icon
                ----------------------------------------------- */

                .neki-current-location-icon {

                    display: block !important;

                    width: 23px !important;
                    height: 23px !important;

                    margin: 4px !important;

                    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Ccircle cx='12' cy='12' r='7.5' fill='none' stroke='%2319B968' stroke-width='4'/%3E%3Ccircle cx='12' cy='12' r='4.2' fill='%2319B968'/%3E%3Crect x='10' y='0.5' width='4' height='5' rx='1.5' fill='%2319B968'/%3E%3Crect x='10' y='18.5' width='4' height='5' rx='1.5' fill='%2319B968'/%3E%3Crect x='0.5' y='10' width='5' height='4' rx='1.5' fill='%2319B968'/%3E%3Crect x='18.5' y='10' width='5' height='4' rx='1.5' fill='%2319B968'/%3E%3C/svg%3E") !important;

                    background-repeat: no-repeat !important;
                    background-position: center !important;
                    background-size: contain !important;

                    pointer-events: none !important;
                }


                /* Hide loading icon completely */
                .neki-current-location-spinner {
                    display: none !important;
                }


                /* Keep the white button */
                .leaflet-control-locate a,
                .leaflet-control-locate.active a {
                    background: #FFFFFF !important;
                }


                .leaflet-control-locate a:focus {
                    outline: none !important;
                }

                </style>
                """
            )
        )
        # ---------------------------------------------------------
        # SHOW SELECTED APPROXIMATE LOCATION
        # ---------------------------------------------------------

        if (
            st.session_state.get("request_latitude") is not None
            and st.session_state.get("request_longitude") is not None
        ):

            selected_latitude = st.session_state["request_latitude"]
            selected_longitude = st.session_state["request_longitude"]

            # Clearly show the approximate area where the request
            # will be placed.
            folium.Circle(
                location=[
                    selected_latitude,
                    selected_longitude,
                ],
                radius=180,
                color="#19B968",
                weight=3,
                fill=True,
                fill_color="#19B968",
                fill_opacity=0.18,
                tooltip="Approximate request area",
            ).add_to(location_map)

            # Clearly mark the exact point selected by the user.
            folium.Marker(
                [
                    selected_latitude,
                    selected_longitude,
                ],
                tooltip="📍 Your selected request location",
                popup=folium.Popup(
                    """
                    <div style="
                        font-family: Arial, sans-serif;
                        font-size: 13px;
                        line-height: 1.5;
                        padding: 4px;
                    ">
                        <strong>📍 Request location</strong><br>
                        This is where your request will be shown
                        to nearby helpers.
                    </div>
                    """,
                    max_width=260,
                ),
                icon=folium.DivIcon(
                    html="""
                    <div style="
                        width: 30px;
                        height: 30px;
                        border-radius: 50% 50% 50% 0;
                        background: #19B968;
                        border: 3px solid #FFFFFF;
                        box-shadow: 0 4px 12px rgba(0,0,0,0.30);
                        transform: rotate(-45deg);
                        display: flex;
                        align-items: center;
                        justify-content: center;
                    ">
                        <div style="
                            width: 8px;
                            height: 8px;
                            border-radius: 50%;
                            background: #FFFFFF;
                        "></div>
                    </div>
                    """
                ),
            ).add_to(location_map)


        # ---------------------------------------------------------
        # MAP INSTRUCTION
        # ---------------------------------------------------------

        st.markdown(
            """
            <div class="request-map-tip">
                <span class="request-map-tip-icon">📍</span>
                <span>
                    <strong>Tip:</strong>
                    Use the location button to find yourself, then click the map
                    to choose the approximate place where help is needed.
                </span>
            </div>  
            """,
            unsafe_allow_html=True,
        )


        with st.container(key="find_help_map_frame"):

            map_data = st_folium(
                location_map,
                width=None,
                height=360,
                key="request_location_map",
            )


        # ---------------------------------------------------------
        # SAVE USER'S SELECTED APPROXIMATE LOCATION
        # ---------------------------------------------------------

        if map_data and map_data.get("last_clicked"):

            selected_latitude = map_data["last_clicked"]["lat"]
            selected_longitude = map_data["last_clicked"]["lng"]

            st.session_state["request_latitude"] = selected_latitude
            st.session_state["request_longitude"] = selected_longitude

            st.session_state["request_map_latitude"] = selected_latitude
            st.session_state["request_map_longitude"] = selected_longitude
            st.session_state["request_map_zoom"] = 15

            # -----------------------------------------------------
            # IDENTIFY AREA FROM SELECTED POINT
            # -----------------------------------------------------

            detected_area = reverse_geocode_area(
                selected_latitude,
                selected_longitude,
            )

            if detected_area:
                st.session_state["request_location_text"] = detected_area

            st.success(
                "✓ Your request will be placed at the selected map location."
            )

            st.rerun()

        st.markdown(
            """<div class="request-section-heading request-budget-heading">
        <div class="request-section-kicker">03 · BUDGET</div>
        <div class="request-section-title">How would you like to offer help?</div>
        <div class="request-section-text">Let neighbours know whether this request is volunteer, paid, or open to discussion.</div>
        </div>""",
            unsafe_allow_html=True,
        )

        budget_type = st.selectbox(
            "Budget",
            [
                "Free / Volunteer",
                "Paid",
                "Negotiable",
            ],
            key="request_budget_type",
        )

        budget_amount_value = st.number_input(
            "Amount offered (₹)",
            min_value=0.0,
            step=50.0,
            value=0.0,
            format="%.0f",
            disabled=(budget_type != "Paid"),
            key="request_budget_amount",
        )

        budget_amount = (
            budget_amount_value
            if budget_type == "Paid"
            else None
        )

        st.caption(
            "Only needed for paid requests."
        )

        st.markdown(
            """
            <div class="request-submit-divider"></div>
            """,
            unsafe_allow_html=True,
        )

        with st.container(key="request_actions"):

            col1, col2 = st.columns([1, 1])

        with col1:
            if st.button(
                "← Back to Dashboard",
                use_container_width=True,
                key="request_back_dashboard",
            ):
                go_to("Dashboard")

        with col2:
            if st.button(
                "Post Help Request →",
                type="primary",
                use_container_width=True,
                key="request_post_help",
            ):
                if not title or not description:
                    st.error(
                        "Please complete the request details."
                    )

                elif (
                    st.session_state.get("request_latitude") is None
                    or st.session_state.get("request_longitude") is None
                ):
                    st.error(
                        "Please select an approximate help location on the map."
                    )

                else:
                    request_location = (
                        location.strip()
                        if location and location.strip()
                        else st.session_state.get(
                            "request_location_text",
                            "",
                        ).strip()
                    )

                    if not request_location:
                        request_location = "Approximate location"

                    request_id = create_help_request(
                        user_id=st.session_state.user_id,
                        title=title,
                        description=description,
                        category=category,
                        location=request_location,
                        budget_type=budget_type,
                        budget_amount=budget_amount,
                        latitude=st.session_state.get("request_latitude"),
                        longitude=st.session_state.get("request_longitude"),
                    )

                    st.session_state.my_requests_tab = "Requests I Created"
                    st.session_state.scroll_to_top = True
                    st.session_state.request_posted_notice = True
                    st.session_state.new_request_id = request_id

                    go_to("My Requests")


# =========================================================
# FIND HELP
# =========================================================

elif st.session_state.page == "Find Help":

    st.markdown(
        '<div class="find-help-page"></div>',
        unsafe_allow_html=True,
    )

    page_header(
        "Find Someone to Help ",
        "Discover people in your community who need assistance.",
        show_back=True,
    )

    search = st.text_input(
        "🔎 Search requests",
        placeholder="Search by request, category or location...",
    )

    

    if search.strip():

        requests = search_help_requests(
            search_term=search,
            user_id=st.session_state.user_id,
        )

    else:

        requests = get_open_requests(
            st.session_state.user_id
        )


    # =========================================================
    # FIND HELP MAP
    # =========================================================

    map_requests = [
        request
        for request in requests
        if request["latitude"] is not None
        and request["longitude"] is not None
    ]

    if map_requests:

        st.markdown(
            """
            <div class="find-help-map-heading">
                <div>
                    <div class="find-help-section-kicker">
                        DISCOVER NEARBY
                    </div>
                    <div class="find-help-section-title">
                        Help requests near you
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # Calculate a useful center from available requests
        center_latitude = sum(
            request["latitude"]
            for request in map_requests
        ) / len(map_requests)

        center_longitude = sum(
            request["longitude"]
            for request in map_requests
        ) / len(map_requests)

        help_map = folium.Map(
            location=[
                center_latitude,
                center_longitude,
            ],
            zoom_start=11,
            control_scale=True,
            tiles="OpenStreetMap",
            prefer_canvas=True,
        )

        # ---------------------------------------------------------
        # CURRENT LOCATION CONTROL
        # ---------------------------------------------------------

        LocateControl(
            position="topleft",
            auto_start=False,
            flyTo=True,
            keepCurrentZoomLevel=False,
            drawMarker=True,
            drawCircle=True,
            showCompass=True,

            icon="neki-current-location-icon",
            iconLoading="neki-current-location-spinner",

            strings={
                "title": "Use my current location",
                "popup": "Your current location",
                "outsideMapBoundsMsg": "Your location is outside the map area.",
            },
        ).add_to(help_map)

        # ---------------------------------------------------------
        # NEKI CURRENT LOCATION CONTROL STYLING
        # ---------------------------------------------------------

        help_map.get_root().header.add_child(
            folium.Element(
                """
                <style>

                /* -----------------------------------------------
                Current location button
                ----------------------------------------------- */

                .leaflet-control-locate {
                    margin-top: 7px !important;
                    margin-left: 7px !important;
                }

                .leaflet-control-locate a {

                    width: 32px !important;
                    height: 32px !important;

                    display: flex !important;
                    align-items: center !important;
                    justify-content: center !important;

                    background: #FFFFFF !important;

                    border: 1px solid rgba(0,0,0,0.12) !important;
                    border-radius: 6px !important;

                    box-shadow:
                        0 2px 6px rgba(0,0,0,0.18) !important;

                    position: relative !important;

                    transition:
                        transform 0.18s ease,
                        box-shadow 0.18s ease !important;
                }

                .leaflet-control-locate a:hover {
                    background: #FFFFFF !important;

                    transform: translateY(-1px);

                    box-shadow:
                        0 4px 10px rgba(0,0,0,0.22) !important;
                }

                .leaflet-control-locate a:active {
                    transform: scale(0.96);
                }


                /* -----------------------------------------------
                Green target / current location icon
                ----------------------------------------------- */

                /* -----------------------------------------------
                Neki custom current-location icon
                ----------------------------------------------- */

                .neki-current-location-icon {

                    display: block !important;

                    width: 23px !important;
                    height: 23px !important;

                    margin: 4px !important;

                    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Ccircle cx='12' cy='12' r='7.5' fill='none' stroke='%2319B968' stroke-width='4'/%3E%3Ccircle cx='12' cy='12' r='4.2' fill='%2319B968'/%3E%3Crect x='10' y='0.5' width='4' height='5' rx='1.5' fill='%2319B968'/%3E%3Crect x='10' y='18.5' width='4' height='5' rx='1.5' fill='%2319B968'/%3E%3Crect x='0.5' y='10' width='5' height='4' rx='1.5' fill='%2319B968'/%3E%3Crect x='18.5' y='10' width='5' height='4' rx='1.5' fill='%2319B968'/%3E%3C/svg%3E") !important;

                    background-repeat: no-repeat !important;
                    background-position: center !important;
                    background-size: contain !important;

                    pointer-events: none !important;
                }


                /* Hide loading icon completely */
                .neki-current-location-spinner {
                    display: none !important;
                }


                /* Keep the white button */
                .leaflet-control-locate a,
                .leaflet-control-locate.active a {
                    background: #FFFFFF !important;
                }


                .leaflet-control-locate a:focus {
                    outline: none !important;
                }

                </style>
                """
            )
        )

        map_bounds = []

        for request in map_requests:

            latitude = request["latitude"]
            longitude = request["longitude"]

            map_bounds.append([latitude, longitude])
            # ---------------------------------------------------------
            # MARKER PREVIEW
            # ---------------------------------------------------------

            popup_html = f"""
            <div style="
                min-width: 220px;
                font-family: Arial, sans-serif;
                line-height: 1.5;
            ">
                <strong style="font-size: 16px;">
                    {request["title"]}
                </strong>

                <br>

                <span>
                    📚 {request["category"]}
                </span>

                <br>

                <span>
                    📍 {request["location"]}
                </span>

                <br>

                <span>
                    💰 {request["budget_type"]}
                </span>

                <!-- Internal request identifier -->
                <span style="display:none;">
                    request_{request["id"]}
                </span>
            </div>
            """

            tooltip_html = f"""
            <div style="
                min-width: 190px;
                font-family: Arial, sans-serif;
                line-height: 1.45;
            ">
                <strong style="font-size: 15px;">
                    {request["title"]}
                </strong>

                <br>

                <span>
                    📚 {request["category"]}
                </span>

                <br>

                <span>
                    📍 {request["location"]}
                </span>

                <br>

                <span>
                    💰 {request["budget_type"]}
                </span>
            </div>
            """

            folium.Marker(
                [latitude, longitude],

                # What the user sees on hover
                tooltip=folium.Tooltip(
                    tooltip_html,
                    sticky=False,
                ),

                

                icon=folium.Icon(
                    color="green",
                    icon="handshake",
                    prefix="fa",
                ),
            ).add_to(help_map)

        # Automatically show all request markers
        if len(map_bounds) > 1:

            help_map.fit_bounds(
                map_bounds,
                padding=(70, 70),
                max_zoom=11,
            )

        elif len(map_bounds) == 1:

            help_map.location = map_bounds[0]
            help_map.zoom_start = 13

        map_data = st_folium(
            help_map,
            width=None,
            height=380,
            key="find_help_map",
        )

        # ---------------------------------------------------------
        # SELECT REQUEST FROM CLICKED MAP MARKER
        # ---------------------------------------------------------

        if map_data:

            clicked_marker = map_data.get(
                "last_object_clicked"
            )

            if clicked_marker:

                clicked_lat = clicked_marker.get("lat")
                clicked_lng = clicked_marker.get("lng")

                if (
                    clicked_lat is not None
                    and clicked_lng is not None
                ):

                    # Find the request whose marker was clicked
                    selected_request = min(
                        map_requests,
                        key=lambda request: (
                            (request["latitude"] - clicked_lat) ** 2
                            +
                            (request["longitude"] - clicked_lng) ** 2
                        ),
                    )

                    st.session_state[
                        "selected_map_request_id"
                    ] = selected_request["id"]

        st.caption(
            "📍 Markers show approximate help locations. "
            "Exact addresses are not displayed."
        )


    if not requests:

        st.info(
            "There are no open help requests right now."
        )

    else:

        st.markdown(
            """
            <div class="find-help-list-heading">
                <div>
                    <div class="find-help-section-kicker">
                        COMMUNITY REQUESTS
                    </div>
                    <div class="find-help-section-title">
                        Requests you can help with
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        selected_request_id = st.session_state.get(
            "selected_map_request_id"
        )

        # Put selected map request first
        if selected_request_id is not None:

            selected_requests = [
                request
                for request in requests
                if request["id"] == selected_request_id
            ]

            other_requests = [
                request
                for request in requests
                if request["id"] != selected_request_id
            ]

            requests = selected_requests + other_requests

   

        for request in requests:
            is_selected = (
                request["id"]
                == st.session_state.get(
                    "selected_map_request_id"
                )
            )

            if is_selected:
                st.success(
                    "📍 Selected from map"
                )

            with st.container(
                border=True,
                key=f"find_help_request_card_{request['id']}",
                width=1080,
                gap="small",
            ):

                st.markdown(
                    f"""
                    <div class="request-time-badge">
                        🕒 {format_request_age(request["created_at"])}
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                

                left, right = st.columns(
                    [5.2, 1.8],
                    gap="large",
                    vertical_alignment="top",
                )

                with left:

                    st.markdown(
                        f"### {request['title']}"
                    )

                    st.caption(
                        f"Category: {request['category']} "
                        f"• 📍 {request['location']}"
                    )

                    # Budget
                    if request["budget_type"] == "Paid" and request["budget_amount"]:
                        st.write(
                            f"💰 **Budget:** ₹{request['budget_amount']:.0f}"
                        )

                    elif request["budget_type"] == "Negotiable":
                        st.write(
                            "💰 **Budget:** Negotiable"
                        )

                    else:
                        st.write(
                            "💚 **Budget:** Free / Volunteer"
                        )

                    st.write(
                        request["description"]
                    )

                    requester_name = (
                        request["requester_name"]
                        or "Neighbour"
                    )

                    st.markdown(
                        '<div class="find-help-requester-gap"></div>',
                        unsafe_allow_html=True,
                    )

                    st.markdown(
                        f"👤 **Requested by {requester_name}**"
                    )

                    if st.button(
                        f"👤 View {requester_name}'s Public Profile →",
                        key=f"requester_profile_{request['id']}",
                        use_container_width=False,
                    ):
                        open_match_profile(request["id"])


                with right:

                    st.markdown(
                        '<div class="find-help-action-top-gap"></div>',
                        unsafe_allow_html=True,
                    )

                    if st.button(
                        "🤝 Offer to Help",
                        key=f"accept_{request['id']}",
                        type="primary",
                        use_container_width=True,
                    ):

                        accepted = accept_help_request(
                            request_id=request["id"],
                            helper_id=st.session_state.user_id
                        )

                        if accepted:

                            st.session_state.accepted_request_notice = True
                            st.session_state.my_requests_tab = "Requests I Accepted"
                            st.session_state.scroll_to_top = True

                            go_to("My Requests")

                        else:

                            st.error(
                                "This request is no longer available. "
                                "It may have already been accepted by another neighbour."
                            )

                    render_report_action(
                        report_key=f"find_request_{request['id']}",
                        reported_user_id=request["user_id"],
                        request_id=request["id"],
                        report_type="Request",
                    )       

# =========================================================
# MY REQUESTS
# =========================================================

elif st.session_state.page == "My Requests":

    if st.session_state.get("scroll_to_top", False):
        scroll_to_top()
        st.session_state.scroll_to_top = False

    if st.session_state.get("request_posted_notice", False):

        st.markdown(
            """
            <div class="request-posted-notice">
                <div class="request-posted-icon">✓</div>
                <div>
                    <div class="request-posted-title">
                        Request posted successfully
                    </div>
                    <div class="request-posted-text">
                        Your request is now in Requests I Created.
                    </div>
                </div>
            </div>

            <script>
                setTimeout(function() {
                    const notice =
                        document.querySelector(".request-posted-notice");

                    if (notice) {
                        notice.classList.add("request-posted-hide");
                    }
                }, 2200);
            </script>
            """,
            unsafe_allow_html=True,
        )

        st.session_state.request_posted_notice = False    

    page_header(
        "My Requests",
        "Track requests you created or accepted.",
        show_back=True,
    )

    # -----------------------------------------------------
    # TABS
    # -----------------------------------------------------

    selected_tab = st.segmented_control(
        "",
        [
            "Requests I Created",
            "Requests I Accepted",
        ],
        default=st.session_state.get(
            "my_requests_tab",
            "Requests I Created",
        ),
        key="my_requests_selector",
    )

    if selected_tab is None:
        selected_tab = "Requests I Created"

    st.session_state.my_requests_tab = selected_tab

    

    # =====================================================
    # REQUESTS I CREATED
    # =====================================================

    if selected_tab == "Requests I Created":

        requests = get_user_requests(
            st.session_state.user_id
        )

        if not requests:

            st.info(
                "You have not created any help requests yet."
            )

        else:

            for request in requests:

                is_new_request = (
                    st.session_state.get("new_request_id")
                    == request["id"]
                )

                # -------------------------------------------------
                # REQUEST CARD
                # -------------------------------------------------

                with st.container(
                    border=True,
                    key=f"my_request_card_{request['id']}",
                    width=1080,
                    gap="small",
                ):

                    st.markdown(
                        """
                        <div class="my-request-card-anchor"></div>
                        """,
                        unsafe_allow_html=True,
                    )

                    st.markdown(
                        f"""
                        <div class="request-time-badge">
                            🕒 {format_request_age(request["created_at"])}
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                    if is_new_request:

                        st.markdown(
                            """
                            <div class="new-request-marker">
                                ✦ Just posted
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

                    # -------------------------------------------------
                    # REQUEST SUMMARY
                    # -------------------------------------------------

                    status = request["status"]
                    is_removed = request["is_removed"] == 1

                    if is_removed:
                        status_label = "Removed"
                        status_class = "removed"
                    elif status == "Accepted":
                        status_label = "Accepted"
                        status_class = "accepted"
                    elif status == "Help Provided":
                        status_label = "Help Provided"
                        status_class = "provided"
                    elif status == "Completed":
                        status_label = "Completed"
                        status_class = "completed"
                    elif status == "Pending":
                        status_label = "Pending"
                        status_class = "pending"
                    elif status == "Awaiting Requester Approval":
                        status_label = "Review Helper Offer"
                        status_class = "review"
                    else:
                        status_label = status
                        status_class = "default"


                    summary_left, summary_right = st.columns(
                        [2.45, 1],
                        gap="large",
                    )


                    # -------------------------------------------------
                    # LEFT — REQUEST DETAILS
                    # -------------------------------------------------

                    with summary_left:

                        st.markdown(
                            '<div class="request-kicker">🤝 HELP CONNECTION</div>',
                            unsafe_allow_html=True,
                        )

                        st.markdown(
                            f'<div class="request-card-title">{request["title"]}</div>',
                            unsafe_allow_html=True,
                        )

                        st.markdown(
                            f'<div class="request-card-meta">📁 {request["category"]}<span class="request-meta-separator">•</span>📍 {request["location"]}</div>',
                            unsafe_allow_html=True,
                        )

                        st.markdown(
                            f'<div class="request-card-description">{request["description"]}</div>',
                            unsafe_allow_html=True,
                        )


                    # -------------------------------------------------
                    # RIGHT — STATUS + BUDGET
                    # -------------------------------------------------

                    with summary_right:

                        budget_display = (
                            f"₹{float(request['budget_amount']):,.0f}"
                            if request["budget_type"] == "Paid"
                            and request["budget_amount"] is not None
                            else request["budget_type"]
                            if request["budget_type"]
                            else "Not specified"
                        )

                        side_panel_html = (
                            f'<div class="request-side-panel">'
                            f'<div class="request-side-label">STATUS</div>'
                            f'<div class="neki-request-status {status_class}">'
                            f'<span class="neki-status-dot"></span>'
                            f'<span>{status_label}</span>'
                            f'</div>'
                            f'<div class="request-side-divider"></div>'
                            f'<div class="request-side-label">BUDGET</div>'
                            f'<div class="request-side-value">{budget_display}</div>'
                            f'</div>'
                        )

                        st.markdown(
                            side_panel_html,
                            unsafe_allow_html=True,
                        )


                    # -------------------------------------------------
                    # REMOVED REQUEST
                    # -------------------------------------------------

                    if is_removed:
                        st.markdown(
                            """
                            <div class="neki-removed-notice">
                                <span class="neki-removed-icon">!</span>
                                <span>
                                    This request has been removed from the community and is no longer active.
                                </span>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

                        if request["removed_reason"]:
                            if request["removed_by_admin"]:
                                st.write(
                                    f"**Removal Reason:** {request['removed_reason']}"
                                )
                            else:
                                st.write(
                                    f"**Status:** {request['removed_reason']}"
                                )

                        if request["removed_at"]:
                            st.caption(
                                f"Removed: {request['removed_at']}"
                            )

                        st.markdown("---")

                    # -------------------------------------------------
                    # HELPER INFORMATION
                    # -------------------------------------------------

                    if request["helper_id"] and not is_removed:

                        st.markdown("---")

                        helper_name = (
                            request["helper_name"]
                            or "Neighbour"
                        )

                        # =================================================
                        # HELPER OFFER — REQUESTER MUST REVIEW
                        # =================================================

                        if status == "Awaiting Requester Approval":

                            helper_id = request["helper_id"]

                            helper_user = get_user_by_id(
                                helper_id
                            )

                            average_rating, total_ratings = (
                                get_user_rating_stats(
                                    helper_id
                                )
                            )

                            people_helped = get_people_helped_count(
                                helper_id
                            )

                            helper_trust_score = (
                                helper_user["trust_score"]
                                if helper_user
                                else 50
                            )

                            helper_location = (
                                helper_user["location"]
                                if helper_user
                                else "Not available"
                            )

                            st.markdown(
                                "🤝 **NEW HELPER OFFER**"
                            )

                            st.markdown(
                                f"### {helper_name} wants to help"
                            )


                            info_col1, info_col2, info_col3, info_col4 = st.columns(4)

                            with info_col1:
                                st.metric(
                                    "⭐ Rating",
                                    f"{average_rating:.1f}/5"
                                )

                            with info_col2:
                                st.metric(
                                    "🛡 Trust Score",
                                    f"{helper_trust_score:.1f}/100"
                                )

                            with info_col3:
                                st.metric(
                                    "🤝 Completed Helps",
                                    people_helped
                                )

                            with info_col4:
                                st.metric(
                                    "📍 Location",
                                    helper_location
                                )

                            st.markdown("")

                            if st.button(
                                f"👤 View {helper_name}'s Public Profile →",
                                key=f"pending_helper_profile_{request['id']}",
                                use_container_width=True,
                            ):
                                open_match_profile(request["id"])

                            accept_col, decline_col = st.columns(2)

                            with accept_col:

                                if st.button(
                                    "✅ Accept Helper",
                                    type="primary",
                                    use_container_width=True,
                                    key=f"approve_helper_{request['id']}",
                                ):

                                    approved = approve_helper(
                                        request["id"],
                                        st.session_state.user_id,
                                    )

                                    if approved:

                                        st.success(
                                            "Helper accepted successfully. 🤝"
                                        )

                                        st.session_state.my_requests_tab = (
                                            "Requests I Created"
                                        )

                                        st.session_state.scroll_to_top = True

                                        st.rerun()

                                    else:

                                        st.error(
                                            "This helper offer is no longer available."
                                        )

                            with decline_col:

                                if st.button(
                                    "🔄 Find Another Helper",
                                    use_container_width=True,
                                    key=f"decline_helper_{request['id']}",
                                ):

                                    declined = decline_helper(
                                        request["id"],
                                        st.session_state.user_id,
                                    )

                                    if declined:

                                        st.success(
                                            "The request is open again for another helper."
                                        )

                                        st.session_state.my_requests_tab = (
                                            "Requests I Created"
                                        )

                                        st.session_state.scroll_to_top = True

                                        st.rerun()

                                    else:

                                        st.error(
                                            "Unable to reopen this request. "
                                            "The helper offer may already have changed."
                                        )

                        # =================================================
                        # ACCEPTED / ACTIVE CONNECTION
                        # =================================================

                        elif status in (
                            "Accepted",
                            "Help Provided",
                            "Completed",
                        ):

                            st.markdown(
                                '<div class="request-kicker">👤 YOUR HELPER</div>',
                                unsafe_allow_html=True,
                            )

                            st.markdown(
                                f'<div class="request-helper-name">{helper_name}</div>',
                                unsafe_allow_html=True,
                            )

                            if status == "Accepted":

                                st.caption(
                                    "This neighbour has accepted your request."
                                )

                            elif status == "Help Provided":

                                st.caption(
                                    "Your helper has marked this help as provided."
                                )

                            elif status == "Completed":

                                st.caption(
                                    "This help request has been completed."
                                )

                            if st.button(
                                f"👤 View {helper_name}'s Profile →",
                                key=f"created_profile_{request['id']}",
                                use_container_width=False,
                            ):

                                open_connection_profile(
                                    request["id"]
                                )

                            
                            if status == "Accepted":
                                if st.button(
                                    "🗺️ Open Journey & Map →",
                                    key=f"created_journey_{request['id']}",
                                    use_container_width=False,
                                ):
                                    open_request_status(
                                        request["id"],
                                        return_page="My Requests",
                                    )

                    

        

                    # =================================================
                    # REQUESTER REMOVES OWN PENDING REQUEST
                    # =================================================

                    if status == "Pending" and not request["is_removed"]:

                        st.markdown("")

                        with st.container(
                            key=f"remove_request_action_{request['id']}"
                        ):
                            if st.button(
                                "Remove Request",
                                icon=":material/delete_outline:",
                                key=f"remove_own_request_{request['id']}",
                                use_container_width=False,
                                type="secondary",
                            ):
                                
                                st.session_state[
                                    f"confirm_remove_request_{request['id']}"
                                ] = True


                            

                        if st.session_state.get(
                            f"confirm_remove_request_{request['id']}",
                            False
                        ):

                            with st.container(border=True):

                                st.markdown(
                                    """
                                    <div class="remove-request-warning">
                                        Are you sure you want to remove this request?
                                        It will no longer be visible to other neighbours.
                                    </div>
                                    """,
                                    unsafe_allow_html=True,
                                )

                                confirm_col1, confirm_col2 = st.columns(2)

                                with confirm_col1:

                                    if st.button(
                                        "Yes, Remove Request",
                                        type="primary",
                                        key=f"confirm_remove_{request['id']}",
                                        use_container_width=True,
                                    ):

                                        success = remove_own_request(
                                            request["id"],
                                            st.session_state.user_id,
                                        )

                                        if success:
                                            st.session_state[
                                                f"confirm_remove_request_{request['id']}"
                                            ] = False

                                            st.success(
                                                "Your request has been removed successfully."
                                            )

                                            st.rerun()

                                        else:
                                            st.error(
                                                "Unable to remove this request. "
                                                "It may no longer be pending."
                                            )

                                with confirm_col2:

                                    if st.button(
                                        "Cancel",
                                        key=f"cancel_remove_{request['id']}",
                                        use_container_width=True,
                                    ):

                                        st.session_state[
                                            f"confirm_remove_request_{request['id']}"
                                        ] = False

                                        st.rerun()    

                    

                    # =================================================
                    # REQUESTER CONFIRMS HELP COMPLETED
                    # =================================================

                    if status == "Help Provided" and not is_removed:

                        st.markdown("")

                        if st.button(
                            "✅ Confirm Help Completed",
                            key=f"confirm_completed_{request['id']}",
                            use_container_width=False,
                        ):

                            confirm_help_completed(
                                request["id"],
                                st.session_state.user_id,
                            )

                            st.rerun()

                    # =================================================
                    # RATING AFTER COMPLETION
                    # =================================================

                    if status == "Completed" and request["helper_id"] and not is_removed:

                        st.markdown("")

                        already_rated = has_user_rated(
                            request["id"],
                            st.session_state.user_id,
                        )

                        if already_rated:

                            st.caption(
                                "⭐ You already rated this helper."
                            )

                        else:

                            st.markdown(
                                "### ⭐ Rate your helper"
                            )

                            # -------------------------------------------------
                            # STAR RATING
                            # -------------------------------------------------

                            rating_key = f"rating_{request['id']}"

                            if rating_key not in st.session_state:
                                st.session_state[rating_key] = 5

                            current_rating = st.session_state[rating_key]

                            st.markdown(
                                '<div class="neki-rating-label">Rating</div>',
                                unsafe_allow_html=True,
                            )

                            star_cols = st.columns(5, gap="small")

                            for star_number, star_col in enumerate(star_cols, start=1):

                                with star_col:

                                    if star_number <= current_rating:
                                        star_label = "★"
                                        button_type = "primary"
                                    else:
                                        star_label = "☆"
                                        button_type = "secondary"

                                    if st.button(
                                        star_label,
                                        key=f"rating_star_{request['id']}_{star_number}",
                                        type=button_type,
                                        use_container_width=True,
                                    ):
                                        st.session_state[rating_key] = star_number
                                        st.rerun()

                            rating = st.session_state[rating_key]

                            st.markdown(
                                f"""
                                <div class="neki-rating-value">
                                    {rating} <span>/ 5</span>
                                </div>
                                """,
                                unsafe_allow_html=True,
                            )

                            review = st.text_area(
                                "Review",
                                placeholder="Share your experience...",
                                key=f"review_{request['id']}",
                            )

                            if st.button(
                                "Submit Rating",
                                type="primary",
                                use_container_width=True,
                                key=f"submit_rating_{request['id']}",
                            ):

                                submit_rating(
                                    request["id"],
                                    st.session_state.user_id,
                                    request["helper_id"],
                                    rating,
                                    review,
                                )

                                st.success(
                                    "Thank you for rating your helper! ⭐"
                                )

                                st.rerun()
    if st.session_state.get("new_request_id") is not None:
        st.session_state.new_request_id = None
    
    # =====================================================
    # REQUESTS I ACCEPTED
    # =====================================================

    elif selected_tab == "Requests I Accepted":

        requests = get_accepted_requests(
            st.session_state.user_id
        )

        if not requests:

            st.info(
                "You have not accepted any help requests yet."
            )

        else:

            for request in requests:

                # -------------------------------------------------
                # REQUEST CARD
                # -------------------------------------------------

                with st.container(
                    border=True,
                    key=f"my_accepted_request_card_{request['id']}",
                    width=1080,
                    gap="small",
                ):

                    st.markdown(
                        """
                        <div class="my-request-card-anchor"></div>
                        """,
                        unsafe_allow_html=True,
                    )

                    st.markdown(
                        f"""
                        <div class="request-time-badge">
                            🕒 {format_request_age(request["created_at"])}
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                    # -------------------------------------------------
                    # REQUEST SUMMARY
                    # -------------------------------------------------

                    status = request["status"]

                    if status == "Accepted":
                        status_label = "Accepted"
                        status_class = "accepted"
                    elif status == "Help Provided":
                        status_label = "Help Provided"
                        status_class = "provided"
                    elif status == "Completed":
                        status_label = "Completed"
                        status_class = "completed"
                    elif status == "Awaiting Requester Approval":
                        status_label = "Waiting for Approval"
                        status_class = "review"
                    else:
                        status_label = status
                        status_class = "default"

                    requester_name = (
                        request["requester_name"]
                        or "Neighbour"
                    )

                    summary_left, summary_right = st.columns(
                        [2.45, 1],
                        gap="large",
                    )


                    # -------------------------------------------------
                    # LEFT — REQUEST DETAILS
                    # -------------------------------------------------

                    with summary_left:

                        st.html(
                            f"""
                            <div class="request-main-heading">

                                <div class="request-kicker">
                                    🤝 HELP CONNECTION
                                </div>

                                <div class="request-card-title">
                                    {request['title']}
                                </div>

                                <div class="request-card-meta">
                                    📁 {request['category']}
                                    <span class="request-meta-separator">•</span>
                                    📍 {request['location']}
                                </div>

                            </div>

                            <div class="request-card-description">
                                {request['description']}
                            </div>
                            """
                        )


                    # -------------------------------------------------
                    # RIGHT — CONNECTION INFO
                    # -------------------------------------------------

                    with summary_right:

                        budget_display = (
                            f"₹{float(request['budget_amount']):,.0f}"
                            if request["budget_type"] == "Paid"
                            and request["budget_amount"] is not None
                            else request["budget_type"]
                            if request["budget_type"]
                            else "Not specified"
                        )

                        side_panel_html = (
                            f'<div class="request-side-panel">'
                            f'<div class="request-side-label">STATUS</div>'
                            f'<div class="neki-request-status {status_class}">'
                            f'<span class="neki-status-dot"></span>'
                            f'<span>{status_label}</span>'
                            f'</div>'
                            f'<div class="request-side-divider"></div>'
                            f'<div class="request-side-label">REQUESTED BY</div>'
                            f'<div class="request-side-value">{requester_name}</div>'
                            f'<div class="request-side-divider"></div>'
                            f'<div class="request-side-label">BUDGET</div>'
                            f'<div class="request-side-value">{budget_display}</div>'
                            f'</div>'
                        )

                        st.markdown(
                            side_panel_html,
                            unsafe_allow_html=True,
                        )

                    # -------------------------------------------------
                    # PROFILE BUTTON
                    # -------------------------------------------------

                    if status in (
                        "Accepted",
                        "Help Provided",
                        "Completed",
                    ):

                        if st.button(
                            f"👤 View {requester_name}'s Profile →",
                            key=f"accepted_profile_{request['id']}",
                            use_container_width=False,
                        ):

                            open_connection_profile(
                                request["id"]
                            )
                        
                        if status == "Accepted":
                            if st.button(
                                "🗺️ Open Journey & Map →",
                                key=f"accepted_journey_{request['id']}",
                                use_container_width=False,
                            ):
                                open_request_status(
                                    request["id"],
                                    return_page="My Requests",
                                )
                    
                    # -------------------------------------------------
                    # REPORT REQUEST
                    # -------------------------------------------------

                    render_report_action(
                        report_key=f"accepted_request_{request['id']}",
                        reported_user_id=request["user_id"],
                        request_id=request["id"],
                        report_type="Request",
                    )
                    

                    # =================================================
                    # HELPER MARKS HELP AS PROVIDED
                    # =================================================

                    if status == "Accepted":

                        st.markdown("")

                        if st.button(
                            "🤝 Mark Help as Provided",
                            type="primary",
                            use_container_width=False,
                            key=f"provided_{request['id']}",
                        ):

                            mark_help_provided(
                                request["id"],
                                st.session_state.user_id,
                            )

                            st.rerun()


elif st.session_state.page == "Request Status":

    request_id = st.session_state.get("request_status_id")
    viewer_id = st.session_state.user_id

    request = (
        get_journey_request(request_id, viewer_id)
        if request_id is not None
        else None
    )

    if request is None:
        st.error("This help connection is unavailable.")
        if st.button("← Back to My Requests", key="journey_unavailable_back"):
            go_to("My Requests")

    else:
        is_helper = viewer_id == request["helper_id"]
        journey_status = request["journey_status"] or "Not Started"

        page_header(
            "Help Journey",
            "Your private journey and connection status.",
            show_back=False,
        )

        if st.button("← Back to My Requests", key="journey_back"):
            st.session_state.my_requests_tab = (
                "Requests I Accepted"
                if is_helper
                else "Requests I Created"
            )
            go_to("My Requests")

        st.markdown(
            f"""
            <div class="journey-hover-card journey-request-card" style="
                padding: 14px 18px;
                border-radius: 12px;
                border: 1px solid rgba(128,128,128,0.18);
                background: rgba(25,185,104,0.04);
                margin: 8px 0 12px 0;
            ">
                <div style="font-size:12px; opacity:0.7;
                            margin-bottom:6px;">
                    🤝 &nbsp; HELP CONNECTION
                </div>
                <div style="font-size:20px; font-weight:700;
                            line-height:1.3;">
                    {request['title']}
                </div>
                <div style="font-size:13px; margin-top:10px;
                            opacity:0.8;">
                    Requester: {request['requester_name']}
                    &nbsp; · &nbsp;
                    Helper: {request['helper_name'] or 'Not assigned'}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        progress_labels = {
            "Not Started": "Accepted — journey not started",
            "In Progress": "On the way",
            "Arrived": "Arrived at the request location",
        }

        status_colors = {
            "Not Started": "#64748b",
            "In Progress": "#19B968",
            "Arrived": "#2583E9",
        }

        st.markdown(
            f"""
            <div class="journey-hover-card journey-status-card" style="
                display:flex;
                align-items:center;
                gap:10px;
                padding:10px 14px;
                border-radius:12px;
                border:1px solid rgba(128,128,128,0.2);
                margin-bottom:8px;
            ">
                <div style="
                    width:10px;
                    height:10px;
                    border-radius:50%;
                    background:{status_colors.get(journey_status, '#64748b')};
                    flex-shrink:0;
                "></div>
                <div>
                    <div style="font-weight:650;font-size:15px;">
                        🚦 &nbsp; {progress_labels.get(journey_status, journey_status)}
                    </div>
                    <div style="font-size:12px;opacity:0.7;margin-top:3px;">
                        Journey status
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        
        # -------------------------------------------------
        # PERSISTENT JOURNEY ACTION AREA
        # -------------------------------------------------

        if is_helper and request["status"] == "Accepted":

            with st.container(border=True):

                if journey_status == "Not Started":

                    st.markdown("#### 🚶 Ready to start?")
                    st.caption(
                        "Start your journey when you are ready to "
                        "travel to the requester."
                    )

                    if st.button(
                        "🚶 Start Journey",
                        type="primary",
                        key=f"start_journey_{request_id}",
                        use_container_width=True,
                    ):
                        if update_journey_status(
                            request_id,
                            viewer_id,
                            "In Progress",
                        ):
                            st.success("Journey started.")
                            st.rerun()
                        else:
                            st.warning(
                                "The journey status changed. "
                                "Refresh and try again."
                            )

                elif journey_status == "In Progress":

                    st.markdown("#### 🟢 Journey Started")
                    st.caption(
                        "Your journey is active. Keep location sharing "
                        "enabled while travelling to the requester."
                    )

                elif journey_status == "Arrived":

                    st.markdown("#### 📍 Journey Completed")
                    st.caption(
                        "Your arrival at the request location has been recorded."
                    )

        # -------------------------------------------------
        # JOURNEY COORDINATES
        # -------------------------------------------------

        destination_lat = request["latitude"]
        destination_lon = request["longitude"]

        helper_lat = request["helper_latitude"]
        helper_lon = request["helper_longitude"]

        has_helper_location = (
            helper_lat is not None
            and helper_lon is not None
        )

        # -------------------------------------------------
        # HELPER LOCATION STATUS CARD
        # -------------------------------------------------

        if journey_status == "In Progress":

            if has_helper_location:
                location_label = "Helper location available"
                location_color = "#19B968"
                location_message = (
                    "A helper location is saved and shown on the map."
                )
            else:
                location_label = "Waiting for helper location"
                location_color = "#D97706"
                location_message = (
                    "The map will show the helper once a location is shared."
                )

            st.markdown(
                f"""
                <div class="journey-hover-card journey-location-card" style="
                    display:flex;
                    align-items:flex-start;
                    gap:10px;
                    padding:10px 14px;
                    margin:0 0 8px 0;
                    border:1px solid rgba(128,128,128,0.22);
                    border-radius:12px;
                ">
                    <span style="
                        width:9px;
                        height:9px;
                        margin-top:5px;
                        border-radius:50%;
                        background:{location_color};
                        flex-shrink:0;
                    "></span>
                    <div>
                        <div style="font-weight:650;">
                            📍 &nbsp; {location_label}
                        </div>
                        <div style="
                            font-size:12px;
                            opacity:0.72;
                            margin-top:3px;
                        ">
                            {location_message}
                        </div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        # -------------------------------------------------
        # GPS TRACKER — HELPER ONLY
        # Kept below the visible status cards to avoid
        # inserting the tracker between those cards.
        # -------------------------------------------------

        if (
            is_helper
            and request["status"] == "Accepted"
            and journey_status == "In Progress"
        ):

            gps_update = neki_gps_tracker(
                active=True,
                key=f"journey_gps_{request_id}",
            )

            if isinstance(gps_update, dict):
                event_time = gps_update.get("sent_at")
                processed_key = (
                    f"journey_gps_last_event_{request_id}"
                )

                if (
                    event_time
                    and event_time
                    != st.session_state.get(processed_key)
                ):
                    if gps_update.get("error"):
                        st.session_state[processed_key] = event_time
                        st.warning(
                            "Neki could not access your location: "
                            f"{gps_update['error']} "
                            "Check your browser's location permission "
                            "and reload the journey page."
                        )

                    elif (
                        gps_update.get("latitude") is not None
                        and gps_update.get("longitude") is not None
                    ):
                        location_saved = update_journey_location(
                            request_id,
                            viewer_id,
                            gps_update["latitude"],
                            gps_update["longitude"],
                        )

                        st.session_state[processed_key] = event_time

                        if not location_saved:
                            st.warning(
                                "Your location was received, but Neki "
                                "could not save it. Check that the "
                                "journey is still active."
                            )

        navigation_url = None
        if destination_lat is None or destination_lon is None:
            st.warning(
                "This request has no saved map coordinates. "
                "A route cannot be calculated for it."
            )

        else:
            destination = [
                float(destination_lat),
                float(destination_lon),
            ]

            navigation_url = (
                "https://www.google.com/maps/dir/?api=1"
                f"&destination={destination[0]},{destination[1]}"
                "&travelmode=driving"
            )

            if (
                helper_lat is not None
                and helper_lon is not None
            ):
                navigation_url += (
                    f"&origin={float(helper_lat)},{float(helper_lon)}"
                )

            has_helper_location = (
                helper_lat is not None
                and helper_lon is not None
            )

            if has_helper_location:
                origin = [
                    float(helper_lat),
                    float(helper_lon),
                ]
            else:
                origin = None

            if (
                is_helper
                and request["status"] == "Accepted"
                and journey_status == "In Progress"
            ):
                map_center = origin or [20.5937, 78.9629]
            else:
                map_center = origin or destination

            map_view_key = f"journey_map_view_{request_id}"
            saved_map_view = st.session_state.get(map_view_key, {})

            route = None

            if has_helper_location:
                route = get_driving_route(
                    origin[0],
                    origin[1],
                    destination[0],
                    destination[1],
                )

            # Send map data to the persistent browser-side component.
            # Do not rebuild the Folium map on every rerun.
            neki_journey_map(
                request_id=str(request_id),
                destination=destination,
                helper=origin,
                route=route["coordinates"] if route else None,
                center=saved_map_view.get("center", map_center),
                zoom=saved_map_view.get(
                    "zoom",
                    13 if origin else 14,
                ),
                key=f"journey_map_{request_id}",
                default=None,
            )    


            if route:
                st.html(
                    f"""
                    <div style="
                        display:flex;
                        gap:12px;
                        flex-wrap:wrap;
                        margin:8px 0 12px 0;
                    ">
                        <div class="journey-hover-card journey-metric-card" style="
                            flex:1;
                            min-width:150px;
                            padding:12px 14px;
                            border-radius:10px;
                            border:1px solid rgba(128,128,128,0.22);
                           
                            background:rgba(128,128,128,0.05);
                        ">
                            <div style="font-size:12px;opacity:0.7;">
                                🛣️ &nbsp; ROAD DISTANCE
                            </div>
                            <div style="font-size:24px;font-weight:700;
                                        margin-top:5px;">
                                {route['distance_km']:.1f} km
                            </div>
                        </div>
                        <div class="journey-hover-card journey-metric-card" style="
                            flex:1;
                            min-width:150px;
                            padding:12px 14px;
                            border-radius:10px;
                            border:1px solid rgba(128,128,128,0.22);
                    
                            background:rgba(128,128,128,0.05);
                        ">
                            <div style="font-size:12px;opacity:0.7;">
                                ⏱️ &nbsp; ESTIMATED DRIVE
                            </div>
                            <div style="font-size:24px;font-weight:700;
                                        margin-top:5px;">
                                {route['duration_min']:.0f} min
                            </div>
                        </div>
                    </div>
                    """
                )

            elif has_helper_location:
                st.warning(
                    "The road-routing service did not return a route. "
                    "The map still shows the saved locations."
                )

            else:
                st.caption(
                    "The destination is shown. The road route appears "
                    "when the helper has shared a location."
                )

            

            

            # -------------------------------------------------
            # ARRIVAL ACTION
            # -------------------------------------------------

            if (
                is_helper
                and request["status"] == "Accepted"
                and journey_status == "In Progress"
            ):
                if st.button(
                    "📍 Mark Arrived",
                    type="primary",
                    key=f"arrived_journey_{request_id}",
                    use_container_width=False,
                ):
                    if update_journey_status(
                        request_id,
                        viewer_id,
                        "Arrived",
                    ):
                        st.success("Arrival recorded.")
                        st.rerun()
                    else:
                        st.warning(
                            "The journey status changed. Refresh and try again."
                        )

        # -------------------------------------------------
        # JOURNEY ACTIONS — NAVIGATION + CHAT
        # -------------------------------------------------

        if request["status"] in (
            "Accepted",
            "Help Provided",
            "Completed",
        ):

            

            action_col1, action_col2 = st.columns(2, gap="medium")

            with action_col1:
                if navigation_url:
                    st.markdown(
                        f"""
                        <a href="{navigation_url}"
                        target="_blank"
                        rel="noopener noreferrer"
                        class="neki-navigation-btn"
                        style="
                            display:flex;
                            align-items:center;
                            justify-content:center;
                            box-sizing:border-box;
                            width:100%;
                            min-height:42px;
                            padding:10px 16px;
                            border:1px solid #19B968;
                            border-radius:8px;
                            background:#19B968;
                            color:#07150D;
                            text-decoration:none;
                            font-size:14px;
                            font-weight:600;
                            text-align:center;
                            cursor:pointer;
                            transition:all .2s ease;
                        ">
                            🧭 Open Navigation
                        </a>
                        """,
                        unsafe_allow_html=True,
                    )
                else:
                    st.button(
                        "🧭 Navigation unavailable",
                        disabled=True,
                        use_container_width=True,
                        key=f"navigation_unavailable_{request_id}",
                    )

            
            
            with action_col2:
                components.html(
                    """
                    <!DOCTYPE html>
                    <html>
                    <body style="margin:0; padding:0;">
                        <button
                            type="button"
                            onclick="
                                const target = window.parent.document
                                    .getElementById('neki-private-chat');

                                if (target) {
                                    target.scrollIntoView({
                                        behavior: 'smooth',
                                        block: 'start'
                                    });
                                }
                            "
                            style="
                                width:100%;
                                height:42px;
                                border:1px solid #19B968;
                                border-radius:8px;
                                background:transparent;
                                color:#19B968;
                                font-size:14px;
                                font-weight:600;
                                cursor:pointer;
                                transition:all .2s ease;
                            "
                        >
                            💬 Private Chat
                        </button>
                    <style>
                        button:hover {
                            background:#EAF8EF !important;
                            color:#16834B !important;
                            border-color:#16834B !important;
                            box-shadow:0 4px 12px rgba(25,185,104,.16);
                            transform:translateY(-1px);
                        }

                        button:active {
                            transform:translateY(0);
                            box-shadow:none;
                        }
                    </style>
                    </body>
                    </html>
                    """,
                    height=48,
                    scrolling=False,
                )


        # -------------------------------------------------
        # PRIVATE CHAT — CONNECTION PARTICIPANTS ONLY
        # -------------------------------------------------

        
        if request["status"] in (
            "Accepted",
            "Help Provided",
            "Completed",
        ):
            with st.container(key="neki-chat-panel"):
                st.markdown(
                    """
                    <div class="neki-chat-header" id="neki-private-chat">
                        <div class="neki-chat-title">
                            💬 Private connection chat
                        </div>
                        <div class="neki-chat-subtitle">
                            Messages between the requester and helper
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                messages = get_request_messages(
                    request_id,
                    viewer_id,
                )

            

                
                with st.container(
                    height=280,
                    key="neki-chat-history",
                ):
                    if not messages:
                        st.markdown(
                            """
                            <div class="neki-chat-empty">
                                👋 No messages yet.<br>
                                Send a message to start the conversation.
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )
                    else:
                        import html

                        for message in messages:
                            sender_name = html.escape(
                                str(
                                    message["sender_name"]
                                    if "sender_name" in message.keys()
                                    else "Neighbour"
                                )
                            )
                            message_text = html.escape(
                                str(
                                    message["message"]
                                    if "message" in message.keys()
                                    else ""
                                )
                            ).replace("\n", "<br>")

                            is_mine = (
                                str(message["sender_name"]).strip().casefold()
                                == str(st.session_state.user_name).strip().casefold()
                            )
                            bubble_class = "mine" if is_mine else "theirs"

                            created_at = html.escape(
                                str(
                                    message["created_at"]
                                    if "created_at" in message.keys()
                                    else ""
                                )
                            )

                            st.markdown(
                                f"""
                                <div class="neki-chat-row {bubble_class}">
                                    <div class="neki-chat-bubble">
                                        <div class="neki-chat-sender">
                                            {sender_name}
                                        </div>
                                        <div>{message_text}</div>
                                        <div class="neki-chat-time">
                                            {created_at}
                                        </div>
                                    </div>
                                </div>
                                """,
                                unsafe_allow_html=True,
                            )


                with st.form(
                    key=f"journey_chat_form_{request_id}",
                    clear_on_submit=True,
                ):
                    message_text = st.text_area(
                        "Message",
                        max_chars=2000,
                        placeholder="Type a message...",
                        key=f"journey_chat_input_{request_id}",
                        label_visibility="collapsed",
                    )

                    send_message = st.form_submit_button(
                        "➤ Send Message",
                        use_container_width=True,
                    )

                if send_message:
                    if not message_text.strip():
                        st.warning("Please enter a message.")
                    elif send_request_message(
                        request_id,
                        viewer_id,
                        message_text,
                    ):
                        st.success("Message sent.")
                        st.rerun()
                    else:
                        st.error(
                            "The message could not be sent. "
                            "Please refresh and try again."
                        )


        if request["status"] == "Help Provided":
            st.info(
                "Your existing help-completion workflow remains unchanged."
            )

        elif request["status"] == "Completed":
            st.success("This help request is completed.")


# =========================================================
# RATINGS
# =========================================================

elif st.session_state.page == "Ratings":

    st.markdown(
        '<div class="ratings-page"></div>',
        unsafe_allow_html=True,
    )

    mark_rating_notifications_read(
        st.session_state.user_id
    )

    st.session_state.rating_unread_count = 0    

    page_header(
        "My Ratings ",
        "Your reputation within the community.",
        show_back=True,
    )

    average_rating, total_ratings = get_user_rating_stats(
        st.session_state.user_id
    )

    people_helped = get_people_helped_count(
        st.session_state.user_id
    )

    current_user = get_user_by_id(st.session_state.user_id)

    trust_score = (
        current_user["trust_score"]
        if current_user
        else 50
    )

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown(
            f"""
            <div class="card rating-stat-card rating-card-average">
                <div class="stat-title">Average Rating</div>
                <div class="stat-number">⭐ {average_rating:.1f}</div>
                <div class="request-meta">
                    Based on {total_ratings} rating(s)
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col2:
        st.markdown(
            f"""
            <div class="card rating-stat-card rating-card-average">
                <div class="stat-title">People Helped</div>
                <div class="stat-number">🤝 {people_helped}</div>
                <div class="request-meta">
                    Completed help requests
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("### Recent Reviews")

    reviews = get_received_reviews(st.session_state.user_id)

    if not reviews:
        st.info(
            "No written reviews yet. "
            "Reviews from completed help requests will appear here."
        )

    else:
        for review in reviews:

            reviewer_name = review["reviewer_name"] or "Community Member"
            request_title = review["request_title"] or "Completed Help Request"
            review_text = (review["review"] or "").strip()

            stars = "⭐" * int(review["rating"])

            st.html(
                f"""
                <div class="neki-review-card">

                    <div class="neki-review-top">

                        <div class="neki-review-person">

                            <div class="neki-review-avatar">
                                {reviewer_name[0].upper()}
                            </div>

                            <div class="neki-review-person-info">

                                <div class="neki-review-name">
                                    {reviewer_name}
                                </div>

                                <div class="neki-review-request">
                                    {request_title}
                                </div>

                            </div>

                        </div>


                        <div class="neki-review-stars">
                            {stars}
                        </div>

                    </div>


                    <div class="neki-review-divider"></div>


                    <div class="neki-review-text">
                        “{review_text}”
                    </div>


                    <div class="neki-review-footer">
                        <span class="neki-review-dot"></span>
                        Community review
                    </div>

                </div>
                """
            )

    with col3:
        st.markdown(
            f"""
            <div class="card rating-stat-card rating-card-average">
                <div class="stat-title">Trust Score</div>
                <div class="stat-number">{trust_score:.1f}/100</div>
                <div class="request-meta">
                    Community trust based on requester feedback
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


# =========================================================
# NOTIFICATIONS
# =========================================================
elif st.session_state.page == "Notifications":

    st.markdown(
        '<div class="notifications-page"></div>',
        unsafe_allow_html=True,
    )

    page_header(
        "Notifications ",
        "Stay updated on your requests, help connections and account activity.",
        show_back=True,
    )

    user_id = st.session_state.user_id

    notifications = get_notifications(
        user_id,
        limit=50
    )

    unread_count = get_unread_notification_count(
        user_id
    )

    # -----------------------------------------------------
    # HEADER / MARK ALL AS READ
    # -----------------------------------------------------

    top_col1, top_col2 = st.columns([3, 1])

    with top_col1:

        if unread_count == 0:
            st.markdown(
                "**You're all caught up.**"
            )
        elif unread_count == 1:
            st.markdown(
                "**You have 1 unread notification.**"
            )
        else:
            st.markdown(
                f"**You have {unread_count} unread notifications.**"
            )

    with top_col2:

        if unread_count > 0:

            if st.button(
                "✓ Mark all as read",
                use_container_width=True,
                key="mark_all_notifications",
            ):

                mark_all_notifications_read(
                    user_id
                )

                st.rerun()

    st.markdown("")

    # -----------------------------------------------------
    # EMPTY STATE
    # -----------------------------------------------------

    if not notifications:

        st.html(
            """
            <div style="
                text-align:center;
                padding:60px 20px;
                border:1px solid #303642;
                border-radius:16px;
                background:#171A21;
            ">
                <div style="
                    font-size:42px;
                    margin-bottom:12px;
                ">
                    🔔
                </div>

                <div style="
                    font-size:18px;
                    font-weight:700;
                    color:#F5F7FA;
                ">
                    No notifications yet
                </div>

                <div style="
                    margin-top:8px;
                    font-size:14px;
                    color:#8F9AAF;
                ">
                    You'll see updates about your activity here.
                </div>
            </div>
            """
        )

    # -----------------------------------------------------
    # NOTIFICATION LIST
    # -----------------------------------------------------

    else:

        icon_map = {
            "request_accepted": "🤝",
            "help_provided": "🙌",
            "help_completed": "✅",
            "rating_received": "⭐",
            "admin_action": "🛡️",
            "request_removed": "🗑️",
            "request_restored": "♻️",
            "account_suspended": "⚠️",
            "account_banned": "🚫",
            "account_restored": "🔓",
            "general": "🔔",
        }

        for notification in notifications:

            notification_id = notification["id"]
            notification_type = notification["type"] or "general"

            icon = icon_map.get(
                notification_type,
                "🔔"
            )

            title = notification["title"] or "Notification"
            message = notification["message"] or ""
            created_at = notification["created_at"]

            is_read = notification["is_read"] == 1

            # -------------------------------------------------
            # NOTIFICATION CARD
            # -------------------------------------------------

            border_color = "#303642"

            if not is_read:
                border_color = "#F97316"

            unread_badge = ""

            if not is_read:
                unread_badge = """
                    <span style="
                        display:inline-block;
                        margin-left:8px;
                        padding:3px 8px;
                        border-radius:20px;
                        background:#3A291C;
                        color:#FDBA74;
                        font-size:10px;
                        font-weight:700;
                    ">
                        NEW
                    </span>
                """

            st.html(
                f"""
            <div class="neki-notification-card {'is-unread' if not is_read else 'is-read'}" style="
                background:#171A21;
                border:1px solid {border_color};
                border-radius:16px;
                padding:20px;
                margin-bottom:12px;
                color:#F5F7FA;
            ">

                <div style="
                    display:flex;
                    align-items:flex-start;
                    gap:14px;
                ">

                    <div style="
                        width:42px;
                        height:42px;
                        min-width:42px;
                        border-radius:12px;
                        background:#242833;
                        display:flex;
                        align-items:center;
                        justify-content:center;
                        font-size:21px;
                    ">
                        {icon}
                    </div>

                    <div style="
                        flex:1;
                        min-width:0;
                    ">

                        <div style="
                            display:flex;
                            align-items:center;
                            flex-wrap:wrap;
                            font-size:15px;
                            font-weight:700;
                            color:#F5F7FA;
                        ">
                            {title}
                            {unread_badge}
                        </div>

                        <div style="
                            margin-top:7px;
                            font-size:14px;
                            line-height:1.5;
                            color:#B8C0CE;
                        ">
                            {message}
                        </div>

                        <div style="
                            margin-top:10px;
                            font-size:12px;
                            color:#737D8F;
                        ">
                            🕒 {created_at}
                        </div>

                    </div>

                </div>

            </div>
            """
            )
            
            # -------------------------------------------------
            # MARK INDIVIDUAL NOTIFICATION AS READ
            # -------------------------------------------------

            if not is_read:

                if st.button(
                    "Mark as read",
                    key=f"read_notification_{notification_id}",
                ):

                    mark_notification_read(
                        notification_id,
                        user_id
                    )

                    st.rerun()

# =========================================================
# PROFILE
# =========================================================

elif st.session_state.page == "Profile":

    st.markdown(
        '<div class="profile-page"></div>',
        unsafe_allow_html=True,
    )

    page_header(
        "My Profile 👤",
        "Manage your community profile.",
        show_back=True,
    )

    # -----------------------------------------------------
    # Get the latest profile data from the database
    # -----------------------------------------------------

    current_user = get_user_by_id(
        st.session_state.user_id
    )

    if st.session_state.pop("profile_updated", False):
        st.success("Profile updated successfully. ✅")

    if current_user is None:

        st.error(
            "Unable to load your profile."
        )

    else:

        current_name = current_user["name"]
        current_email = current_user["email"]
        current_location = current_user["location"]
        current_phone = current_user["phone"]
        phone_verified = bool(current_user["phone_verified"])

        # Keep session state synchronized with database
        st.session_state.user_name = current_name

        # -------------------------------------------------
        # PROFILE HEADER
        # -------------------------------------------------

        st.markdown(
            f"""<div class="card profile-identity-card">
        <div class="profile-head">
        <div class="avatar">👤</div>
        <div>
        <div class="request-title">{current_name}</div>
        <div class="request-meta">Community member</div>
        </div>
        </div>
        </div>""",
            unsafe_allow_html=True,
        )

        st.markdown("")

        # -------------------------------------------------
        # PROFILE DETAILS
        # -------------------------------------------------

        with st.container(border=True):

            
            st.markdown(
                '<div style="font-size:18px;font-weight:750;'
                'margin-bottom:10px;color:var(--text-color);">'
                'Name</div>',
                unsafe_allow_html=True,
            )
            name = st.text_input(
                "Name",
                value=current_name,
                key="profile_name",
                label_visibility="collapsed",
            )

            st.markdown(
                '<div style="font-size:18px;font-weight:750;'
                'margin:18px 0 10px;color:var(--text-color);">'
                'Email</div>',
                unsafe_allow_html=True,
            )
            st.text_input(
                "Email",
                value=current_email,
                disabled=True,
                key="profile_email",
                label_visibility="collapsed",
            )


            # -------------------------------------------------
            # PHONE NUMBER
            # -------------------------------------------------

            current_phone = current_user["phone"] or ""

            st.markdown("### 📱 Contact Information")

            phone = st.text_input(
                "Phone Number",
                value=current_phone,
                placeholder="+91XXXXXXXXXX",
                key="profile_phone",
            )

            st.caption(
                "Your phone number will only be shared with the "
                "neighbour involved in an accepted help request."
            )

            if current_phone:
                if current_user["phone_verified"]:
                    st.success("Phone number verified. ✅")
                else:
                    st.warning("Phone number added — verification pending.")
            else:
                st.info("Add your phone number so neighbours can contact you after a request is accepted.")                


            
            st.markdown(
                '<div style="font-size:18px;font-weight:750;'
                'margin:18px 0 10px;color:var(--text-color);">'
                'Location</div>',
                unsafe_allow_html=True,
            )
            location = st.text_input(
                "Location",
                value=current_location,
                key="profile_location",
                label_visibility="collapsed",
            )


            
            # -------------------------------------------------
            # SKILLS — PREMIUM PROFILE EDITOR
            # -------------------------------------------------

            st.markdown(
                """
                <div class="profile-skills-heading">
                    <div class="profile-skills-title">
                        Skills &amp; What I Can Offer
                    </div>
                    <div class="profile-skills-subtitle">
                        Share what you know and help your neighbours.
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            with st.container(key="profile_skills_editor"):

                
                with st.form("add_profile_skill_form"):
                    input_col, button_col = st.columns(
                        [4, 1.15],
                        vertical_alignment="center",
                    )

                    with input_col:
                        new_skill = st.text_input(
                            "Skill",
                            placeholder="e.g. First Aid, Tutoring, Cooking",
                            max_chars=40,
                            label_visibility="collapsed",
                            key="profile_new_skill",
                        )

                    with button_col:
                        add_skill_clicked = st.form_submit_button(
                            "＋ Add Skill",
                            type="primary",
                            use_container_width=True,
                        )


                if add_skill_clicked:
                    if not new_skill.strip():
                        st.warning("Please enter a skill.")

                    elif add_user_skill(
                        st.session_state.user_id,
                        new_skill,
                    ):
                        st.success("Skill added successfully.")
                        st.rerun()

                    else:
                        st.warning(
                            "This skill already exists or is invalid."
                        )

                current_skills = get_user_skills(
                    st.session_state.user_id
                )

                if current_skills:
                    st.markdown(
                        '<div class="profile-skills-list">',
                        unsafe_allow_html=True,
                    )

                    for skill_row in current_skills:
                        skill_col, delete_col = st.columns(
                            [5, 0.65],
                            vertical_alignment="center",
                        )

                        with skill_col:
                            st.markdown(
                                f"""
                                <span class="profile-skill-chip">
                                    {html.escape(skill_row["skill"])}
                                </span>
                                """,
                                unsafe_allow_html=True,
                            )

                        with delete_col:
                            if st.button(
                                "×",
                                key=f"delete_skill_{skill_row['id']}",
                                help=f"Remove {skill_row['skill']}",
                                use_container_width=True,
                            ):
                                if delete_user_skill(
                                    st.session_state.user_id,
                                    skill_row["id"],
                                ):
                                    st.rerun()
                                else:
                                    st.error(
                                        "Unable to remove this skill."
                                    )

                    st.markdown("</div>", unsafe_allow_html=True)

                else:
                    st.markdown(
                        """
                        <div class="profile-skills-empty">
                            <span class="profile-skills-empty-icon">✳</span>
                            <div>No skills added yet</div>
                            <small>
                                Add your first skill to show neighbours
                                how you can help.
                            </small>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

            st.markdown("")
            

            if st.button(
                "Save Changes",
                type="primary",
                use_container_width=True,
            ):

                name = name.strip()
                location = location.strip()
                phone = phone.strip()

                if not name:

                    st.error(
                        "Name cannot be empty."
                    )

                elif not location:

                    st.error(
                        "Location cannot be empty."
                    )

                elif phone and not phone.startswith("+"):

                    st.error(
                        "Please enter your phone number with country code, "
                        "for example +91XXXXXXXXXX."
                    )

                elif phone and not phone[1:].isdigit():

                    st.error(
                        "Please enter a valid phone number."
                    )

                else:

                    updated = update_user(
                        st.session_state.user_id,
                        name,
                        location,
                        phone,
                    )

                    if updated:

                        st.session_state.user_name = name
                        st.session_state.profile_updated = True

                        st.rerun()

                    else:

                        st.error(
                            "Unable to update your profile. "
                            "Please try again."
                        )


# =========================================================
# CONNECTION PROFILE
# =========================================================

elif st.session_state.page == "Connection Profile":

    profile_user_id = st.session_state.get(
        "profile_view_user_id"
    )
    profile_is_public = st.session_state.get(
        "profile_is_public",
        False,
    )

    profile_request_id = st.session_state.get(
        "profile_view_request_id"
    )

    if profile_is_public:
        profile_subtitle = (
            "Public profile information for this help match."
        )
    else:
        profile_subtitle = (
            "Contact details for your accepted help connection."
        )

    page_header(
        "Neighbour Profile 👤",
        profile_subtitle,
        show_back=True,
    )


    if not profile_user_id:

        st.error(
            "Unable to open this profile."
        )

    else:

        if profile_is_public and profile_request_id:

            profile = get_match_profile(
                request_id=profile_request_id,
                viewer_id=st.session_state.user_id,
            )

        else:

            profile = get_user_by_id(
                profile_user_id
            )

        if profile is None:

            st.error(
                "This profile is no longer available."
            )

        else:

            # -------------------------------------------------
            # PROFILE HEADER
            # -------------------------------------------------

            st.html(
                f"""
                <div class="card">

                    <div class="profile-head">

                        <div class="avatar">
                            👤
                        </div>

                        <div>

                            <div class="request-title">
                                {profile["name"]}
                            </div>

                            <div class="request-meta">
                                Community member
                            </div>

                        </div>

                    </div>

                </div>
                """
            )

            if not profile_is_public:

                # -------------------------------------------------
                # CONTACT INFORMATION
                # -------------------------------------------------

                with st.container(border=True):

                    st.markdown("### 📞 Contact Information")

                    email = profile["email"]

                    phone = profile["phone"]

                    if email:
                        st.markdown(
                            f"**📧 Email:** {email}"
                        )

                    if phone:
                        st.markdown(
                            f"**📱 Phone:** {phone}"
                        )
                    else:
                        st.info(
                            "Phone number has not been added yet."
                        )

                    st.markdown("")

                    st.caption(
                        "This contact information is visible because "
                        "you are connected through an accepted help request."
                    )

            # -------------------------------------------------
            # LOCATION
            # -------------------------------------------------

            with st.container(border=True):

                st.markdown("### 📍 Location")

                st.write(
                    profile["location"]
                )
            
            
            # -------------------------------------------------
            # SKILLS
            # -------------------------------------------------

            profile_skills = get_user_skills(profile_user_id)

            with st.container(key="public_profile_skills", border=True):
                st.markdown("### 🛠️ Skills")

                if profile_skills:
                    skill_tags = (
                        '<div class="public-profile-skill-list">'
                        + "".join(
                            f'<span class="public-profile-skill-chip">'
                            f'{html.escape(skill["skill"])}</span>'
                            for skill in profile_skills
                        )
                        + '</div>'
                    )
                    st.markdown(skill_tags, unsafe_allow_html=True)
                else:
                    st.caption("No skills added yet.")

            # -------------------------------------------------
            # RATING & COMMUNITY ACTIVITY
            # -------------------------------------------------

            average_rating, total_ratings = get_user_rating_stats(
                profile_user_id
            )

            completed_helps = get_people_helped_count(
                profile_user_id
            )

            with st.container(border=True):

                st.markdown("### ⭐ Community Reputation")

                stat_col1, stat_col2, stat_col3 = st.columns(3)

                with stat_col1:
                    st.metric(
                        "⭐ Rating",
                        f"{average_rating:.1f}/5"
                        if total_ratings
                        else "New"
                    )

                with stat_col2:
                    st.metric(
                        "🛡 Trust Score",
                        f"{(profile['trust_score'] or 50):.0f}/100"
                    )

                with stat_col3:
                    st.metric(
                        "🤝 Completed Helps",
                        completed_helps
                    )

                if total_ratings:
                    st.caption(
                        f"Based on {total_ratings} rating"
                        f"{'s' if total_ratings != 1 else ''}."
                    )
                else:
                    st.caption(
                        "No ratings yet."
                    )

            # -------------------------------------------------
            # TRUST & VERIFICATION
            # -------------------------------------------------

            with st.container(border=True):

                st.markdown("### ⭐ Trust & Verification")

                trust_score = profile["trust_score"] or 50

                st.write(
                    f"⭐ Trust Score: **{trust_score:.0f}/100**"
                )

                if not profile_is_public:

                    if profile["email_verified"]:
                        st.write(
                            "✅ Email verified"
                        )

                    if profile["phone_verified"]:
                        st.write(
                            "📱 Phone verified"
                        )


            # -------------------------------------------------
            # REPORT PROFILE
            # -------------------------------------------------

            render_report_action(
                report_key=f"profile_{profile_user_id}",
                reported_user_id=profile_user_id,
                request_id=None,
                report_type="Profile",
            )

            st.markdown("")


            st.markdown("")

            back_page = st.session_state.get(
                "profile_return_page",
                "My Requests",
            )

            back_label = (
                "← Back to Find Help"
                if back_page == "Find Help"
                else "← Back to My Requests"
            )

            if st.button(
                back_label,
                use_container_width=True,
            ):
                st.session_state.profile_is_public = False
                st.session_state.profile_view_request_id = None
                st.session_state.page = back_page
                st.rerun()



# =========================================================
# ADMIN PANEL
# =========================================================

elif st.session_state.page == "Admin":

    if st.session_state.user_role != "Admin":
        st.error(
            "You do not have permission to access this page."
        )

        if st.button("← Back to Dashboard"):
            go_to("Dashboard")

    else:

        st.markdown(
            '<div class="admin-panel-page"></div>',
            unsafe_allow_html=True,
        )

        page_header(
            "Admin Panel 🛡️",
            "Manage and monitor the NeighbourHelp community.",
            show_back=True,
        )

        # ---------------------------------------------------------
        # ADMIN STATISTICS
        # ---------------------------------------------------------

        stats = get_admin_statistics()

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric(
                "Total Users",
                stats["total_users"]
            )

        with col2:
            st.metric(
                "Help Requests",
                stats["total_requests"]
            )

        with col3:
            st.metric(
                "Completed",
                stats["completed_requests"]
            )

        with col4:
            st.metric(
                "Reports",
                stats["total_reports"]
            )

        st.markdown("### Administration")

        tab1, tab2, tab3 = st.tabs(
            [
                "👥 Users",
                "📋 Requests",
                "🚨 Reports",
            ]
        )

        with tab1:

            st.markdown("### Community Users")

            users = get_all_users()

            if not users:
                st.info("No users found.")

            else:

                for user in users:

                    user_status = user["moderation_status"]

                    # -------------------------------------------------
                    # COMPLETE USER BLOCK
                    # -------------------------------------------------

                    with st.container(border=True):
                        is_light_theme = st.session_state.get(
                            "theme",
                            "dark",
                        ) == "light"

                        admin_name_color = (
                            "#17201A"
                            if is_light_theme
                            else "#F5F7FA"
                        )

                        admin_email_color = (
                            "#536159"
                            if is_light_theme
                            else "#8FA0B5"
                        )                                
                        # USER INFORMATION
                        st.html(
                            f"""
                            <div style="
                                padding: 4px 4px 8px 4px;
                            ">

                                <div style="
                                    color:{admin_name_color};
                                    font-size:17px;
                                    font-weight:700;
                                    margin-bottom:8px;
                                ">
                                    {user["name"]}
                                </div>

                                <div style="
                                    color:{admin_email_color};
                                    font-size:13px;
                                    margin-bottom:12px;
                                ">
                                    {user["email"]}
                                </div>

                                <div style="
                                    display:flex;
                                    gap:10px;
                                    align-items:center;
                                ">

                                    <span style="
                                        color:#B8C2D0;
                                        font-size:12px;
                                        padding:5px 10px;
                                        border-radius:8px;
                                        background:rgba(255,255,255,.035);
                                        border:1px solid #30343f;
                                    ">
                                        👤 {user["role"]}
                                    </span>

                                    <span style="
                                        color:{'#FF6B6B' if user_status == 'Banned' else '#55D88A'};
                                        font-size:12px;
                                        font-weight:600;
                                        padding:5px 10px;
                                        border-radius:8px;
                                        background:{'rgba(255,80,80,.08)' if user_status == 'Banned' else 'rgba(85,216,138,.08)'};
                                        border:1px solid {'rgba(255,80,80,.30)' if user_status == 'Banned' else 'rgba(85,216,138,.30)'};
                                    ">
                                        ● {user_status}
                                    </span>

                                </div>
                            </div>
                            """
                        )

                        # -------------------------------------------------
                        # ADMIN ACCOUNT
                        # -------------------------------------------------

                        if user["role"] == "Admin":

                            st.caption(
                                "🛡️ Admin accounts cannot be suspended or banned."
                            )

                        # -------------------------------------------------
                        # BANNED / SUSPENDED USER
                        # -------------------------------------------------

                        elif user_status in ("Suspended", "Banned"):

                            if user["ban_reason"]:
                                st.caption(
                                    f"Reason: {user['ban_reason']}"
                                )

                            if (
                                user_status == "Suspended"
                                and user["banned_until"]
                            ):
                                st.caption(
                                    f"Suspended until: {user['banned_until']}"
                                )

                            if st.button(
                                "🔓 Restore User",
                                key=f"restore_user_{user['id']}",
                                use_container_width=True,
                            ):

                                success = restore_user(user["id"])

                                if success:

                                    st.success(
                                        f"{user['name']} has been restored successfully."
                                    )

                                    st.rerun()

                                else:

                                    st.error(
                                        "Unable to restore this user."
                                    )

                        # -------------------------------------------------
                        # ACTIVE USER
                        # -------------------------------------------------

                        else:

                            with st.expander("⚙️ Moderate User"):

                                moderation_action = st.selectbox(
                                    "Choose action",
                                    [
                                        "No Action",
                                        "Suspend 6 hours",
                                        "Suspend 24 hours",
                                        "Suspend 72 hours",
                                        "Suspend 168 hours",
                                        "Ban User",
                                    ],
                                    key=f"user_moderation_action_{user['id']}",
                                )

                                moderation_reason = st.text_area(
                                    "Reason",
                                    placeholder="Explain why this moderation action is being taken...",
                                    key=f"user_moderation_reason_{user['id']}",
                                    height=100,
                                )

                                if st.button(
                                    "⚡ Apply Moderation",
                                    key=f"apply_user_moderation_{user['id']}",
                                    use_container_width=True,
                                ):

                                    if moderation_action == "No Action":

                                        st.warning(
                                            "Please select a moderation action."
                                        )

                                    elif not moderation_reason.strip():

                                        st.warning(
                                            "Please provide a reason."
                                        )

                                    else:

                                        if moderation_action.startswith(
                                            "Suspend"
                                        ):

                                            hours = int(
                                                moderation_action
                                                .replace("Suspend", "")
                                                .replace("hours", "")
                                                .strip()
                                            )

                                            success = suspend_user(
                                                user["id"],
                                                hours,
                                                moderation_reason,
                                            )

                                        elif moderation_action == "Ban User":

                                            success = ban_user(
                                                user["id"],
                                                moderation_reason,
                                            )

                                        else:

                                            success = False

                                        if success:

                                            st.success(
                                                f"{user['name']} has been moderated successfully."
                                            )

                                            st.rerun()

                                        else:

                                            st.error(
                                                "Unable to apply this moderation action."
                                            )

        with tab2:

            st.markdown("### Community Requests")

            requests = get_admin_requests()

            if not requests:

                st.info("No help requests have been created yet.")

            else:

                # -------------------------------------------------
                # REQUEST STATUS FILTER
                # -------------------------------------------------

                status_filter = st.selectbox(
                    "Filter by status",
                    [
                        "All",
                        "Removed",
                        "Pending",          
                        "Accepted",
                        "Help Provided",
                        "Completed",
                    ],
                    key="admin_request_status_filter",
                )

                if status_filter == "All":
                    filtered_requests = requests

                elif status_filter == "Removed":
                    filtered_requests = [
                        request
                        for request in requests
                        if request["is_removed"]
                    ]

                else:
                    filtered_requests = [
                        request
                        for request in requests
                        if request["status"] == status_filter
                        and not request["is_removed"]
                    ]

                st.caption(
                    f"Showing {len(filtered_requests)} of "
                    f"{len(requests)} requests"
                )

                # -------------------------------------------------
                # REQUEST CARDS
                # -------------------------------------------------

                for request in filtered_requests:

                    status = request["status"]
                    is_removed = request["is_removed"] == 1

                    # -------------------------------------------------
                    # REQUEST STATUS
                    # -------------------------------------------------

                    if is_removed:
                        status_icon = "🔴"
                        display_status = "Removed"
                    elif status == "Pending":
                        status_icon = "🟡"
                        display_status = status
                    elif status == "Accepted":
                        status_icon = "🔵"
                        display_status = status
                    elif status == "Help Provided":
                        status_icon = "🟠"
                        display_status = status
                    elif status == "Completed":
                        status_icon = "🟢"
                        display_status = status
                    else:
                        status_icon = "⚪"
                        display_status = status

                    with st.container(
                        border=True,
                        key=f"admin_request_card_{request['id']}",
                        width=1080,
                        gap="small",
                    ):

                        col1, col2 = st.columns([4, 1])

                        with col1:
                            st.markdown(
                                f"### 📋 {request['title']}"
                            )

                            st.caption(
                                f"Request ID: {request['id']}"
                            )

                        with col2:
                            st.markdown(
                                f"**{status_icon} {display_status}**"
                            )

                        st.write(request["description"])

                        meta1, meta2, meta3 = st.columns(3)

                        with meta1:
                            st.write(
                                f"📁 **Category**  \n"
                                f"{request['category']}"
                            )

                        with meta2:
                            st.write(
                                f"📍 **Location**  \n"
                                f"{request['location']}"
                            )

                        with meta3:

                            if request["helper_id"]:
                                helper_status = "Assigned"
                            else:
                                helper_status = "Not assigned"

                            st.write(
                                f"🤝 **Helper**  \n"
                                f"{helper_status}"
                            )

                        # -------------------------------------------------
                        # BUDGET
                        # -------------------------------------------------

                        budget_type = request["budget_type"]

                        if budget_type == "Paid" and request["budget_amount"] is not None:
                            budget_text = f"₹{request['budget_amount']}"
                        elif budget_type:
                            budget_text = budget_type
                        else:
                            budget_text = "Not specified"

                        st.write(
                            f"💰 **Budget**  \n"
                            f"{budget_text}"
                        )

                        # -------------------------------------------------
                        # REMOVED REQUEST
                        # -------------------------------------------------

                        if is_removed:

                            st.warning(
                                "This request has been removed from the community."
                            )

                            if request["removed_reason"]:
                                st.write(
                                    f"**Removal Reason:** "
                                    f"{request['removed_reason']}"
                                )

                            if request["removed_at"]:
                                st.caption(
                                    f"Removed: {request['removed_at']}"
                                )

                            if st.button(
                                "♻️ Restore Request",
                                key=f"restore_request_{request['id']}",
                                use_container_width=True,
                            ):

                                success = restore_admin_request(
                                    request["id"]
                                )

                                if success:
                                    st.success(
                                        "Request restored successfully."
                                    )
                                    st.rerun()
                                else:
                                    st.error(
                                        "Unable to restore this request."
                                    )

                        st.caption(
                            f"Created: {request['created_at']}"
                        )

        with tab3:

            st.markdown("### 🚨 Reports")

            reports = get_admin_reports()

            if not reports:

                st.success("No reports have been submitted.")

            else:

                for report in reports:

                    report_id = report["id"]

                    with st.container(
                        key=f"admin_report_card_{report_id}",
                        border=True,
                    ):
                        report_type = report["report_type"] or "User"
                        status = report["status"]

                        reporter_name = (
                            report["reporter_name"]
                            or "Unknown User"
                        )

                        reported_user_name = (
                            report["reported_user_name"]
                            or "Unknown User"
                        )

                        request_id = report["request_id"]

                       

                        # -------------------------------------------------
                        # REPORT HEADER
                        # -------------------------------------------------

                        col1, col2 = st.columns([3, 1])

                        with col1:

                            if report_type == "Request":
                                st.markdown(
                                    f"### 📋 Request Report #{report_id}"
                                )
                            else:
                                st.markdown(
                                    f"### 👤 Profile Report #{report_id}"
                                )

                        with col2:

                            if status == "Resolved":
                                st.success("Resolved")
                            else:
                                st.warning("Open")

                        # -------------------------------------------------
                        # REPORT INFORMATION
                        # -------------------------------------------------

                        st.write(
                            f"**Reported User:** "
                            f"{reported_user_name}"
                        )

                        st.write(
                            f"**Reported By:** "
                            f"{reporter_name}"
                        )

                        if request_id:
                            st.write(
                                f"**Request ID:** #{request_id}"
                            )

                        st.write(
                            f"**Reason:** "
                            f"{report['reason']}"
                        )

                        if report["created_at"]:
                            st.caption(
                                f"Reported: {report['created_at']}"
                            )

                        # -------------------------------------------------
                        # RESOLVED INFORMATION
                        # -------------------------------------------------

                        if status == "Resolved":

                            if report["admin_action"]:

                                st.info(
                                    f"**Admin Action:** "
                                    f"{report['admin_action']}"
                                )

                            if report["admin_note"]:

                                st.caption(
                                    f"**Admin Note:** "
                                    f"{report['admin_note']}"
                                )

                            continue

                        # -------------------------------------------------
                        # ADMIN ACTION
                        # -------------------------------------------------

                        st.markdown("#### Admin Action")

                        if report_type == "Request":
                            report_actions = [
                                "No Action",
                                "Suspend 6 hours",
                                "Suspend 24 hours",
                                "Suspend 72 hours",
                                "Suspend 168 hours",
                                "Ban User",
                                "Remove Request",
                            ]
                        else:
                            report_actions = [
                                "No Action",
                                "Suspend 6 hours",
                                "Suspend 24 hours",
                                "Suspend 72 hours",
                                "Suspend 168 hours",
                                "Ban User",
                            ]

                        action = st.selectbox(
                            "Choose action",
                            report_actions,
                            key=f"admin_report_action_{report_id}",
                        )

                        admin_reason = st.text_area(
                            "Admin note / reason",
                            placeholder="Explain the action taken...",
                            key=f"admin_report_reason_{report_id}",
                        )

                        action_col1, action_col2 = st.columns(2)

                        with action_col1:

                            if st.button(
                                "⚡ Take Action",
                                key=f"take_action_{report_id}",
                                use_container_width=True,
                            ):

                                if action == "No Action":

                                    st.warning(
                                        "Please select an action."
                                    )

                                elif not admin_reason.strip():

                                    st.warning(
                                        "Please provide a reason."
                                    )

                                else:

                                    success = take_admin_report_action(
                                        report_id,
                                        action,
                                        admin_reason,
                                    )

                                    if success:

                                        st.success(
                                            "Action completed successfully."
                                        )

                                        st.rerun()

                                    else:

                                        st.error(
                                            "Unable to complete this action."
                                        )

                        with action_col2:

                            if st.button(
                                "✅ Resolve Without Action",
                                key=f"resolve_only_{report_id}",
                                use_container_width=True,
                            ):

                                success = resolve_admin_report(
                                    report_id,
                                    admin_note=admin_reason,
                                    admin_action="No moderation action",
                                )

                                if success:

                                    st.success(
                                        "Report resolved."
                                    )

                                    st.rerun()

                                else:

                                    st.error(
                                        "Unable to resolve the report."
                                    )


# =========================================================
# FOOTER
# =========================================================

st.markdown(
    """
    <div class="app-footer">
        Neki • Neighbours helping neighbours
    </div>
    """,
    unsafe_allow_html=True,
)
