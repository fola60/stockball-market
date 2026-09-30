"""Process and CLI entry points for the worker service.

- `cli`: the `stockball-worker` command table.
- `commands/`: one module per command group (runtime processes, ingestion, market setup).
- `processes`: wiring for the scheduler and the queue-consuming job worker.
- `factories`: builders that connect services to their repositories and clients.
"""
