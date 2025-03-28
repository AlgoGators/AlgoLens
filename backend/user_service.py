from sqlalchemy.orm import Session
from db_models import User
from typing import Optional
from werkzeug.security import generate_password_hash, check_password_hash

def get_user_by_email(db: Session, email:str) -> Optional[User]:
    """
    Retrieve a user from the database by email
    """
    return db.query(User).filter_by(email=email).first()

def get_user_by_id(db: Session, user_id: int) -> Optional[User]:
    """
    Retrieve a user by their ID.
    """
    return db.query(User).filter_by(id=user_id).first()

def create_user(db: Session, email: str, password: str, role: str="general_member"):
    """
    Create a new user and store the hashed password.
    """
    user = User(email=email, role=role)
    user.set_password(password)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

def check_user_password(db:Session, email: str, password:str):
    """
    Verify the user's password
    """
    user = get_user_by_email(db, email)
    if user and user.check_password(password):
        return True
    return False

def update_user_role(db: Session, user_id: int, password: Optional[str] = None, role:Optional[str] = None) -> Optional[User]:
    """
    Update a user's mutable fields. Email, ID, and created_at cannot be changed.
    """
    user = get_user_by_id(db, user_id)
    if not user:
        return None
    if password:
        user.set_password(password)
    if role:
        user.role = role
    
    db.commit()
    db.refresh(user)
    return user


def delete_user(db: Session, user_id: int) -> bool:
    """
    Delete a user from the database
    """
    user = get_user_by_id(db, user_id)
    if user:
        db.delete(user)
        db.commit()
        return True
    return False