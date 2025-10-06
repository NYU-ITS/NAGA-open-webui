"""
Workspace access control utilities for group-based collaboration
"""

def item_assigned_to_user_groups(user_id: str, item, permission: str = "write") -> bool:
    """Check if item is assigned to any group the user is member of OR owns OR user is super admin"""
    from open_webui.models.groups import Groups
    from open_webui.models.users import Users
    
    # Check if user is super admin - they see everything
    user = Users.get_user_by_id(user_id)
    super_admin_emails = [
        "sm11538@nyu.edu",
        "ms15138@nyu.edu", 
        "mb484@nyu.edu",
        "cg4532@nyu.edu",
        "jy4421@nyu.edu",
        "ht2490@nyu.edu",
        "ps5226@nyu.edu"
    ]
    is_super_admin = (
        user and user.id == Users.get_first_user().id or 
        user and user.email in super_admin_emails
    )
    
    if is_super_admin:
        return True  # Super admin sees ALL items
    
    # Get groups where user is member
    user_groups = Groups.get_groups_by_member_id(user_id)
    user_group_ids = [g.id for g in user_groups]
    
    # Get BOTH read and write groups for the item
    read_groups = item.access_control.get("read", {}).get("group_ids", [])
    write_groups = item.access_control.get("write", {}).get("group_ids", [])
    item_groups = list(set(read_groups + write_groups))  # Combine and dedupe
    
    # Check if user is member of any group that has access
    member_match = any(group_id in user_group_ids for group_id in item_groups)
    if member_match:
        return True
    
    # Also check if user owns any of the groups that have access to this item
    all_groups = Groups.get_groups()
    owned_group_ids = [g.id for g in all_groups if g.user_id == user_id]
    owner_match = any(group_id in owned_group_ids for group_id in item_groups)
    
    return owner_match