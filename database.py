from azure.cosmos import CosmosClient, exceptions, PartitionKey
from azure.cosmos.container import ContainerProxy
from typing import Optional, List, Dict, Any
from config import settings
import logging

db_logger = logging.getLogger(__name__)


class CosmosDBClient:
    def __init__(self):
        self.client = CosmosClient(settings.cosmos_endpoint, settings.cosmos_key)
        self.database = None
        self.users_container = None
        self.media_container = None

    def initialize(self):
        """Setup database and container resources"""
        try:
            # Setup database instance
            self.database = self.client.create_database_if_not_exists(
                id=settings.cosmos_database_name
            )
            db_logger.info(f"Database '{settings.cosmos_database_name}' initialized")

            # Setup users storage container
            self.users_container = self.database.create_container_if_not_exists(
                partition_key=PartitionKey(path="/id"),
                id="users",
                offer_throughput=400
            )
            db_logger.info("Users container initialized")

            # Setup media storage container
            self.media_container = self.database.create_container_if_not_exists(
                partition_key=PartitionKey(path="/userId"),
                id="media",
                offer_throughput=400
            )
            db_logger.info("Media container initialized")

        except exceptions.CosmosHttpResponseError as cosmos_error:
            db_logger.error(f"Cosmos DB initialization failed: {cosmos_error}")
            raise

    # Account management operations
    def create_user(self, account_data: dict) -> dict:
        """Insert new user account"""
        try:
            return self.users_container.create_item(body=account_data)
        except exceptions.CosmosResourceExistsError:
            raise ValueError("User already exists")
        except exceptions.CosmosHttpResponseError as cosmos_err:
            db_logger.error(f"User creation failed: {cosmos_err}")
            raise

    def get_user_by_email(self, email_address: str) -> Optional[dict]:
        """Fetch user by email address"""
        try:
            sql_query = "SELECT * FROM users u WHERE u.email = @email"
            query_params = [{"name": "@email", "value": email_address}]
            results = list(
                self.users_container.query_items(
                    enable_cross_partition_query=True, query=sql_query, parameters=query_params
                )
            )
            return results[0] if results else None
        except exceptions.CosmosHttpResponseError as cosmos_err:
            db_logger.error(f"Email lookup failed: {cosmos_err}")
            raise

    def get_user_by_id(self, account_id: str) -> Optional[dict]:
        """Fetch user by unique identifier"""
        try:
            return self.users_container.read_item(partition_key=account_id, item=account_id)
        except exceptions.CosmosResourceNotFoundError:
            return None
        except exceptions.CosmosHttpResponseError as cosmos_err:
            db_logger.error(f"User ID lookup failed: {cosmos_err}")
            raise

    # Media file operations
    def create_media(self, media_record: dict) -> dict:
        """Insert new media record"""
        try:
            return self.media_container.create_item(body=media_record)
        except exceptions.CosmosHttpResponseError as cosmos_err:
            db_logger.error(f"Media creation failed: {cosmos_err}")
            raise

    def get_media_by_id(self, record_id: str, owner_id: str) -> Optional[dict]:
        """Retrieve media by unique identifier"""
        try:
            return self.media_container.read_item(partition_key=owner_id, item=record_id)
        except exceptions.CosmosResourceNotFoundError:
            return None
        except exceptions.CosmosHttpResponseError as cosmos_err:
            db_logger.error(f"Media ID lookup failed: {cosmos_err}")
            raise

    def get_user_media(
        self,
        user_id: str,
        page: int = 1,
        page_size: int = 20,
        media_type: Optional[str] = None
    ) -> tuple[List[dict], int]:
        """Retrieve paginated user media collection"""
        try:
            # Construct SQL query
            base_query = "SELECT * FROM media m WHERE m.userId = @userId"
            params = [{"name": "@userId", "value": user_id}]

            if media_type:
                base_query += " AND m.mediaType = @mediaType"
                params.append({"name": "@mediaType", "value": media_type})

            base_query += " ORDER BY m.uploadedAt DESC"

            # Calculate total records
            count_sql = base_query.replace("SELECT *", "SELECT VALUE COUNT(1)")
            count_results = list(
                self.media_container.query_items(
                    parameters=params, query=count_sql
                )
            )
            total_records = count_results[0] if count_results else 0

            # Implement pagination
            skip_count = (page - 1) * page_size
            paginated_query = f"{base_query} OFFSET {skip_count} LIMIT {page_size}"

            records = list(
                self.media_container.query_items(parameters=params, query=paginated_query)
            )

            return records, total_records

        except exceptions.CosmosHttpResponseError as cosmos_err:
            db_logger.error(f"User media retrieval failed: {cosmos_err}")
            raise

    def update_media(self, record_id: str, owner_id: str, modifications: dict) -> dict:
        """Modify media metadata"""
        try:
            # Retrieve current record
            current_record = self.get_media_by_id(record_id, owner_id)
            if not current_record:
                raise ValueError("Media not found")

            # Apply modifications
            current_record.update(modifications)

            # Persist changes
            return self.media_container.replace_item(
                body=current_record, item=record_id
            )
        except exceptions.CosmosHttpResponseError as cosmos_err:
            db_logger.error(f"Media update failed: {cosmos_err}")
            raise

    def delete_media(self, record_id: str, owner_id: str) -> bool:
        """Remove media record"""
        try:
            self.media_container.delete_item(partition_key=owner_id, item=record_id)
            return True
        except exceptions.CosmosResourceNotFoundError:
            return False
        except exceptions.CosmosHttpResponseError as cosmos_err:
            db_logger.error(f"Media deletion failed: {cosmos_err}")
            raise

    def search_media(
        self, user_id: str, query: str, page: int = 1, page_size: int = 20
    ) -> tuple[List[dict], int]:
        """Find media by text search"""
        try:
            # Build search SQL
            search_sql = """
                SELECT * FROM media m
                WHERE m.userId = @userId
                AND (
                    CONTAINS(LOWER(m.originalFileName), LOWER(@searchTerm))
                    OR CONTAINS(LOWER(m.description), LOWER(@searchTerm))
                    OR ARRAY_CONTAINS(m.tags, @searchTerm, true)
                )
                ORDER BY m.uploadedAt DESC
            """
            params = [
                {"name": "@userId", "value": user_id},
                {"name": "@searchTerm", "value": query}
            ]

            # Calculate total matches
            count_sql = search_sql.replace("SELECT *", "SELECT VALUE COUNT(1)")
            count_data = list(
                self.media_container.query_items(
                    parameters=params, query=count_sql
                )
            )
            total_matches = count_data[0] if count_data else 0

            # Add pagination
            skip_count = (page - 1) * page_size
            search_sql += f" OFFSET {skip_count} LIMIT {page_size}"

            matches = list(
                self.media_container.query_items(
                    parameters=params, query=search_sql
                )
            )

            return matches, total_matches

        except exceptions.CosmosHttpResponseError as cosmos_err:
            db_logger.error(f"Media search failed: {cosmos_err}")
            raise


# Singleton instance
cosmos_db = CosmosDBClient()
