import logging
import time
from typing import Optional

from open_webui.internal.db import Base, JSONField, get_db
from open_webui.models.users import Users, UserResponse
from open_webui.env import SRC_LOG_LEVELS
from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Column, String, Text, JSON, or_, text, bindparam

from open_webui.utils.access_control import has_access


log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

####################
# Tools DB Schema
####################


class Tool(Base):
    __tablename__ = "tool"

    id = Column(String, primary_key=True)
    user_id = Column(String)
    created_by = Column(Text, nullable=True)
    name = Column(Text)
    content = Column(Text)
    specs = Column(JSONField)
    meta = Column(JSONField)
    valves = Column(JSONField)

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

    updated_at = Column(BigInteger)
    created_at = Column(BigInteger)


class ToolMeta(BaseModel):
    description: Optional[str] = None
    manifest: Optional[dict] = {}


class ToolModel(BaseModel):
    id: str
    user_id: str
    created_by: Optional[str] = None
    name: str
    content: str
    specs: list[dict]
    meta: ToolMeta
    # access_control: Optional[dict] = None
    access_control: Optional[dict] = {}

    updated_at: int  # timestamp in epoch
    created_at: int  # timestamp in epoch

    model_config = ConfigDict(from_attributes=True)


####################
# Forms
####################


class ToolUserModel(ToolModel):
    user: Optional[UserResponse] = None


class ToolResponse(BaseModel):
    id: str
    user_id: str
    created_by: Optional[str] = None
    name: str
    meta: ToolMeta
    # access_control: Optional[dict] = None
    access_control: Optional[dict] = {}
    updated_at: int  # timestamp in epoch
    created_at: int  # timestamp in epoch


class ToolUserResponse(ToolResponse):
    user: Optional[UserResponse] = None


class ToolForm(BaseModel):
    id: str
    name: str
    content: str
    meta: ToolMeta
    # access_control: Optional[dict] = None
    access_control: Optional[dict] = {}
    assign_to_email: Optional[str] = None


class ToolValves(BaseModel):
    valves: Optional[dict] = None


class ToolsTable:
    def insert_new_tool(
        self, user_id: str, user_email: str, form_data: ToolForm, specs: list[dict]
    ) -> Optional[ToolModel]:
        with get_db() as db:
            tool = ToolModel(
                **{
                    **form_data.model_dump(exclude={"assign_to_email"}),
                    "specs": specs,
                    "user_id": user_id,
                    "created_by": user_email,
                    "updated_at": int(time.time()),
                    "created_at": int(time.time()),
                }
            )

            try:
                result = Tool(**tool.model_dump())
                db.add(result)
                db.commit()
                db.refresh(result)
                if result:
                    return ToolModel.model_validate(result)
                else:
                    return None
            except Exception as e:
                log.exception(f"Error creating a new tool: {e}")
                return None

    def get_tool_by_id(self, id: str) -> Optional[ToolModel]:
        try:
            with get_db() as db:
                tool = db.get(Tool, id)
                return ToolModel.model_validate(tool)
        except Exception:
            return None

    def get_tools(self) -> list[ToolUserModel]:
        with get_db() as db:
            all_tools = db.query(Tool).order_by(Tool.updated_at.desc()).all()
            
            # Batch load all users at once
            user_ids = {tool.user_id for tool in all_tools}
            users_dict = {}
            if user_ids:
                users_list = Users.get_users_by_user_ids(list(user_ids))
                users_dict = {user.id: user for user in users_list}
            
            # Build response with batched user data
            tools = []
            for tool in all_tools:
                user = users_dict.get(tool.user_id)
                tools.append(
                    ToolUserModel.model_validate(
                        {
                            **ToolModel.model_validate(tool).model_dump(),
                            "user": user.model_dump() if user else None,
                        }
                    )
                )
            return tools

    # def get_tools_by_user_id(
    #     self, user_id: str, permission: str = "write"
    # ) -> list[ToolUserModel]:
    #     tools = self.get_tools()

    #     return [
    #         tool
    #         for tool in tools
    #         if tool.user_id == user_id
    #         or has_access(user_id, permission, tool.access_control)
    #     ]

    def _item_assigned_to_user_groups(self, user_id: str, item, permission: str = "write") -> bool:
        """Check if item is assigned to any group the user is member of OR owns"""
        from open_webui.utils.workspace_access import item_assigned_to_user_groups
        return item_assigned_to_user_groups(user_id, item, permission)

    def get_tools_by_user_id(
        self, user_id: str, permission: str = "write"
    ) -> list[ToolUserModel]:
        """
        Return only the tools that this user either created
        or has group-based permission to (via has_access).
        """
        with get_db() as db:
            from open_webui.models.groups import Groups
            
            # Pre-fetch user groups once
            user_groups = Groups.get_groups_by_member_id(user_id)
            user_group_ids = [g.id for g in user_groups]
            
            # Build SQL query to filter at database level
            dialect_name = db.bind.dialect.name
            query = db.query(Tool).order_by(Tool.updated_at.desc())
            
            # Filter by user_id first (uses index)
            conditions = [Tool.user_id == user_id]
            
            # For PostgreSQL, we can use JSON queries to filter at database level
            if dialect_name == "postgresql":
                # Add direct access conditions (access_control with user_ids)
                user_id_json = f'["{user_id}"]'
                if permission == "write":
                    conditions.append(
                        text("""
                            (tool.access_control->'write'->'user_ids' @> :user_id_json::jsonb)
                            OR (tool.access_control->'read'->'user_ids' @> :user_id_json::jsonb)
                        """).bindparams(bindparam('user_id_json', user_id_json))
                    )
                else:
                    conditions.append(
                        text("""
                            tool.access_control->'read'->'user_ids' @> :user_id_json::jsonb
                        """).bindparams(bindparam('user_id_json', user_id_json))
                    )
                
                # Add group access conditions using PostgreSQL JSON queries
                if user_group_ids:
                    group_ids_list = user_group_ids
                    if permission == "write":
                        conditions.append(
                            text("""
                                EXISTS (
                                    SELECT 1
                                    FROM jsonb_array_elements_text(tool.access_control->'write'->'group_ids') AS group_id
                                    WHERE group_id = ANY(:group_ids)
                                )
                                OR EXISTS (
                                    SELECT 1
                                    FROM jsonb_array_elements_text(tool.access_control->'read'->'group_ids') AS group_id
                                    WHERE group_id = ANY(:group_ids)
                                )
                            """).bindparams(bindparam('group_ids', group_ids_list))
                        )
                    else:
                        conditions.append(
                            text("""
                                EXISTS (
                                    SELECT 1
                                    FROM jsonb_array_elements_text(tool.access_control->'read'->'group_ids') AS group_id
                                    WHERE group_id = ANY(:group_ids)
                                )
                            """).bindparams(bindparam('group_ids', group_ids_list))
                        )
            
            # Apply all conditions
            query = query.filter(or_(*conditions))
            
            # Execute query - now filtered at database level for PostgreSQL
            tools_for_user = query.all()
            
            # For SQLite, we need additional Python filtering for access_control
            if dialect_name != "postgresql":
                filtered_tools = []
                for tool in tools_for_user:
                    # Check access in Python
                    has_user_access = tool.user_id == user_id
                    has_direct_access = has_access(user_id, permission, tool.access_control)
                    has_group_access = False
                    
                    if not has_user_access and not has_direct_access and tool.access_control:
                        read_groups = tool.access_control.get("read", {}).get("group_ids", [])
                        write_groups = tool.access_control.get("write", {}).get("group_ids", [])
                        item_groups = list(set(read_groups + write_groups))
                        has_group_access = any(group_id in user_group_ids for group_id in item_groups)
                    
                    if has_user_access or has_direct_access or has_group_access:
                        filtered_tools.append(tool)
                tools_for_user = filtered_tools
            
            # Get all unique user_ids from filtered tools to batch load users
            user_ids = {tool.user_id for tool in tools_for_user}
            users_dict = {}
            if user_ids:
                users_list = Users.get_users_by_user_ids(list(user_ids))
                users_dict = {user.id: user for user in users_list}
            
            # Build response with batched user data
            result = []
            for tool in tools_for_user:
                user = users_dict.get(tool.user_id)
                result.append(
                        ToolUserModel.model_validate(
                            {
                                **ToolModel.model_validate(tool).model_dump(),
                                "user": user.model_dump() if user else None,
                            }
                        )
                    )
            return result

    def get_tool_valves_by_id(self, id: str) -> Optional[dict]:
        try:
            with get_db() as db:
                tool = db.get(Tool, id)
                return tool.valves if tool.valves else {}
        except Exception as e:
            log.exception(f"Error getting tool valves by id {id}: {e}")
            return None

    def update_tool_valves_by_id(self, id: str, valves: dict) -> Optional[ToolValves]:
        try:
            with get_db() as db:
                db.query(Tool).filter_by(id=id).update(
                    {"valves": valves, "updated_at": int(time.time())}
                )
                db.commit()
                return self.get_tool_by_id(id)
        except Exception:
            return None

    def get_user_valves_by_id_and_user_id(
        self, id: str, user_id: str
    ) -> Optional[dict]:
        try:
            user = Users.get_user_by_id(user_id)
            user_settings = user.settings.model_dump() if user.settings else {}

            # Check if user has "tools" and "valves" settings
            if "tools" not in user_settings:
                user_settings["tools"] = {}
            if "valves" not in user_settings["tools"]:
                user_settings["tools"]["valves"] = {}

            return user_settings["tools"]["valves"].get(id, {})
        except Exception as e:
            log.exception(
                f"Error getting user values by id {id} and user_id {user_id}: {e}"
            )
            return None

    def update_user_valves_by_id_and_user_id(
        self, id: str, user_id: str, valves: dict
    ) -> Optional[dict]:
        try:
            user = Users.get_user_by_id(user_id)
            user_settings = user.settings.model_dump() if user.settings else {}

            # Check if user has "tools" and "valves" settings
            if "tools" not in user_settings:
                user_settings["tools"] = {}
            if "valves" not in user_settings["tools"]:
                user_settings["tools"]["valves"] = {}

            user_settings["tools"]["valves"][id] = valves

            # Update the user settings in the database
            Users.update_user_by_id(user_id, {"settings": user_settings})

            return user_settings["tools"]["valves"][id]
        except Exception as e:
            log.exception(
                f"Error updating user valves by id {id} and user_id {user_id}: {e}"
            )
            return None

    def update_tool_by_id(self, id: str, updated: dict) -> Optional[ToolModel]:
        try:
            with get_db() as db:
                db.query(Tool).filter_by(id=id).update(
                    {**updated, "updated_at": int(time.time())}
                )
                db.commit()

                tool = db.query(Tool).get(id)
                db.refresh(tool)
                return ToolModel.model_validate(tool)
        except Exception:
            return None

    def delete_tool_by_id(self, id: str) -> bool:
        try:
            with get_db() as db:
                db.query(Tool).filter_by(id=id).delete()
                db.commit()

                return True
        except Exception:
            return False


Tools = ToolsTable()
