import logging
import time
from typing import Optional

from open_webui.internal.db import Base, JSONField, get_db
from open_webui.env import SRC_LOG_LEVELS

from open_webui.models.users import Users, UserResponse


from pydantic import BaseModel, ConfigDict

from sqlalchemy import or_, and_, func, text, literal
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy import BigInteger, Column, Text, JSON, Boolean


from open_webui.utils.access_control import has_access


log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


####################
# Models DB Schema
####################


# ModelParams is a model for the data stored in the params field of the Model table
class ModelParams(BaseModel):
    model_config = ConfigDict(extra="allow")
    pass


# ModelMeta is a model for the data stored in the meta field of the Model table
class ModelMeta(BaseModel):
    profile_image_url: Optional[str] = "/static/favicon.png"

    description: Optional[str] = None
    """
        User-facing description of the model.
    """

    capabilities: Optional[dict] = None

    model_config = ConfigDict(extra="allow")

    pass


class Model(Base):
    __tablename__ = "model"

    id = Column(Text, primary_key=True)
    """
        The model's id as used in the API. If set to an existing model, it will override the model.
    """
    user_id = Column(Text)
    created_by = Column(Text, nullable=True)

    base_model_id = Column(Text, nullable=True)
    """
        An optional pointer to the actual model that should be used when proxying requests.
    """

    name = Column(Text)
    """
        The human-readable display name of the model.
    """

    params = Column(JSONField)
    """
        Holds a JSON encoded blob of parameters, see `ModelParams`.
    """

    meta = Column(JSONField)
    """
        Holds a JSON encoded blob of metadata, see `ModelMeta`.
    """

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

    is_active = Column(Boolean, default=True)

    updated_at = Column(BigInteger)
    created_at = Column(BigInteger)


class ModelModel(BaseModel):
    id: str
    user_id: str
    created_by: Optional[str] = None
    base_model_id: Optional[str] = None

    name: str
    params: ModelParams
    meta: ModelMeta

    access_control: Optional[dict] = None

    is_active: bool
    updated_at: int  # timestamp in epoch
    created_at: int  # timestamp in epoch

    model_config = ConfigDict(from_attributes=True)


####################
# Forms
####################


class ModelUserResponse(ModelModel):
    user: Optional[UserResponse] = None


class ModelResponse(ModelModel):
    pass


class ModelForm(BaseModel):
    id: str
    base_model_id: Optional[str] = None
    name: str
    meta: ModelMeta
    params: ModelParams
    access_control: Optional[dict] = None
    is_active: bool = True


class ModelsTable:
    def insert_new_model(
        self, form_data: ModelForm, user_id: str, user_email: str
    ) -> Optional[ModelModel]:
        model = ModelModel(
            **{
                **form_data.model_dump(),
                "user_id": user_id,
                "created_by": user_email,
                "created_at": int(time.time()),
                "updated_at": int(time.time()),
            }
        )
        try:
            with get_db() as db:
                result = Model(**model.model_dump())
                db.add(result)
                db.commit()
                db.refresh(result)

                if result:
                    return ModelModel.model_validate(result)
                else:
                    return None
        except Exception as e:
            log.exception(f"Failed to insert a new model: {e}")
            return None

    # def get_all_models(self) -> list[ModelModel]:
    #     with get_db() as db:
    #         return [ModelModel.model_validate(model) for model in db.query(Model).all()]

    def get_all_models(
        self, user_id, user_email: str = None, permission: str = "read"
    ) -> list[ModelModel]:
        with get_db() as db:
            from sqlalchemy import or_, text
            from open_webui.models.groups import Groups
            
            # Pre-fetch user groups once
            user_groups = Groups.get_groups_by_member_id(user_id)
            user_group_ids = [g.id for g in user_groups]
            
            # Build SQL query to filter at database level
            dialect_name = db.bind.dialect.name
            query = db.query(Model)
            
            # Filter by created_by first (uses index if available)
            conditions = []
            if user_email:
                conditions.append(Model.created_by == user_email)
            
            # For PostgreSQL, we can use JSON queries to filter at database level
            if dialect_name == "postgresql":
                # Add direct access conditions (access_control with user_ids)
                # Use literal() to safely embed the JSON value (user_id is from authenticated user, safe to embed)
                user_id_json = f'["{user_id}"]'
                if permission == "write":
                    conditions.append(
                        text(f"""
                            (model.access_control->'write'->'user_ids' @> '{user_id_json}'::jsonb)
                            OR (model.access_control->'read'->'user_ids' @> '{user_id_json}'::jsonb)
                        """)
                    )
                else:
                    conditions.append(
                        text(f"""
                            model.access_control->'read'->'user_ids' @> '{user_id_json}'::jsonb
                        """)
                    )
                
                # Add group access conditions using PostgreSQL JSON queries
                if user_group_ids:
                    # Convert list to PostgreSQL array format
                    group_ids_array = "{" + ",".join([f'"{gid}"' for gid in user_group_ids]) + "}"
                    if permission == "write":
                        conditions.append(
                            text(f"""
                                EXISTS (
                                    SELECT 1
                                    FROM jsonb_array_elements_text(model.access_control->'write'->'group_ids') AS group_id
                                    WHERE group_id = ANY(ARRAY[{group_ids_array}]::text[])
                                )
                                OR EXISTS (
                                    SELECT 1
                                    FROM jsonb_array_elements_text(model.access_control->'read'->'group_ids') AS group_id
                                    WHERE group_id = ANY(ARRAY[{group_ids_array}]::text[])
                                )
                            """)
                        )
                    else:
                        conditions.append(
                            text(f"""
                                EXISTS (
                                    SELECT 1
                                    FROM jsonb_array_elements_text(model.access_control->'read'->'group_ids') AS group_id
                                    WHERE group_id = ANY(ARRAY[{group_ids_array}]::text[])
                                )
                            """)
                        )
            
            # Apply conditions if any, otherwise return all (for admin/super admin)
            if conditions:
                query = query.filter(or_(*conditions))
            
            # Execute query - now filtered at database level for PostgreSQL
            raw_models = query.all()
            
            # For SQLite, we need additional Python filtering for access_control
            if dialect_name != "postgresql" and conditions:
                filtered = []
                for model in raw_models:
                    if model.created_by == user_email or has_access(
                        user_id, permission, model.access_control
                    ):
                        filtered.append(model)
                raw_models = filtered

        return [ModelModel.model_validate(m) for m in raw_models]

    def get_models(self) -> list[ModelUserResponse]:
        with get_db() as db:
            all_models = db.query(Model).filter(Model.base_model_id != None).all()
            
            # Batch load all users at once
            user_ids = {model.user_id for model in all_models}
            users_dict = {}
            if user_ids:
                users_list = Users.get_users_by_user_ids(list(user_ids))
                users_dict = {user.id: user for user in users_list}
            
            # Build response with batched user data
            models = []
            for model in all_models:
                user = users_dict.get(model.user_id)
                models.append(
                    ModelUserResponse.model_validate(
                        {
                            **ModelModel.model_validate(model).model_dump(),
                            "user": user.model_dump() if user else None,
                        }
                    )
                )
            return models

    def get_base_models(self) -> list[ModelModel]:
        with get_db() as db:
            return [
                ModelModel.model_validate(model)
                for model in db.query(Model).filter(Model.base_model_id == None).all()
            ]

    # def get_base_models(self, user_email: str) -> list[ModelModel]:
    #     with get_db() as db:
    #         return [
    #             ModelModel.model_validate(model)
    #             for model in db.query(Model)
    #                 .filter(
    #                     Model.base_model_id == None,
    #                     or_(
    #                         Model.created_by == user_email,
    #                         Model.created_by == "cg4532@nyu.edu"
    #                     )
    #                 )
    #                 .all()
    #         ]

    # def get_models_by_user_id(
    #     self, user_id: str, permission: str = "write"
    # ) -> list[ModelUserResponse]:
    #     models = self.get_models()
    #     return [
    #         model
    #         for model in models
    #         if model.user_id == user_id
    #         or has_access(user_id, permission, model.access_control)
    #     ]

    def _item_assigned_to_user_groups(self, user_id: str, item, permission: str = "write") -> bool:
        """Check if item is assigned to any group the user is member of OR owns"""
        from open_webui.utils.workspace_access import item_assigned_to_user_groups
        return item_assigned_to_user_groups(user_id, item, permission)

    def get_models_by_user_id(
        self, user_id: str, permission: str = "write"
    ) -> list[ModelUserResponse]:
        with get_db() as db:
            from open_webui.models.groups import Groups
            
            # Pre-fetch user groups once
            user_groups = Groups.get_groups_by_member_id(user_id)
            user_group_ids = [g.id for g in user_groups]
            
            # Build SQL query to filter at database level
            dialect_name = db.bind.dialect.name
            query = db.query(Model).filter(Model.base_model_id != None)
            
            # Filter by user_id first (uses index)
            conditions = [Model.user_id == user_id]
            
            # For PostgreSQL, we can use JSON queries to filter at database level
            # For SQLite, we'll fall back to Python filtering (slower but works)
            if dialect_name == "postgresql":
                # Add direct access conditions (access_control with user_ids)
                # Use f-string to embed JSON value (user_id is from authenticated user, safe to embed)
                user_id_json = f'["{user_id}"]'
                if permission == "write":
                    conditions.append(
                        text(f"""
                            (model.access_control->'write'->'user_ids' @> '{user_id_json}'::jsonb)
                            OR (model.access_control->'read'->'user_ids' @> '{user_id_json}'::jsonb)
                        """)
                    )
                else:
                    conditions.append(
                        text(f"""
                            model.access_control->'read'->'user_ids' @> '{user_id_json}'::jsonb
                        """)
                    )
                
                # Add group access conditions using PostgreSQL JSON queries
                if user_group_ids:
                    # Check if any of the user's groups are in the access_control
                    # Use jsonb_array_elements_text to expand arrays and check membership
                    # Convert list to PostgreSQL array format
                    group_ids_array = "{" + ",".join([f'"{gid}"' for gid in user_group_ids]) + "}"
                    if permission == "write":
                        # Check write or read groups
                        conditions.append(
                            text(f"""
                                EXISTS (
                                    SELECT 1
                                    FROM jsonb_array_elements_text(model.access_control->'write'->'group_ids') AS group_id
                                    WHERE group_id = ANY(ARRAY[{group_ids_array}]::text[])
                                )
                                OR EXISTS (
                                    SELECT 1
                                    FROM jsonb_array_elements_text(model.access_control->'read'->'group_ids') AS group_id
                                    WHERE group_id = ANY(ARRAY[{group_ids_array}]::text[])
                                )
                            """)
                        )
                    else:
                        # Check read groups only
                        conditions.append(
                            text(f"""
                                EXISTS (
                                    SELECT 1
                                    FROM jsonb_array_elements_text(model.access_control->'read'->'group_ids') AS group_id
                                    WHERE group_id = ANY(ARRAY[{group_ids_array}]::text[])
                                )
                            """)
                        )
            else:
                # For SQLite, filter by user_id first (uses index), then filter access_control in Python
                # This is less efficient but necessary for SQLite compatibility
                pass
            
            # Apply all conditions
            query = query.filter(or_(*conditions))
            
            # Execute query - now filtered at database level for PostgreSQL
            models_for_user = query.all()
            
            # For SQLite, we need additional Python filtering for access_control
            if dialect_name != "postgresql":
                filtered_models = []
                for model in models_for_user:
                    # Check access in Python
                    has_user_access = model.user_id == user_id
                    has_direct_access = has_access(user_id, permission, model.access_control)
                    has_group_access = False
                    
                    if not has_user_access and not has_direct_access and model.access_control:
                        read_groups = model.access_control.get("read", {}).get("group_ids", [])
                        write_groups = model.access_control.get("write", {}).get("group_ids", [])
                        item_groups = list(set(read_groups + write_groups))
                        has_group_access = any(group_id in user_group_ids for group_id in item_groups)
                    
                    if has_user_access or has_direct_access or has_group_access:
                        filtered_models.append(model)
                models_for_user = filtered_models
            
            # Get all unique user_ids from filtered models to batch load users
            user_ids = {model.user_id for model in models_for_user}
            users_dict = {}
            if user_ids:
                users_list = Users.get_users_by_user_ids(list(user_ids))
                users_dict = {user.id: user for user in users_list}
            
            # Build response with batched user data
            result = []
            for model in models_for_user:
                user = users_dict.get(model.user_id)
                result.append(
                    ModelUserResponse.model_validate(
                        {
                            **ModelModel.model_validate(model).model_dump(),
                            "user": user.model_dump() if user else None,
                        }
                    )
                )
            return result

    def get_model_by_id(self, id: str) -> Optional[ModelModel]:
        try:
            with get_db() as db:
                model = db.get(Model, id)
                return ModelModel.model_validate(model)
        except Exception:
            return None

    # def get_model_by_id(self, id: str, user_email: str) -> Optional[ModelModel]:
    #     try:
    #         with get_db() as db:
    #             model = db.get(Model, id)
    #             if model is None:
    #                 return None
    #             # Only return the model if it was created by the current user
    #             # or by the specific shared email.
    #             if model.created_by != user_email and model.created_by != "cg4532@nyu.edu":
    #                 return None
    #             return ModelModel.model_validate(model)
    #     except Exception:
    #         return None

    def toggle_model_by_id(self, id: str) -> Optional[ModelModel]:
        with get_db() as db:
            try:
                is_active = db.query(Model).filter_by(id=id).first().is_active

                db.query(Model).filter_by(id=id).update(
                    {
                        "is_active": not is_active,
                        "updated_at": int(time.time()),
                    }
                )
                db.commit()

                return self.get_model_by_id(id)
            except Exception:
                return None

    def update_model_by_id(self, id: str, model: ModelForm) -> Optional[ModelModel]:
        try:
            with get_db() as db:
                # update only the fields that are present in the model
                result = (
                    db.query(Model)
                    .filter_by(id=id)
                    .update(model.model_dump(exclude={"id"}))
                )
                db.commit()

                model = db.get(Model, id)
                db.refresh(model)
                return ModelModel.model_validate(model)
        except Exception as e:
            log.exception(f"Failed to update the model by id {id}: {e}")
            return None

    def delete_model_by_id(self, id: str) -> bool:
        try:
            with get_db() as db:
                db.query(Model).filter_by(id=id).delete()
                db.commit()

                return True
        except Exception:
            return False

    def delete_all_models(self) -> bool:
        try:
            with get_db() as db:
                db.query(Model).delete()
                db.commit()

                return True
        except Exception:
            return False


Models = ModelsTable()
