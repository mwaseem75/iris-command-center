"""Builds an OperationExecutor wired to the demo handler."""

from app.execution.demo_handler import DemoSafeOperationHandler
from app.execution.executor import OperationExecutor


def build_default_executor() -> OperationExecutor:
    executor = OperationExecutor()
    executor.register_handler("demo.safe-operation", DemoSafeOperationHandler())
    return executor
