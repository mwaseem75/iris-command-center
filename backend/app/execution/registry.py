"""Wires the (currently single) known handler to its operation name and
builds a ready-to-use OperationExecutor. Not used by any route yet — no
route in this project uses the execution framework at all. This exists so
the framework can be demonstrated/exercised as a whole, and so a future
route has an obvious place to get a configured executor from.
"""

from app.execution.demo_handler import DemoSafeOperationHandler
from app.execution.executor import OperationExecutor


def build_default_executor() -> OperationExecutor:
    executor = OperationExecutor()
    executor.register_handler("demo.safe-operation", DemoSafeOperationHandler())
    return executor
