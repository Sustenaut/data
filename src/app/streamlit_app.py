"""data.sustenaut.eu, as Streamlit runs it:

    data app --store ./store         # on a laptop, from a copy of the store
    data app --store gs://BUCKET     # as the Cloud Run service does

The landing page at / and the power-auctions app at /power-auctions; both are
in app.page."""

from app.page import site

site()
