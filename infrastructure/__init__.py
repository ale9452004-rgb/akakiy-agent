"""
Infrastructure package for external system processes and hardware lifecycle management.
"""

from infrastructure.ollama_manager import OllamaManager, get_ollama_manager

__all__ = ["OllamaManager", "get_ollama_manager"]
