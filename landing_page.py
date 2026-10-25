import streamlit as st
from textwrap import dedent


def render_landing_page(
    on_login,
    on_register,
    on_request_help,
    on_find_help,
):
    # =========================================================
    # LANDING PAGE NAVIGATION
    # =========================================================

    with st.container(key="landing_top_nav"):

        nav_brand, nav_how, nav_community, nav_safety, nav_spacer, nav_login, nav_join = st.columns(
            [1.35, 1.05, 1.05, 1.15, 3.1, 0.75, 1.05],
            gap="small",
        )

        with nav_brand:
            st.html(
                """
                <a href="#neki-hero" class="landing-nav-brand landing-scroll-link">
                    <span class="landing-nav-mark">N</span>
                    <span class="landing-nav-name">Neki</span>
                </a>
                """
            )

        with nav_how:
            st.html(
                """
                <a href="#neki-how-it-works" class="landing-nav-link landing-scroll-link">
                    How it works
                </a>
                """
            )

        with nav_community:
            st.html(
                """
                <a href="#neki-community" class="landing-nav-link landing-scroll-link">
                    Community
                </a>
                """
            )

        with nav_safety:
            st.html(
                """
                <a href="#neki-safety" class="landing-nav-link landing-scroll-link">
                    Trust & Safety
                </a>
                """
            )

        with nav_spacer:
            st.html("<div></div>")

        with nav_login:
            if st.button(
                "Login",
                key="landing_top_login",
                width="content",
            ):
                on_login()

        with nav_join:
            if st.button(
                "Join Neki →",
                key="landing_top_register",
                type="primary",
                width="content",
            ):
                on_register()

    # =========================================================
    # SMOOTH LANDING NAVIGATION
    # =========================================================

    st.html(
        """
        <script>
        document.addEventListener("click", function(event) {

            const link = event.target.closest(".landing-scroll-link");

            if (!link) {
                return;
            }

            const targetId = link.getAttribute("href");

            if (!targetId || !targetId.startsWith("#")) {
                return;
            }

            const target = document.querySelector(targetId);

            if (!target) {
                return;
            }

            event.preventDefault();

            target.scrollIntoView({
                behavior: "smooth",
                block: targetId === "#neki-safety" ? "center" : "start"
            });

            history.replaceState(null, "", targetId);
        });
        </script>
        """,
        unsafe_allow_javascript=True,
    )


    # =========================================================
    # HERO
    # =========================================================

    st.html(
        dedent(
            """
            <section class="neki-hero" id="neki-hero">

                <div class="hero-eyebrow">
                    🤝 COMMUNITY SUPPORT, MADE SIMPLE
                </div>

                <h1>
                    Neighbours helping<br>
                    <span>neighbours.</span>
                </h1>

                <p class="hero-description">
                    Need a hand with something nearby?
                    Or have a little time to help someone?
                    Neki brings neighbours together to make everyday
                    help easier, safer and more human.
                </p>

            </section>
            """
        )
    )

    # =========================================================
    # PRIMARY ACTIONS
    # =========================================================

    action_col1, action_col2 = st.columns(2, gap="large")

    with action_col1:
        st.html(
            dedent(
                """
                <div class="landing-action-card landing-action-help">

                    <div class="landing-action-icon">🙋</div>

                    <div class="landing-action-title">
                        I need help
                    </div>

                    <div class="landing-action-text">
                        Ask your neighbourhood for help with something
                        you need.
                    </div>

                </div>
                """
            )
        )

        if st.button(
            "Request Help →",
            key="landing_request_help",
            use_container_width=True,
            type="primary",
        ):
            on_request_help()

    with action_col2:
        st.html(
            dedent(
                """
                <div class="landing-action-card landing-action-helping">

                    <div class="landing-action-icon">🤝</div>

                    <div class="landing-action-title">
                        I want to help
                    </div>

                    <div class="landing-action-text">
                        Discover people nearby who could use a helping hand.
                    </div>

                </div>
                """
            )
        )

        if st.button(
            "Find Someone to Help →",
            key="landing_find_help",
            use_container_width=True,
        ):
            on_find_help()

    # =========================================================
    # TRUST STRIP
    # =========================================================

    st.html(
        dedent(
            """
            <div class="landing-trust-strip">

                <div>
                    <span class="trust-strip-icon">🛡️</span>
                    <strong>Build Trust</strong>
                    <small>Ratings & Trust Score</small>
                </div>

                <div>
                    <span class="trust-strip-icon">📍</span>
                    <strong>Stay Nearby</strong>
                    <small>Discover local requests</small>
                </div>

                <div>
                    <span class="trust-strip-icon">🔒</span>
                    <strong>Connect Safely</strong>
                    <small>Private details after approval</small>
                </div>

            </div>
            """
        )
    )

    # =========================================================
    # HOW NEKI WORKS
    # =========================================================

    st.html(
        dedent(
            """
            <section class="landing-section" id="neki-how-it-works">

                <div class="landing-section-heading">
                    <div class="section-kicker">HOW IT WORKS</div>

                    <h2>
                        Simple help.<br>
                        Real connections.
                    </h2>

                    <p>
                        Neki makes the journey from asking for help
                        to building trust straightforward.
                    </p>
                </div>

                <div class="neki-flow">

                    <div class="neki-flow-step">
                        <div class="flow-number">01</div>
                        <div class="flow-icon">🙋</div>
                        <h3>Ask</h3>
                        <p>Post what you need.</p>
                    </div>

                    <div class="flow-line"></div>

                    <div class="neki-flow-step">
                        <div class="flow-number">02</div>
                        <div class="flow-icon">🔎</div>
                        <h3>Discover</h3>
                        <p>Find help nearby.</p>
                    </div>

                    <div class="flow-line"></div>

                    <div class="neki-flow-step">
                        <div class="flow-number">03</div>
                        <div class="flow-icon">🤝</div>
                        <h3>Connect</h3>
                        <p>Review and approve.</p>
                    </div>

                    <div class="flow-line"></div>

                    <div class="neki-flow-step">
                        <div class="flow-number">04</div>
                        <div class="flow-icon">⭐</div>
                        <h3>Build Trust</h3>
                        <p>Complete and rate.</p>
                    </div>

                </div>

            </section>
            """
        )
    )

    # =========================================================
    # WHAT NEKI OFFERS
    # =========================================================

    st.html(
        dedent(
            """
            <section
                class="landing-section landing-section-soft"
                id="neki-community"
            >

                <div class="section-kicker">ONE COMMUNITY</div>

                <h2 class="landing-center-title">
                    More than just asking for help.
                </h2>

                <p class="landing-center-text">
                    Neki is designed around the complete neighbour-to-neighbour
                    experience.
                </p>

            </section>
            """
        )
    )

    feature_col1, feature_col2, feature_col3 = st.columns(
        3,
        gap="large",
    )

    features = [
        (
            "📍",
            "Nearby help",
            "Discover requests around your neighbourhood instead of searching blindly.",
        ),
        (
            "🛡️",
            "Trust & reputation",
            "See public profile information, ratings, completed helps and Trust Score before connecting.",
        ),
        (
            "🔔",
            "Stay informed",
            "Follow your requests, offers, approvals, completions and ratings without constantly refreshing.",
        ),
    ]

    for col, (icon, title, description) in zip(
        [feature_col1, feature_col2, feature_col3],
        features,
    ):
        with col:
            st.html(
                dedent(
                    f"""
                    <div class="landing-feature-card">

                        <div class="feature-icon">
                            {icon}
                        </div>

                        <h3>{title}</h3>

                        <p>{description}</p>

                    </div>
                    """
                )
            )

    # =========================================================
    # SAFETY / PRIVACY
    # =========================================================

    st.html(
        dedent(
            """
            <section class="landing-safety" id="neki-safety">

                <div class="safety-copy">

                    <div class="section-kicker">
                        TRUST COMES FIRST
                    </div>

                    <h2>
                        Know who you're<br>
                        connecting with.
                    </h2>

                    <p>
                        Before a help connection is accepted, Neki keeps
                        private contact details protected while allowing
                        neighbours to review the relevant public profile.
                    </p>

                </div>

                <div class="safety-points">

                    <div class="safety-point">
                        <span>✓</span>
                        <div>
                            <strong>Public profile before connection</strong>
                            <small>
                                Review relevant community information first.
                            </small>
                        </div>
                    </div>

                    <div class="safety-point">
                        <span>✓</span>
                        <div>
                            <strong>Private details after approval</strong>
                            <small>
                                Contact information is revealed only when
                                the connection is accepted.
                            </small>
                        </div>
                    </div>

                    <div class="safety-point">
                        <span>✓</span>
                        <div>
                            <strong>Ratings after completed help</strong>
                            <small>
                                Build reputation through real interactions.
                            </small>
                        </div>
                    </div>

                </div>

            </section>
            """
        )
    )

    # =========================================================
    # FINAL CTA
    # =========================================================

    st.html(
        dedent(
            """
            <section class="landing-final-cta">

                <div class="section-kicker">
                    YOUR COMMUNITY STARTS HERE
                </div>

                <h2>
                    Sometimes you need a hand.<br>
                    Sometimes you're the one who can give it.
                </h2>

                <p>
                    Join Neki and make neighbour-to-neighbour help easier.
                </p>

            </section>
            """
        )
    )

    cta1, cta2 = st.columns([1, 1], gap="medium")

    with cta1:
        if st.button(
            "Create your Neki account →",
            key="landing_register",
            type="primary",
            use_container_width=True,
        ):
            on_register()

    with cta2:
        if st.button(
            "Already a member? Login",
            key="landing_login",
            use_container_width=True,
        ):
            on_login()

    # =========================================================
    # FOOTER
    # =========================================================

    st.html(
        dedent(
            """
            <div class="landing-footer">
                <strong>Neki</strong>
                <span>Neighbours helping neighbours.</span>
            </div>
            """
        )
    )