"""soldera: ingest pipelines for data.sustenaut.eu.

Each pipeline is a list of stages. A stage is the generic runner
(soldera.core.runner) with one versioned parser plugged in. Every stage reads
the stored output of the stage before it and writes its own, so a pipeline can
be run again from any stage."""

__version__ = "0.1.0"
