import time
from typing import Optional

from open_webui.internal.db import Base, get_db
from open_webui.models.users import Users, UserResponse

from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Column, String, Text, JSON, or_, text

from open_webui.utils.access_control import has_access

####################
# Prompts DB Schema
####################


class Prompt(Base):
    __tablename__ = "prompt"

    command = Column(String, primary_key=True)
    user_id = Column(String)
    title = Column(Text)
    content = Column(Text)
    timestamp = Column(BigInteger)

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


class PromptModel(BaseModel):
    command: str
    user_id: str
    title: str
    content: str
    timestamp: int  # timestamp in epoch

    # access_control: Optional[dict] = None
    access_control: Optional[dict] = {}
    model_config = ConfigDict(from_attributes=True)


####################
# Forms
####################


class PromptUserResponse(PromptModel):
    user: Optional[UserResponse] = None


class PromptForm(BaseModel):
    command: str
    title: str
    content: str
    # access_control: Optional[dict] = None
    access_control: Optional[dict] = {}
    assign_to_email: Optional[str] = None


class PromptsTable:
    def insert_new_prompt(
        self, user_id: str, form_data: PromptForm
    ) -> Optional[PromptModel]:
        prompt = PromptModel(
            **{
                "user_id": user_id,
                **form_data.model_dump(exclude={"assign_to_email"}),
                "timestamp": int(time.time()),
            }
        )

        try:
            with get_db() as db:
                result = Prompt(**prompt.model_dump())
                db.add(result)
                db.commit()
                db.refresh(result)
                if result:
                    return PromptModel.model_validate(result)
                else:
                    return None
        except Exception:
            return None

    def get_prompt_by_command(self, command: str) -> Optional[PromptModel]:
        try:
            with get_db() as db:
                prompt = db.query(Prompt).filter_by(command=command).first()
                return PromptModel.model_validate(prompt)
        except Exception:
            return None

    def get_prompts(self) -> list[PromptUserResponse]:
        with get_db() as db:
            all_prompts = db.query(Prompt).order_by(Prompt.timestamp.desc()).all()
            
            # Batch load all users at once
            user_ids = {prompt.user_id for prompt in all_prompts}
            users_dict = {}
            if user_ids:
                users_list = Users.get_users_by_user_ids(list(user_ids))
                users_dict = {user.id: user for user in users_list}
            
            # Build response with batched user data
            prompts = []
            for prompt in all_prompts:
                user = users_dict.get(prompt.user_id)
                prompts.append(
                    PromptUserResponse.model_validate(
                        {
                            **PromptModel.model_validate(prompt).model_dump(),
                            "user": user.model_dump() if user else None,
                        }
                    )
                )
            return prompts

    # def get_prompts_by_user_id(
    #     self, user_id: str, permission: str = "write"
    # ) -> list[PromptUserResponse]:
    #     prompts = self.get_prompts()

    #     return [
    #         prompt
    #         for prompt in prompts
    #         if prompt.user_id == user_id
    #         or has_access(user_id, permission, prompt.access_control)
    #     ]

    def _item_assigned_to_user_groups(self, user_id: str, item, permission: str = "write") -> bool:
        """Check if item is assigned to any group the user is member of OR owns"""
        from open_webui.utils.workspace_access import item_assigned_to_user_groups
        return item_assigned_to_user_groups(user_id, item, permission)

    def get_prompts_by_user_id(
        self, user_id: str, permission: str = "write"
    ) -> list[PromptUserResponse]:
        with get_db() as db:
            from open_webui.models.groups import Groups
            
            # Pre-fetch user groups once
            user_groups = Groups.get_groups_by_member_id(user_id)
            user_group_ids = [g.id for g in user_groups]
            
            # Build SQL query to filter at database level
            dialect_name = db.bind.dialect.name
            query = db.query(Prompt).order_by(Prompt.timestamp.desc())
            
            # Filter by user_id first (uses index)
            conditions = [Prompt.user_id == user_id]
            
            # For PostgreSQL, we can use JSON queries to filter at database level
            if dialect_name == "postgresql":
                # Add direct access conditions (access_control with user_ids)
                user_id_json = f'["{user_id}"]'
                if permission == "write":
                    conditions.append(
                        text("""
                            (prompt.access_control->'write'->'user_ids' @> :user_id_json::jsonb)
                            OR (prompt.access_control->'read'->'user_ids' @> :user_id_json::jsonb)
                        """).params(user_id_json=user_id_json)
                    )
                else:
                    conditions.append(
                        text("""
                            prompt.access_control->'read'->'user_ids' @> :user_id_json::jsonb
                        """).params(user_id_json=user_id_json)
                    )
                
                # Add group access conditions using PostgreSQL JSON queries
                if user_group_ids:
                    group_ids_list = user_group_ids
                    if permission == "write":
                        conditions.append(
                            text("""
                                EXISTS (
                                    SELECT 1
                                    FROM jsonb_array_elements_text(prompt.access_control->'write'->'group_ids') AS group_id
                                    WHERE group_id = ANY(:group_ids)
                                )
                                OR EXISTS (
                                    SELECT 1
                                    FROM jsonb_array_elements_text(prompt.access_control->'read'->'group_ids') AS group_id
                                    WHERE group_id = ANY(:group_ids)
                                )
                            """).params(group_ids=group_ids_list)
                        )
                    else:
                        conditions.append(
                            text("""
                                EXISTS (
                                    SELECT 1
                                    FROM jsonb_array_elements_text(prompt.access_control->'read'->'group_ids') AS group_id
                                    WHERE group_id = ANY(:group_ids)
                                )
                            """).params(group_ids=group_ids_list)
                        )
            
            # Apply all conditions
            query = query.filter(or_(*conditions))
            
            # Execute query - now filtered at database level for PostgreSQL
            prompts_for_user = query.all()
            
            # For SQLite, we need additional Python filtering for access_control
            if dialect_name != "postgresql":
                filtered_prompts = []
                for prompt in prompts_for_user:
                    # Check access in Python
                    has_user_access = prompt.user_id == user_id
                    has_direct_access = has_access(user_id, permission, prompt.access_control)
                    has_group_access = False
                    
                    if not has_user_access and not has_direct_access and prompt.access_control:
                        read_groups = prompt.access_control.get("read", {}).get("group_ids", [])
                        write_groups = prompt.access_control.get("write", {}).get("group_ids", [])
                        item_groups = list(set(read_groups + write_groups))
                        has_group_access = any(group_id in user_group_ids for group_id in item_groups)
                    
                    if has_user_access or has_direct_access or has_group_access:
                        filtered_prompts.append(prompt)
                prompts_for_user = filtered_prompts
            
            # Get all unique user_ids from filtered prompts to batch load users
            user_ids = {prompt.user_id for prompt in prompts_for_user}
            users_dict = {}
            if user_ids:
                users_list = Users.get_users_by_user_ids(list(user_ids))
                users_dict = {user.id: user for user in users_list}
            
            # Build response with batched user data
            result = []
            for prompt in prompts_for_user:
                user = users_dict.get(prompt.user_id)
                result.append(
                        PromptUserResponse.model_validate(
                            {
                                **PromptModel.model_validate(prompt).model_dump(),
                                "user": user.model_dump() if user else None,
                            }
                        )
                    )
            return result

    def update_prompt_by_command(
        self, command: str, form_data: PromptForm
    ) -> Optional[PromptModel]:
        try:
            with get_db() as db:
                prompt = db.query(Prompt).filter_by(command=command).first()
                prompt.title = form_data.title
                prompt.content = form_data.content
                prompt.access_control = form_data.access_control
                prompt.timestamp = int(time.time())
                db.commit()
                return PromptModel.model_validate(prompt)
        except Exception:
            return None

    def delete_prompt_by_command(self, command: str) -> bool:
        try:
            with get_db() as db:
                db.query(Prompt).filter_by(command=command).delete()
                db.commit()

                return True
        except Exception:
            return False


Prompts = PromptsTable()
