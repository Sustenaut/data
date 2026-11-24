"""ingest: the ingest pipelines of data.sustenaut.eu.

Each pipeline is a list of stages. A stage is the generic runner
(ingest.core.runner) with one versioned parser plugged in. Every stage reads
the stored output of the stage before it and writes its own, so a pipeline can
be run again from any stage."""

__version__ = "0.1.0"


def setting(name: str, default: str | None = None) -> str | None:
    """The environment's DATA_<name>, or the default when it is unset or empty."""
    import os  # noqa: PLC0415

    # DEBUG(#27): the deployed job and service set SOLDERA_<name> until the cloud migration.
    return os.environ.get(f"DATA_{name}") or os.environ.get(f"SOLDERA_{name}") or default
