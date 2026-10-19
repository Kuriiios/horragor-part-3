import os

from langfuse.langchain import CallbackHandler


def create_handler() -> CallbackHandler:
    """Create a manual Langfuse handler from externally provided credentials."""
    if not os.getenv("LANGFUSE_PUBLIC_KEY") or not os.getenv("LANGFUSE_SECRET_KEY"):
        raise RuntimeError("Set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY first.")
    return CallbackHandler()