"""data.sustenaut.eu, as Streamlit runs it:

    soldera app --store ./store         # on a laptop, from a copy of the store
    soldera app --store gs://BUCKET     # as the Cloud Run service does

The landing page at / and the power-auctions app at /power-auctions; both are
in soldera.app.page."""

from soldera.app.page import site

site()
