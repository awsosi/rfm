"""
Elasticsearch service for indexing and searching operations and files.

This service provides:
- Index creation and management
- Document indexing for operations and files
- Search functionality with filters and pagination
- Automatic index synchronization
"""

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

from elasticsearch import AsyncElasticsearch
from elasticsearch.exceptions import NotFoundError, ConnectionError as ESConnectionError
from loguru import logger

from ..config import get_settings


class ElasticsearchService:
    """Service for managing Elasticsearch indexing and searching."""

    def __init__(self):
        """Initialize Elasticsearch service."""
        self.settings = get_settings()
        self._client: Optional[AsyncElasticsearch] = None
        self._initialized = False

    async def initialize(self):
        """Initialize Elasticsearch client and create indices if needed."""
        if not self.settings.elasticsearch_enabled:
            logger.info("Elasticsearch is disabled in configuration")
            return

        try:
            # Build connection parameters
            es_params: Dict[str, Any] = {
                "hosts": [self.settings.elasticsearch_url],
                "max_retries": self.settings.elasticsearch_max_retries,
                "retry_on_timeout": True,
                "request_timeout": self.settings.elasticsearch_timeout,
            }

            # Add authentication if configured
            if self.settings.elasticsearch_username and self.settings.elasticsearch_password:
                es_params["basic_auth"] = (
                    self.settings.elasticsearch_username,
                    self.settings.elasticsearch_password,
                )

            self._client = AsyncElasticsearch(**es_params)

            # Test connection
            await self._client.info()
            logger.info("Elasticsearch connection established")

            # Create indices
            await self._create_operations_index()
            await self._create_files_index()

            self._initialized = True
            logger.info("Elasticsearch service initialized successfully")

        except ESConnectionError as e:
            logger.error(f"Failed to connect to Elasticsearch: {e}")
            self._client = None
        except Exception as e:
            logger.error(f"Unexpected error initializing Elasticsearch: {e}")
            self._client = None

    async def close(self):
        """Close Elasticsearch client connection."""
        if self._client:
            await self._client.close()
            self._client = None
            self._initialized = False
            logger.info("Elasticsearch connection closed")

    @property
    def is_enabled(self) -> bool:
        """Check if Elasticsearch is enabled and initialized."""
        return self.settings.elasticsearch_enabled and self._initialized and self._client is not None

    async def _create_operations_index(self):
        """Create operations index with proper mappings."""
        index_name = self.settings.elasticsearch_index_operations

        # Check if index exists
        if await self._client.indices.exists(index=index_name):
            logger.info(f"Operations index '{index_name}' already exists")
            return

        # Define mappings
        mappings = {
            "properties": {
                "operation_id": {"type": "integer"},
                "user_id": {"type": "integer"},
                "user_name": {
                    "type": "text",
                    "fields": {"keyword": {"type": "keyword"}},
                },
                "operation_type": {"type": "keyword"},
                "status": {"type": "keyword"},
                "source_path": {
                    "type": "text",
                    "fields": {"keyword": {"type": "keyword"}},
                },
                "dest_path": {
                    "type": "text",
                    "fields": {"keyword": {"type": "keyword"}},
                },
                "original_path": {
                    "type": "text",
                    "fields": {"keyword": {"type": "keyword"}},
                },
                "archive_path": {
                    "type": "text",
                    "fields": {"keyword": {"type": "keyword"}},
                },
                "error_msg": {"type": "text"},
                "file_count": {"type": "integer"},
                "total_size_bytes": {"type": "long"},
                "created_at": {"type": "date"},
                "started_at": {"type": "date"},
                "completed_at": {"type": "date"},
                "indexed_at": {"type": "date"},
            }
        }

        # Create index
        await self._client.indices.create(index=index_name, mappings=mappings)
        logger.info(f"Created operations index '{index_name}'")

    async def _create_files_index(self):
        """Create files index with proper mappings."""
        index_name = self.settings.elasticsearch_index_files

        # Check if index exists
        if await self._client.indices.exists(index=index_name):
            logger.info(f"Files index '{index_name}' already exists")
            return

        # Define mappings
        mappings = {
            "properties": {
                "path": {
                    "type": "text",
                    "fields": {"keyword": {"type": "keyword"}},
                },
                "name": {
                    "type": "text",
                    "fields": {"keyword": {"type": "keyword"}},
                },
                "parent_path": {
                    "type": "text",
                    "fields": {"keyword": {"type": "keyword"}},
                },
                "is_directory": {"type": "boolean"},
                "size": {"type": "long"},
                "modified_at": {"type": "date"},
                "worker_id": {"type": "integer"},
                "indexed_at": {"type": "date"},
            }
        }

        # Create index
        await self._client.indices.create(index=index_name, mappings=mappings)
        logger.info(f"Created files index '{index_name}'")

    async def index_operation(self, operation_data: Dict[str, Any]) -> bool:
        """
        Index an operation in Elasticsearch.

        Args:
            operation_data: Operation data to index (must include 'operation_id')

        Returns:
            True if indexed successfully, False otherwise
        """
        if not self.is_enabled:
            return False

        try:
            operation_id = operation_data.get("operation_id")
            if not operation_id:
                logger.error("Cannot index operation without operation_id")
                return False

            # Add indexing timestamp
            operation_data["indexed_at"] = datetime.utcnow().isoformat()

            # Index document
            await self._client.index(
                index=self.settings.elasticsearch_index_operations,
                id=str(operation_id),
                document=operation_data,
            )

            logger.debug(f"Indexed operation {operation_id} in Elasticsearch")
            return True

        except Exception as e:
            logger.error(f"Failed to index operation: {e}")
            return False

    async def update_operation(self, operation_id: int, updates: Dict[str, Any]) -> bool:
        """
        Update an operation document in Elasticsearch.

        Args:
            operation_id: Operation ID to update
            updates: Fields to update

        Returns:
            True if updated successfully, False otherwise
        """
        if not self.is_enabled:
            return False

        try:
            # Add indexing timestamp
            updates["indexed_at"] = datetime.utcnow().isoformat()

            # Update document
            await self._client.update(
                index=self.settings.elasticsearch_index_operations,
                id=str(operation_id),
                doc=updates,
            )

            logger.debug(f"Updated operation {operation_id} in Elasticsearch")
            return True

        except NotFoundError:
            logger.warning(f"Operation {operation_id} not found in Elasticsearch, will re-index")
            return False
        except Exception as e:
            logger.error(f"Failed to update operation: {e}")
            return False

    async def search_operations(
        self,
        query: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
        offset: int = 0,
        limit: int = 50,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> Dict[str, Any]:
        """
        Search operations in Elasticsearch.

        Args:
            query: Free-text search query (searches paths, user_name, error_msg)
            filters: Dict of filters (e.g., {"status": "COMPLETED", "operation_type": "PUSH"})
            offset: Result offset for pagination
            limit: Maximum results to return
            sort_by: Field to sort by
            sort_order: Sort order ("asc" or "desc")

        Returns:
            Dict with 'total', 'hits', 'offset', 'limit'
        """
        if not self.is_enabled:
            return {"total": 0, "hits": [], "offset": offset, "limit": limit}

        try:
            # Build query
            must_clauses = []

            # Add free-text search
            if query:
                must_clauses.append({
                    "multi_match": {
                        "query": query,
                        "fields": [
                            "source_path^3",
                            "dest_path^3",
                            "original_path^2",
                            "archive_path^2",
                            "user_name^2",
                            "error_msg",
                        ],
                        "type": "best_fields",
                        "operator": "and",
                        "fuzziness": "AUTO",
                    }
                })

            # Add filters
            if filters:
                for field, value in filters.items():
                    if value is not None:
                        must_clauses.append({"term": {field: value}})

            # Build complete query
            if must_clauses:
                es_query = {"bool": {"must": must_clauses}}
            else:
                es_query = {"match_all": {}}

            # Execute search
            response = await self._client.search(
                index=self.settings.elasticsearch_index_operations,
                query=es_query,
                from_=offset,
                size=limit,
                sort=[{sort_by: {"order": sort_order}}],
            )

            # Format results
            hits = []
            for hit in response["hits"]["hits"]:
                doc = hit["_source"]
                doc["_score"] = hit.get("_score")
                hits.append(doc)

            return {
                "total": response["hits"]["total"]["value"],
                "hits": hits,
                "offset": offset,
                "limit": limit,
            }

        except Exception as e:
            logger.error(f"Failed to search operations: {e}")
            return {"total": 0, "hits": [], "offset": offset, "limit": limit}

    async def index_file(self, file_data: Dict[str, Any]) -> bool:
        """
        Index a file in Elasticsearch.

        Args:
            file_data: File data to index (must include 'path' and 'worker_id')

        Returns:
            True if indexed successfully, False otherwise
        """
        if not self.is_enabled:
            return False

        try:
            path = file_data.get("path")
            worker_id = file_data.get("worker_id")

            if not path or worker_id is None:
                logger.error("Cannot index file without path and worker_id")
                return False

            # Add indexing timestamp
            file_data["indexed_at"] = datetime.utcnow().isoformat()

            # Create unique document ID from path and worker
            doc_id = f"{worker_id}:{path}"

            # Index document
            await self._client.index(
                index=self.settings.elasticsearch_index_files,
                id=doc_id,
                document=file_data,
            )

            logger.debug(f"Indexed file {path} (worker {worker_id}) in Elasticsearch")
            return True

        except Exception as e:
            logger.error(f"Failed to index file: {e}")
            return False

    async def bulk_index_files(self, files: List[Dict[str, Any]]) -> int:
        """
        Bulk index multiple files.

        Args:
            files: List of file data dicts

        Returns:
            Number of successfully indexed files
        """
        if not self.is_enabled or not files:
            return 0

        try:
            # Prepare bulk operations
            operations = []
            for file_data in files:
                path = file_data.get("path")
                worker_id = file_data.get("worker_id")

                if not path or worker_id is None:
                    continue

                # Add indexing timestamp
                file_data["indexed_at"] = datetime.utcnow().isoformat()

                # Create unique document ID
                doc_id = f"{worker_id}:{path}"

                # Add index operation
                operations.append({"index": {"_index": self.settings.elasticsearch_index_files, "_id": doc_id}})
                operations.append(file_data)

            if not operations:
                return 0

            # Execute bulk operation
            response = await self._client.bulk(operations=operations)

            # Count successful operations
            success_count = sum(1 for item in response["items"] if item["index"]["status"] in (200, 201))

            logger.info(f"Bulk indexed {success_count}/{len(files)} files")
            return success_count

        except Exception as e:
            logger.error(f"Failed to bulk index files: {e}")
            return 0

    async def search_files(
        self,
        query: str,
        worker_id: Optional[int] = None,
        parent_path: Optional[str] = None,
        is_directory: Optional[bool] = None,
        offset: int = 0,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """
        Search files in Elasticsearch.

        Args:
            query: Free-text search query (searches path and name)
            worker_id: Filter by worker ID
            parent_path: Filter by parent directory path
            is_directory: Filter by directory flag
            offset: Result offset for pagination
            limit: Maximum results to return

        Returns:
            Dict with 'total', 'hits', 'offset', 'limit'
        """
        if not self.is_enabled:
            return {"total": 0, "hits": [], "offset": offset, "limit": limit}

        try:
            # Build query
            must_clauses = []

            # Add free-text search
            if query:
                must_clauses.append({
                    "multi_match": {
                        "query": query,
                        "fields": ["path^2", "name^3"],
                        "type": "best_fields",
                        "fuzziness": "AUTO",
                    }
                })

            # Add filters
            if worker_id is not None:
                must_clauses.append({"term": {"worker_id": worker_id}})

            if parent_path is not None:
                must_clauses.append({"term": {"parent_path.keyword": parent_path}})

            if is_directory is not None:
                must_clauses.append({"term": {"is_directory": is_directory}})

            # Build complete query
            if must_clauses:
                es_query = {"bool": {"must": must_clauses}}
            else:
                es_query = {"match_all": {}}

            # Execute search
            response = await self._client.search(
                index=self.settings.elasticsearch_index_files,
                query=es_query,
                from_=offset,
                size=limit,
                sort=[{"path.keyword": {"order": "asc"}}],
            )

            # Format results
            hits = []
            for hit in response["hits"]["hits"]:
                doc = hit["_source"]
                doc["_score"] = hit.get("_score")
                hits.append(doc)

            return {
                "total": response["hits"]["total"]["value"],
                "hits": hits,
                "offset": offset,
                "limit": limit,
            }

        except Exception as e:
            logger.error(f"Failed to search files: {e}")
            return {"total": 0, "hits": [], "offset": offset, "limit": limit}

    async def delete_file(self, path: str, worker_id: int) -> bool:
        """
        Delete a file from the index.

        Args:
            path: File path
            worker_id: Worker ID

        Returns:
            True if deleted successfully, False otherwise
        """
        if not self.is_enabled:
            return False

        try:
            doc_id = f"{worker_id}:{path}"
            await self._client.delete(
                index=self.settings.elasticsearch_index_files,
                id=doc_id,
            )
            logger.debug(f"Deleted file {path} from Elasticsearch")
            return True

        except NotFoundError:
            logger.debug(f"File {path} not found in Elasticsearch (already deleted)")
            return True
        except Exception as e:
            logger.error(f"Failed to delete file from index: {e}")
            return False


# Global service instance
_elasticsearch_service: Optional[ElasticsearchService] = None


async def get_elasticsearch_service() -> ElasticsearchService:
    """
    Get or create the global Elasticsearch service instance.

    Returns:
        Initialized ElasticsearchService instance
    """
    global _elasticsearch_service

    if _elasticsearch_service is None:
        _elasticsearch_service = ElasticsearchService()
        await _elasticsearch_service.initialize()

    return _elasticsearch_service


async def close_elasticsearch_service():
    """Close the global Elasticsearch service."""
    global _elasticsearch_service

    if _elasticsearch_service:
        await _elasticsearch_service.close()
        _elasticsearch_service = None
