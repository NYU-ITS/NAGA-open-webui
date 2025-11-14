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
from sqlalchemy import BigInteger, Column, String, Text, JSON, or_, text

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
    files: Optional[list[FileMetadataResponse | dict]] = None


class KnowledgeUserResponse(KnowledgeUserModel):
    files: Optional[list[FileMetadataResponse | dict]] = None


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
            knowledge = KnowledgeModel(
                **{
                    **form_data.model_dump(exclude={"assign_to_email"}),
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
            all_knowledge = db.query(Knowledge).order_by(Knowledge.updated_at.desc()).all()
            
            # Batch load all users at once
            user_ids = {kb.user_id for kb in all_knowledge}
            users_dict = {}
            if user_ids:
                users_list = Users.get_users_by_user_ids(list(user_ids))
                users_dict = {user.id: user for user in users_list}
            
            # Build response with batched user data
            knowledge_bases = []
            for knowledge in all_knowledge:
                user = users_dict.get(knowledge.user_id)
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
            from open_webui.models.groups import Groups
            
            # Pre-fetch user groups once
            user_groups = Groups.get_groups_by_member_id(user_id)
            user_group_ids = [g.id for g in user_groups]
            
            # Build SQL query to filter at database level
            dialect_name = db.bind.dialect.name
            query = db.query(Knowledge).order_by(Knowledge.updated_at.desc())
            
            # Filter by user_id first (uses index)
            conditions = [Knowledge.user_id == user_id]
            
            # For PostgreSQL, we can use JSON queries to filter at database level
            if dialect_name == "postgresql":
                # Add direct access conditions (access_control with user_ids)
                user_id_json = f'["{user_id}"]'
                if permission == "write":
                    conditions.append(
                        text("""
                            (knowledge.access_control->'write'->'user_ids' @> :user_id_json::jsonb)
                            OR (knowledge.access_control->'read'->'user_ids' @> :user_id_json::jsonb)
                        """).bindparam(user_id_json=user_id_json)
                    )
                else:
                    conditions.append(
                        text("""
                            knowledge.access_control->'read'->'user_ids' @> :user_id_json::jsonb
                        """).bindparam(user_id_json=user_id_json)
                    )
                
                # Add group access conditions using PostgreSQL JSON queries
                if user_group_ids:
                    group_ids_list = user_group_ids
                    if permission == "write":
                        conditions.append(
                            text("""
                                EXISTS (
                                    SELECT 1
                                    FROM jsonb_array_elements_text(knowledge.access_control->'write'->'group_ids') AS group_id
                                    WHERE group_id = ANY(:group_ids)
                                )
                                OR EXISTS (
                                    SELECT 1
                                    FROM jsonb_array_elements_text(knowledge.access_control->'read'->'group_ids') AS group_id
                                    WHERE group_id = ANY(:group_ids)
                                )
                            """).bindparam(group_ids=group_ids_list)
                        )
                    else:
                        conditions.append(
                            text("""
                                EXISTS (
                                    SELECT 1
                                    FROM jsonb_array_elements_text(knowledge.access_control->'read'->'group_ids') AS group_id
                                    WHERE group_id = ANY(:group_ids)
                                )
                            """).bindparam(group_ids=group_ids_list)
                        )
            
            # Apply all conditions
            query = query.filter(or_(*conditions))
            
            # Execute query - now filtered at database level for PostgreSQL
            knowledge_for_user = query.all()
            
            # For SQLite, we need additional Python filtering for access_control
            if dialect_name != "postgresql":
                filtered_knowledge = []
                for knowledge in knowledge_for_user:
                    # Check access in Python
                    has_user_access = knowledge.user_id == user_id
                    has_direct_access = has_access(user_id, permission, knowledge.access_control)
                    has_group_access = False
                    
                    if not has_user_access and not has_direct_access and knowledge.access_control:
                        read_groups = knowledge.access_control.get("read", {}).get("group_ids", [])
                        write_groups = knowledge.access_control.get("write", {}).get("group_ids", [])
                        item_groups = list(set(read_groups + write_groups))
                        has_group_access = any(group_id in user_group_ids for group_id in item_groups)
                    
                    if has_user_access or has_direct_access or has_group_access:
                        filtered_knowledge.append(knowledge)
                knowledge_for_user = filtered_knowledge
            
            # Get all unique user_ids from filtered knowledge bases to batch load users
            user_ids = {knowledge.user_id for knowledge in knowledge_for_user}
            users_dict = {}
            if user_ids:
                users_list = Users.get_users_by_user_ids(list(user_ids))
                users_dict = {user.id: user for user in users_list}
            
            # Build response with batched user data
            result = []
            for knowledge in knowledge_for_user:
                user = users_dict.get(knowledge.user_id)
                result.append(
                    KnowledgeUserModel.model_validate(
                        {
                            **KnowledgeModel.model_validate(knowledge).model_dump(),
                            "user": user.model_dump() if user else None,
                        }
                    )
                )
            return result

    def get_knowledge_by_id(self, id: str) -> Optional[KnowledgeModel]:
        try:
            with get_db() as db:
                knowledge = db.query(Knowledge).filter_by(id=id).first()
                return KnowledgeModel.model_validate(knowledge) if knowledge else None
        except Exception:
            return None

    def update_knowledge_by_id(
        self, id: str, form_data: KnowledgeForm, overwrite: bool = False
    ) -> Optional[KnowledgeModel]:
        try:
            with get_db() as db:
                knowledge = self.get_knowledge_by_id(id=id)
                db.query(Knowledge).filter_by(id=id).update(
                    {
                        **form_data.model_dump(exclude={"assign_to_email"}),
                        "updated_at": int(time.time()),
                    }
                )
                db.commit()
                return self.get_knowledge_by_id(id=id)
        except Exception as e:
            log.exception(e)
            return None

    def update_knowledge_data_by_id(
        self, id: str, data: dict
    ) -> Optional[KnowledgeModel]:
        try:
            with get_db() as db:
                knowledge = self.get_knowledge_by_id(id=id)
                db.query(Knowledge).filter_by(id=id).update(
                    {
                        "data": data,
                        "updated_at": int(time.time()),
                    }
                )
                db.commit()
                return self.get_knowledge_by_id(id=id)
        except Exception as e:
            log.exception(e)
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


Knowledges = KnowledgeTable()
