"""The power-auctions app, as Streamlit runs it:

    soldera app --store ./store         # on a laptop, from a copy of the store
    soldera app --store gs://BUCKET     # as the Cloud Run service does

The page itself is soldera.app.page."""

from soldera.app.page import main

main()
