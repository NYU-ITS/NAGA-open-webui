import json
import logging
import time
from typing import Optional
import uuid

from open_webui.internal.db import Base, get_db
from open_webui.env import SRC_LOG_LEVELS

from open_webui.models.files import FileMetadataResponse
from open_webui.models.users import Users, UserResponse


from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Column, String, Text, JSON

from open_webui.utils.access_control import has_access

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

####################
# Knowledge DB Schema
####################


class Knowledge(Base):
    __tablename__ = "knowledge"

    id = Column(Text, unique=True, primary_key=True)
    user_id = Column(Text)

    name = Column(Text)
    description = Column(Text)

    data = Column(JSON, nullable=True)
    meta = Column(JSON, nullable=True)

    access_control = Column(JSON, nullable=True)  # Controls data access levels.
    # Defines access control rules for this entry.
    # - `None`: Public access, available to all users with the "user" role.
    # - `{}`: Private access, restricted exclusively to the owner.
    # - Custom permissions: Specific access control for reading and writing;
    #   Can specify group or user-level restrictions:
    #   {
    #      "read": {
    #          "group_ids": ["group_id1", "group_id2"],
    #          "user_ids":  ["user_id1", "user_id2"]
    #      },
    #      "write": {
    #          "group_ids": ["group_id1", "group_id2"],
    #          "user_ids":  ["user_id1", "user_id2"]
    #      }
    #   }

    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)


class KnowledgeModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str

    name: str
    description: str

    data: Optional[dict] = None
    meta: Optional[dict] = None

    # access_control: Optional[dict] = None
    access_control: Optional[dict] = {}

    created_at: int  # timestamp in epoch
    updated_at: int  # timestamp in epoch


####################
# Forms
####################


class KnowledgeUserModel(KnowledgeModel):
    user: Optional[UserResponse] = None


class KnowledgeResponse(KnowledgeModel):
    files: Optional[list[FileMetadataResponse]] = None


class KnowledgeUserResponse(KnowledgeUserModel):
    files: Optional[list[FileMetadataResponse]] = None


class KnowledgeForm(BaseModel):
    name: str
    description: str
    data: Optional[dict] = None
    # access_control: Optional[dict] = None
    access_control: Optional[dict] = {}
    assign_to_email: Optional[str] = None


class KnowledgeTable:
    def insert_new_knowledge(
        self, user_id: str, form_data: KnowledgeForm
    ) -> Optional[KnowledgeModel]:
        with get_db() as db:
            # ``file_ids`` is server-owned. Attachments must flow through the
            # add-file routes so membership and vector projections stay aligned.
            form_data_dict = form_data.model_dump(exclude={"assign_to_email"})
            data = form_data_dict.get("data")
            data = dict(data) if isinstance(data, dict) else {}
            data["file_ids"] = []
            form_data_dict["data"] = data
            
            knowledge = KnowledgeModel(
                **{
                    **form_data_dict,
                    "id": str(uuid.uuid4()),
                    "user_id": user_id,
                    "created_at": int(time.time()),
                    "updated_at": int(time.time()),
                }
            )

            try:
                result = Knowledge(**knowledge.model_dump())
                db.add(result)
                db.commit()
                db.refresh(result)
                if result:
                    return KnowledgeModel.model_validate(result)
                else:
                    return None
            except Exception:
                return None

    def get_knowledge_bases(self) -> list[KnowledgeUserModel]:
        with get_db() as db:
            knowledge_bases = []
            for knowledge in (
                db.query(Knowledge).order_by(Knowledge.updated_at.desc()).all()
            ):
                user = Users.get_user_by_id(knowledge.user_id)
                knowledge_bases.append(
                    KnowledgeUserModel.model_validate(
                        {
                            **KnowledgeModel.model_validate(knowledge).model_dump(),
                            "user": user.model_dump() if user else None,
                        }
                    )
                )
            return knowledge_bases

    # def get_knowledge_bases_by_user_id(
    #     self, user_id: str, permission: str = "write"
    # ) -> list[KnowledgeUserModel]:
    #     knowledge_bases = self.get_knowledge_bases()
    #     return [
    #         knowledge_base
    #         for knowledge_base in knowledge_bases
    #         if knowledge_base.user_id == user_id
    #         or has_access(user_id, permission, knowledge_base.access_control)
    #     ]

    def _item_assigned_to_user_groups(self, user_id: str, item, permission: str = "write") -> bool:
        """Check if item is assigned to any group the user is member of OR owns"""
        from open_webui.utils.workspace_access import item_assigned_to_user_groups
        return item_assigned_to_user_groups(user_id, item, permission)

    def get_knowledge_bases_by_user_id(
        self, user_id: str, permission: str = "write"
    ) -> list[KnowledgeUserModel]:
        with get_db() as db:
            # Optimize: First get knowledge bases owned by user (SQL filter)
            # Then get all others for access control checks
            owned_knowledge = (
                db.query(Knowledge)
                .filter(Knowledge.user_id == user_id)
                .order_by(Knowledge.updated_at.desc())
                .all()
            )
            
            # Get all other knowledge bases for access control checks
            other_knowledge = (
                db.query(Knowledge)
                .filter(Knowledge.user_id != user_id)
                .order_by(Knowledge.updated_at.desc())
                .all()
            )
            
            # Combine and dedupe (in case of any overlap)
            all_knowledge_bases = owned_knowledge + other_knowledge
            knowledge_for_user = []
            
            # Batch fetch all unique user_ids to avoid N+1 queries
            unique_user_ids = list(set([kb.user_id for kb in all_knowledge_bases]))
            users_dict = {}
            if unique_user_ids:
                # Use batch method if available, otherwise fall back to individual lookups
                batch_users = Users.get_users_by_user_ids(unique_user_ids)
                users_dict = {user.id: user.model_dump() for user in batch_users}
                # Fill in None for any user_ids not found
                for uid in unique_user_ids:
                    if uid not in users_dict:
                        users_dict[uid] = None

            for knowledge in all_knowledge_bases:
                # Check ownership first (fast path)
                if knowledge.user_id == user_id:
                    knowledge_for_user.append(
                        KnowledgeUserModel.model_validate(
                            {
                                **KnowledgeModel.model_validate(knowledge).model_dump(),
                                "user": users_dict.get(knowledge.user_id),
                            }
                        )
                    )
                # Then check access control (slower, but only for non-owned items)
                elif (has_access(user_id, permission, knowledge.access_control) or
                      self._item_assigned_to_user_groups(user_id, knowledge, permission)):
                    knowledge_for_user.append(
                        KnowledgeUserModel.model_validate(
                            {
                                **KnowledgeModel.model_validate(knowledge).model_dump(),
                                "user": users_dict.get(knowledge.user_id),
                            }
                        )
                    )
            return knowledge_for_user

    def get_knowledge_by_id(self, id: str) -> Optional[KnowledgeModel]:
        try:
            with get_db() as db:
                knowledge = db.query(Knowledge).filter_by(id=id).first()
                if knowledge:
                    # Ensure data is never None - initialize with file_ids if missing
                    knowledge_model = KnowledgeModel.model_validate(knowledge)
                    if knowledge_model.data is None:
                        knowledge_model.data = {"file_ids": []}
                    elif not isinstance(knowledge_model.data, dict):
                        knowledge_model.data = {"file_ids": []}
                    elif "file_ids" not in knowledge_model.data:
                        knowledge_model.data["file_ids"] = []
                    return knowledge_model
                return None
        except Exception:
            return None

    def update_knowledge_by_id(
        self, id: str, form_data: KnowledgeForm, overwrite: bool = False
    ) -> Optional[KnowledgeModel]:
        try:
            with get_db() as db:
                knowledge = (
                    db.query(Knowledge)
                    .filter_by(id=id)
                    .with_for_update()
                    .first()
                )
                if knowledge is None:
                    return None
                values = form_data.model_dump(exclude={"assign_to_email"})
                current_data = (
                    dict(knowledge.data) if isinstance(knowledge.data, dict) else {}
                )
                incoming_data = values.get("data")
                next_data = (
                    dict(incoming_data)
                    if isinstance(incoming_data, dict)
                    else current_data
                )
                current_file_ids = current_data.get("file_ids", [])
                next_data["file_ids"] = (
                    list(current_file_ids)
                    if isinstance(current_file_ids, list)
                    else []
                )
                values["data"] = next_data
                for key, value in values.items():
                    setattr(knowledge, key, value)
                knowledge.updated_at = int(time.time())
                db.commit()
                return KnowledgeModel.model_validate(knowledge)
        except Exception as error:
            log.error(
                "Failed to update knowledge %s | type=%s",
                id,
                type(error).__name__,
            )
            return None

    def add_files_to_knowledge_by_id(
        self,
        id: str,
        file_ids: list[str],
    ) -> Optional[KnowledgeModel]:
        """Append existing files under the shared File-then-Knowledge lock order."""

        from open_webui.models.files import File

        requested_ids = sorted({str(file_id) for file_id in file_ids if file_id})
        if not requested_ids:
            return self.get_knowledge_by_id(id=id)
        try:
            with get_db() as db:
                locked_files = (
                    db.query(File)
                    .filter(File.id.in_(requested_ids))
                    .order_by(File.id)
                    .with_for_update()
                    .all()
                )
                if {row.id for row in locked_files} != set(requested_ids):
                    return None
                knowledge = (
                    db.query(Knowledge)
                    .filter(Knowledge.id == id)
                    .with_for_update()
                    .first()
                )
                if knowledge is None:
                    return None
                data = dict(knowledge.data or {})
                current_ids = data.get("file_ids", [])
                current_ids = (
                    list(current_ids) if isinstance(current_ids, list) else []
                )
                for file_id in requested_ids:
                    if file_id not in current_ids:
                        current_ids.append(file_id)
                data["file_ids"] = current_ids
                knowledge.data = data
                knowledge.updated_at = int(time.time())
                db.commit()
                return KnowledgeModel.model_validate(knowledge)
        except Exception:
            log.exception("Failed to add files to knowledge %s", id)
            return None

    def remove_files_from_knowledge_by_id(
        self,
        id: str,
        file_ids: list[str],
    ) -> Optional[KnowledgeModel]:
        """Remove specified IDs from the current locked membership list."""

        removed_ids = {str(file_id) for file_id in file_ids if file_id}
        try:
            with get_db() as db:
                knowledge = (
                    db.query(Knowledge)
                    .filter(Knowledge.id == id)
                    .with_for_update()
                    .first()
                )
                if knowledge is None:
                    return None
                data = dict(knowledge.data or {})
                current_ids = data.get("file_ids", [])
                current_ids = (
                    list(current_ids) if isinstance(current_ids, list) else []
                )
                data["file_ids"] = [
                    file_id for file_id in current_ids if file_id not in removed_ids
                ]
                knowledge.data = data
                knowledge.updated_at = int(time.time())
                db.commit()
                return KnowledgeModel.model_validate(knowledge)
        except Exception:
            log.exception("Failed to remove files from knowledge %s", id)
            return None

    def update_knowledge_data_by_id(
        self, id: str, data: dict
    ) -> Optional[KnowledgeModel]:
        import time as time_module
        max_retries = 3
        retry_delay = 0.1  # 100ms
        
        for attempt in range(max_retries):
            try:
                with get_db() as db:
                    # Verify knowledge exists before updating
                    knowledge_exists = db.query(Knowledge).filter_by(id=id).first()
                    if not knowledge_exists:
                        log.error(f"Knowledge {id} not found for data update")
                        return None
                    
                    # Log current state for debugging
                    log.info(
                        "Updating knowledge %s (attempt %s/%s)",
                        id,
                        attempt + 1,
                        max_retries,
                    )
                    
                    # Ensure data is a dict with file_ids key
                    if not isinstance(data, dict):
                        log.error(f"Invalid data type for knowledge {id}: {type(data)}")
                        return None
                    if "file_ids" not in data:
                        data["file_ids"] = []
                    
                    # Perform the update
                    rows_updated = db.query(Knowledge).filter_by(id=id).update(
                        {
                            "data": data,
                            "updated_at": int(time.time()),
                        }
                    )
                    db.commit()
                    
                    log.info(f"Update commit completed for knowledge {id}: rows_updated={rows_updated}")
                    
                    # Verify the update succeeded
                    if rows_updated == 0:
                        if attempt < max_retries - 1:
                            log.warning(f"No rows updated for knowledge {id} on attempt {attempt + 1}, retrying...")
                            time_module.sleep(retry_delay * (attempt + 1))  # Exponential backoff
                            continue
                        else:
                            log.error(f"No rows updated for knowledge {id} after {max_retries} attempts - possible transaction conflict or row lock")
                            return None
                    
                    # Refresh and read from the same session to ensure consistency
                    db.expire_all()  # Expire all objects to force fresh read
                    updated_knowledge = db.query(Knowledge).filter_by(id=id).first()
                    if not updated_knowledge:
                        log.error(f"Failed to retrieve updated knowledge {id} from same session")
                        return None
                    
                    log.info("Retrieved updated knowledge %s", id)
                    
                    # Convert to model and normalize data
                    knowledge_model = KnowledgeModel.model_validate(updated_knowledge)
                    if knowledge_model.data is None:
                        knowledge_model.data = {"file_ids": []}
                    elif not isinstance(knowledge_model.data, dict):
                        knowledge_model.data = {"file_ids": []}
                    elif "file_ids" not in knowledge_model.data:
                        knowledge_model.data["file_ids"] = []
                    
                    return knowledge_model
            except Exception as error:
                if attempt < max_retries - 1:
                    log.warning(
                        "Knowledge data update failed; retrying | knowledge=%s | "
                        "attempt=%s | type=%s",
                        id,
                        attempt + 1,
                        type(error).__name__,
                    )
                    time_module.sleep(retry_delay * (attempt + 1))
                    continue
                else:
                    log.error(
                        "Knowledge data update failed | knowledge=%s | "
                        "attempts=%s | type=%s",
                        id,
                        max_retries,
                        type(error).__name__,
                    )
                    return None
        
        return None

    def delete_knowledge_by_id(self, id: str) -> bool:
        try:
            with get_db() as db:
                db.query(Knowledge).filter_by(id=id).delete()
                db.commit()
                return True
        except Exception:
            return False

    def delete_all_knowledge(self) -> bool:
        with get_db() as db:
            try:
                db.query(Knowledge).delete()
                db.commit()

                return True
            except Exception:
                return False

    def get_knowledge_bases_by_file_id(self, file_id: str) -> list[KnowledgeModel]:
        """
        Find all knowledge bases that contain the specified file_id in their file_ids list.
        
        This method works with both SQLite and PostgreSQL databases via SQLAlchemy ORM.
        It loads all knowledge bases and filters in Python, which is acceptable for
        typical use cases. For very large datasets, consider optimizing with a database
        query that uses JSON functions (PostgreSQL jsonb_path_exists or SQLite json_each).
        
        Args:
            file_id: The file ID to search for
            
        Returns:
            List of KnowledgeModel instances that contain this file_id
        """
        knowledge_bases = []
        try:
            with get_db() as db:
                # Load all knowledge bases - works for both SQLite and PostgreSQL
                # SQLAlchemy ORM abstracts database differences
                all_knowledge = db.query(Knowledge).all()
                for knowledge in all_knowledge:
                    if knowledge.data and isinstance(knowledge.data, dict):
                        file_ids = knowledge.data.get("file_ids", [])
                        if isinstance(file_ids, list) and file_id in file_ids:
                            knowledge_model = KnowledgeModel.model_validate(knowledge)
                            # Ensure data structure is normalized
                            if knowledge_model.data is None:
                                knowledge_model.data = {"file_ids": []}
                            elif not isinstance(knowledge_model.data, dict):
                                knowledge_model.data = {"file_ids": []}
                            elif "file_ids" not in knowledge_model.data:
                                knowledge_model.data["file_ids"] = []
                            knowledge_bases.append(knowledge_model)
        except Exception as e:
            log.exception(f"Error finding knowledge bases for file_id {file_id}: {e}")
        return knowledge_bases

    def user_has_read_access_to_file(self, user_id: str, file_id: str) -> bool:
        """Return whether any containing knowledge base is readable by a user.

        File ownership and administrator access remain the responsibility of
        the file route. This helper extends read access only through current
        knowledge ownership, explicit read grants, or assigned groups.
        """
        for knowledge in self.get_knowledge_bases_by_file_id(file_id):
            if knowledge.user_id == user_id:
                return True
            if has_access(user_id, "read", knowledge.access_control):
                return True
            if self._item_assigned_to_user_groups(
                user_id, knowledge, permission="read"
            ):
                return True
        return False

    def remove_file_from_all_knowledge_bases(self, file_id: str) -> bool:
        """
        Remove a file_id from all knowledge bases that contain it.
        This updates the knowledge.data.file_ids list for each affected knowledge base.
        
        Args:
            file_id: The file ID to remove from all knowledge bases
            
        Returns:
            True if successful, False otherwise
        """
        try:
            knowledge_bases = self.get_knowledge_bases_by_file_id(file_id)
            success = True
            
            for knowledge in knowledge_bases:
                if knowledge.data and isinstance(knowledge.data, dict):
                    file_ids = knowledge.data.get("file_ids", [])
                    if isinstance(file_ids, list) and file_id in file_ids:
                        file_ids.remove(file_id)
                        knowledge.data["file_ids"] = file_ids
                        
                        # Update the knowledge base
                        updated = self.update_knowledge_data_by_id(knowledge.id, knowledge.data)
                        if not updated:
                            log.error(f"Failed to remove file {file_id} from knowledge base {knowledge.id}")
                            success = False
                        else:
                            log.info(f"Removed file {file_id} from knowledge base {knowledge.id}")
            
            return success
        except Exception as e:
            log.exception(f"Error removing file {file_id} from all knowledge bases: {e}")
            return False


Knowledges = KnowledgeTable()
