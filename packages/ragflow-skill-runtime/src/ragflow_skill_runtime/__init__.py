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
from .profiles import ChunkProfile, ProfileError, load_profile
from .kb_build import (
    BuildDocument,
    BuildError,
    discover_markdown_documents,
    extract_document_states,
    make_kb_manifest_payload,
    normalize_document_state,
    wait_for_document_states,
)
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
    "ChunkProfile",
    "ProfileError",
    "RAGFlowClient",
    "RagflowConfig",
    "BuildDocument",
    "BuildError",
    "NormalizedChunk",
    "QueryResult",
    "RetrievalError",
    "discover_markdown_documents",
    "extract_document_states",
    "make_kb_manifest_payload",
    "load_api_key",
    "load_config",
    "load_doc_manifest",
    "load_kb_manifest",
    "load_profile",
    "normalize_retrieval_response",
    "normalize_document_state",
    "resolve_dataset_ids",
    "wait_for_document_states",
]

__version__ = "0.1.0"
