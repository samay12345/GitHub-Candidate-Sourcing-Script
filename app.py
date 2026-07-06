import streamlit as st
import pandas as pd

from candidate_sourcing import build_candidates

st.set_page_config(
    page_title="Debut — GitHub Candidate Sourcing",
    page_icon="🔍",
    layout="wide",
)

st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

  /* ── Base ── */
  html, body, [class*="css"], .stApp {
    font-family: 'Inter', 'Segoe UI', sans-serif;
    background-color: #0A0A0A !important;
    color: #F9FAFB !important;
  }
  #MainMenu, footer, header { visibility: hidden; }

  /* ── Scrollbar ── */
  ::-webkit-scrollbar { width: 6px; height: 6px; }
  ::-webkit-scrollbar-track { background: #111111; }
  ::-webkit-scrollbar-thumb { background: #22C55E55; border-radius: 4px; }

  /* ── Navbar ── */
  .debut-navbar {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 20px 0 20px 0;
    border-bottom: 1px solid #1F2937;
    margin-bottom: 40px;
  }
  .debut-navbar img { height: 32px; width: 32px; object-fit: contain; }
  .debut-brand {
    display: flex;
    flex-direction: column;
    gap: 1px;
  }
  .debut-brand .company {
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: #22C55E;
  }
  .debut-brand .product {
    font-size: 1.05rem;
    font-weight: 700;
    color: #F9FAFB;
    letter-spacing: -0.2px;
  }
  .navbar-divider {
    width: 1px;
    height: 32px;
    background: #1F2937;
    margin: 0 4px;
  }
  .navbar-tag {
    font-size: 0.68rem;
    font-weight: 500;
    color: #6B7280;
    letter-spacing: 0.05em;
    margin-top: 2px;
  }

  /* ── Hero ── */
  .hero {
    margin-bottom: 36px;
  }
  .hero h1 {
    font-size: 2rem;
    font-weight: 700;
    color: #F9FAFB;
    letter-spacing: -0.5px;
    margin: 0 0 8px 0;
    line-height: 1.2;
  }
  .hero h1 span { color: #22C55E; }
  .hero p {
    font-size: 0.9rem;
    color: #6B7280;
    margin: 0;
    font-weight: 400;
  }

  /* ── Section label ── */
  .section-label {
    font-size: 0.68rem;
    font-weight: 600;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: #4B5563;
    margin-bottom: 12px;
  }

  /* ── Inputs ── */
  .stTextInput > div > div > input,
  .stNumberInput > div > div > input {
    background: #111111 !important;
    border: 1px solid #1F2937 !important;
    border-radius: 8px !important;
    color: #F9FAFB !important;
    font-size: 0.9rem !important;
    padding: 10px 14px !important;
    transition: border-color 0.15s ease;
  }
  .stTextInput > div > div > input:focus,
  .stNumberInput > div > div > input:focus {
    border-color: #22C55E !important;
    box-shadow: 0 0 0 3px #22C55E18 !important;
  }
  .stTextInput label, .stNumberInput label {
    color: #9CA3AF !important;
    font-size: 0.8rem !important;
    font-weight: 500 !important;
  }
  .stTextInput .st-emotion-cache-ue6h4q { color: #4B5563 !important; font-size: 0.75rem !important; }

  /* ── Checkbox ── */
  .stCheckbox label { color: #9CA3AF !important; font-size: 0.85rem !important; }
  .stCheckbox input:checked + div { background: #22C55E !important; border-color: #22C55E !important; }

  /* ── Primary button ── */
  div.stButton > button[kind="primary"] {
    background: #22C55E !important;
    color: #0A0A0A !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 700 !important;
    font-size: 0.9rem !important;
    padding: 11px 32px !important;
    letter-spacing: 0.01em !important;
    transition: all 0.15s ease !important;
    box-shadow: 0 0 20px #22C55E30 !important;
  }
  div.stButton > button[kind="primary"]:hover {
    background: #16A34A !important;
    box-shadow: 0 0 28px #22C55E50 !important;
  }

  /* ── Spinner ── */
  .stSpinner > div { border-top-color: #22C55E !important; }

  /* ── Metric cards ── */
  .metric-row {
    display: flex;
    gap: 14px;
    margin-bottom: 28px;
  }
  .metric-card {
    flex: 1;
    background: #111111;
    border: 1px solid #1F2937;
    border-radius: 12px;
    padding: 20px 24px;
    display: flex;
    flex-direction: column;
    gap: 6px;
    transition: border-color 0.2s ease;
  }
  .metric-card:hover { border-color: #374151; }
  .metric-card .m-value {
    font-size: 2rem;
    font-weight: 700;
    color: #F9FAFB;
    line-height: 1;
    font-variant-numeric: tabular-nums;
  }
  .metric-card .m-label {
    font-size: 0.75rem;
    color: #4B5563;
    font-weight: 500;
    letter-spacing: 0.03em;
  }
  .metric-card.accent {
    border-color: #22C55E40;
    background: #0D1F14;
  }
  .metric-card.accent .m-value { color: #22C55E; }

  /* ── Results header ── */
  .results-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 16px;
  }
  .results-header .rh-title {
    font-size: 0.68rem;
    font-weight: 600;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: #4B5563;
  }
  .results-header .rh-badge {
    background: #22C55E15;
    color: #22C55E;
    font-size: 0.72rem;
    font-weight: 600;
    padding: 3px 10px;
    border-radius: 20px;
    border: 1px solid #22C55E30;
  }

  /* ── Dataframe ── */
  .stDataFrame {
    border: 1px solid #1F2937 !important;
    border-radius: 12px !important;
    overflow: hidden !important;
  }
  .stDataFrame thead th {
    background: #111111 !important;
    color: #6B7280 !important;
    font-size: 0.72rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.06em !important;
    text-transform: uppercase !important;
    border-bottom: 1px solid #1F2937 !important;
  }
  .stDataFrame tbody tr:hover { background: #111111 !important; }

  /* ── Download button ── */
  div.stDownloadButton > button {
    background: transparent !important;
    color: #22C55E !important;
    border: 1px solid #22C55E40 !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    font-size: 0.85rem !important;
    transition: all 0.15s ease !important;
  }
  div.stDownloadButton > button:hover {
    background: #22C55E10 !important;
    border-color: #22C55E !important;
  }

  /* ── Divider ── */
  .divider { border: none; border-top: 1px solid #1F2937; margin: 28px 0; }

  /* ── Alert overrides ── */
  .stAlert { background: #111111 !important; border-color: #1F2937 !important; }
</style>

<div class="debut-navbar">
  <img src="https://trydebut.com/assets/debut-mark-DlIhz45H.png" alt="Debut" />
  <div class="navbar-divider"></div>
  <div class="debut-brand">
    <span class="company">Debut</span>
    <span class="product">GitHub Candidate Sourcing</span>
  </div>
</div>

<div class="hero">
  <h1>Find the right <span>engineers.</span></h1>
  <p>Search GitHub's public data to surface qualified candidates by role and tech stack.</p>
</div>
""", unsafe_allow_html=True)


# ── Search ──
st.markdown('<p class="section-label">Search Parameters</p>', unsafe_allow_html=True)

col1, col2, col3, col4 = st.columns([3, 3, 1.5, 1.5])
with col1:
    role = st.text_input("Role", "software engineer", placeholder="e.g. backend engineer")
with col2:
    tech_stack_input = st.text_input(
        "Tech Stack",
        "python,java",
        placeholder="e.g. python,react,postgres",
        help="Separate multiple technologies with commas — e.g. python,pytorch,sql",
    )
with col3:
    limit = st.number_input("Candidates", min_value=1, max_value=500, value=50, step=10)
with col4:
    st.markdown("<div style='height:29px'></div>", unsafe_allow_html=True)
    us_only = st.checkbox("US / Canada only", value=True)

st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

# Comma hint
st.markdown(
    "<p style='font-size:0.75rem; color:#4B5563; margin-top:-8px; margin-bottom:16px;'>"
    "Tip: separate tech stack items with commas — e.g. <code style='background:#111;padding:1px 5px;border-radius:4px;color:#22C55E;'>python,pytorch,sql</code>"
    "</p>",
    unsafe_allow_html=True,
)

run = st.button("Find Candidates", type="primary")
st.markdown('<hr class="divider">', unsafe_allow_html=True)


# ── Results ──
if run:
    tech_stack = [t.strip() for t in tech_stack_input.split(",") if t.strip()]

    if not role.strip():
        st.error("Please enter a role.")
    elif not tech_stack:
        st.error("Please enter at least one tech stack item.")
    else:
        with st.spinner(f"Searching GitHub for {limit} {role} candidates…"):
            candidates = build_candidates(role, tech_stack, limit=limit, us_only=us_only)

        if not candidates:
            st.warning("No candidates found. Try a broader role or tech stack.")
        else:
            strong     = sum(1 for c in candidates if c["match_label"] == "Strong match")
            good       = sum(1 for c in candidates if c["match_label"] == "Good match")
            with_email = sum(1 for c in candidates if c["public_email"])

            st.markdown(f"""
            <div class="metric-row">
              <div class="metric-card accent">
                <span class="m-value">{len(candidates)}</span>
                <span class="m-label">Candidates Found</span>
              </div>
              <div class="metric-card">
                <span class="m-value">{strong}</span>
                <span class="m-label">Strong Matches</span>
              </div>
              <div class="metric-card">
                <span class="m-value">{good}</span>
                <span class="m-label">Good Matches</span>
              </div>
              <div class="metric-card">
                <span class="m-value">{with_email}</span>
                <span class="m-label">With Public Email</span>
              </div>
            </div>
            """, unsafe_allow_html=True)

            st.markdown(f"""
            <div class="results-header">
              <span class="rh-title">Results</span>
              <span class="rh-badge">{len(candidates)} candidates · ranked by score</span>
            </div>
            """, unsafe_allow_html=True)

            df = pd.DataFrame([
                {
                    "Username":  c["username"],
                    "Profile":   c["profile_url"],
                    "Email":     c["public_email"] or "—",
                    "Top Repo":  c["most_relevant_repo"],
                    "Summary":   c["relevance_summary"],
                    "Location":  c["location"] or "—",
                    "Match":     c["match_label"],
                    "Score":     c["score"],
                }
                for c in candidates
            ])

            st.dataframe(
                df,
                use_container_width=True,
                column_config={
                    "Profile":  st.column_config.LinkColumn("Profile"),
                    "Top Repo": st.column_config.LinkColumn("Top Repo"),
                },
                hide_index=True,
                height=480,
            )

            st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
            st.download_button(
                label="⬇  Download CSV",
                data=df.to_csv(index=False),
                file_name="candidates.csv",
                mime="text/csv",
            )
