"""Portable runtime primitives for public RAGFlow skills."""

from .auth import AuthError, load_api_key
from .config import ConfigError, RagflowConfig, load_config
from .manifests import (
    DocManifest,
    DocumentEntry,
    KbDataset,
    KbDocumentEntry,
    KbManifest,
    ManifestError,
    load_doc_manifest,
    load_kb_manifest,
)
from .ragflow_client import RAGFlowClient
from .retrieval import (
    NormalizedChunk,
    QueryResult,
    RetrievalError,
    normalize_retrieval_response,
    resolve_dataset_ids,
)

__all__ = [
    "AuthError",
    "ConfigError",
    "DocManifest",
    "DocumentEntry",
    "KbDataset",
    "KbDocumentEntry",
    "KbManifest",
    "ManifestError",
    "RAGFlowClient",
    "RagflowConfig",
    "NormalizedChunk",
    "QueryResult",
    "RetrievalError",
    "load_api_key",
    "load_config",
    "load_doc_manifest",
    "load_kb_manifest",
    "normalize_retrieval_response",
    "resolve_dataset_ids",
]

__version__ = "0.1.0"
