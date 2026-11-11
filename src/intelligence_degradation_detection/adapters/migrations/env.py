"""Run Alembic using the connection owned by application startup."""

from alembic import context

from intelligence_degradation_detection.adapters.storage import metadata

context.configure(
    connection=context.config.attributes["connection"], target_metadata=metadata
)
with context.begin_transaction():
    context.run_migrations()
