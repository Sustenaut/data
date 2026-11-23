"""data.sustenaut.eu, as Streamlit runs it:

    soldera app --store ./store         # on a laptop, from a copy of the store
    soldera app --store gs://BUCKET     # as the Cloud Run service does

Two pages: the landing page at / and the power-auctions app at
/power-auctions. Each is a page script beside this one; what they draw is in
soldera.app.page."""

import streamlit as st

from soldera.app.page import POWER_AUCTIONS

st.navigation(
    [st.Page("home.py", title="Sustenaut data", default=True),
     st.Page(POWER_AUCTIONS, title="Power auctions", url_path="power-auctions")],
    position="hidden",
).run()
