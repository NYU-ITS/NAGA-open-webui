SUPER_ADMIN_EMAILS = [
        "sm11538@nyu.edu",
        "ms15138@nyu.edu", 
        "mb484@nyu.edu",
        "cg4532@nyu.edu",
        "ht2490@nyu.edu",
        "ps5226@nyu.edu"
    ]

def is_super_admin(user) -> bool:
    """Check if user is super admin based on existing logic"""
    from open_webui.models.users import Users
    
    if not user:
        return False
    
    return (
        user.id == Users.get_first_user().id or 
        user.email in SUPER_ADMIN_EMAILS
    )

def is_email_super_admin(email) -> bool:
    """Check if an email belongs to a super admin"""
    if not email:
        return False
    return email in SUPER_ADMIN_EMAILS

def batch_check_super_admin(emails: list[str]) -> dict[str, bool]:
    """
    Batch check super admin status for multiple emails.
    
    This function matches the behavior of is_email_super_admin() for consistency
    with the single endpoint /users/is-super-admin.
    
    Args:
        emails: List of email addresses to check
        
    Returns:
        Dictionary mapping email -> bool (True if super admin, False otherwise)
    """
    if not emails:
        return {}
    
    # Remove duplicates and None/empty values
    unique_emails = list(set(email for email in emails if email))
    
    if not unique_emails:
        return {}
    
    # Build result dictionary - check if each email is in SUPER_ADMIN_EMAILS
    # This matches the behavior of is_email_super_admin() used by the single endpoint
    result = {}
    for email in unique_emails:
        result[email] = is_email_super_admin(email)
    
    return result