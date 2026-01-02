from fastapi import APIRouter, HTTPException, status, Depends
from models import AccountRegistration, CredentialsInput, AuthenticationToken, AccountProfile
from auth import (
    get_password_hash,
    verify_password,
    create_access_token,
    get_current_user_id
)
from database import cosmos_db
from datetime import datetime
import uuid
import logging

auth_logger = logging.getLogger(__name__)

router = APIRouter(tags=["Authentication"], prefix="/auth")


@router.post("/register", status_code=status.HTTP_200_OK, response_model=AuthenticationToken)
async def create_user_account(registration_data: AccountRegistration):
    """Create new user registration"""
    try:
        # Verify email availability
        auth_logger.info(f"New registration request: {registration_data.email}")
        user_exists = cosmos_db.get_user_by_email(registration_data.email)
        if user_exists:
            auth_logger.warning(f"Duplicate email detected: {registration_data.email}")
            raise HTTPException(
                detail="User with this email already exists",
                status_code=status.HTTP_400_BAD_REQUEST
            )

        # Build user record
        new_user_id = str(uuid.uuid4())
        hashed_pwd = get_password_hash(registration_data.password)
        timestamp = datetime.utcnow().isoformat()

        user_record = {
            "id": new_user_id,
            "email": registration_data.email,
            "username": registration_data.username,
            "hashed_password": hashed_pwd,
            "created_at": timestamp
        }

        # Persist to database
        saved_user = cosmos_db.create_user(user_record)
        auth_logger.info(f"Successfully registered: {registration_data.email}")

        # Create authentication token
        jwt_token = create_access_token(
            data={"email": registration_data.email, "sub": new_user_id}
        )

        # Build response payload
        response_user = AccountProfile(
            email=saved_user["email"],
            id=saved_user["id"],
            createdAt=saved_user["created_at"],
            username=saved_user["username"]
        )

        return AuthenticationToken(user=response_user, token=jwt_token)

    except HTTPException:
        raise
    except ValueError as validation_error:
        auth_logger.error(f"Validation failed: {validation_error}")
        raise HTTPException(
            detail=str(validation_error), status_code=status.HTTP_400_BAD_REQUEST
        )
    except Exception as unexpected_error:
        auth_logger.error(f"Registration failed: {unexpected_error}", exc_info=True)
        raise HTTPException(
            detail=f"Failed to register user: {str(unexpected_error)}",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@router.post("/login", status_code=status.HTTP_200_OK, response_model=AuthenticationToken)
async def authenticate_user(credentials: CredentialsInput):
    """Authenticate and issue access token"""
    try:
        # Fetch user account
        auth_logger.info(f"Authentication request: {credentials.email}")
        account = cosmos_db.get_user_by_email(credentials.email)
        if not account:
            auth_logger.warning(f"Account not found: {credentials.email}")
            raise HTTPException(
                detail="Invalid email or password",
                status_code=status.HTTP_401_UNAUTHORIZED
            )

        # Validate credentials
        password_valid = verify_password(credentials.password, account["hashed_password"])
        if not password_valid:
            auth_logger.warning(f"Invalid credentials for: {credentials.email}")
            raise HTTPException(
                detail="Invalid email or password",
                status_code=status.HTTP_401_UNAUTHORIZED
            )

        # Issue JWT token
        jwt_token = create_access_token(
            data={"email": account["email"], "sub": account["id"]}
        )

        # Construct response
        authenticated_user = AccountProfile(
            email=account["email"],
            createdAt=account["created_at"],
            id=account["id"],
            username=account["username"]
        )

        auth_logger.info(f"Authentication successful: {account['email']}")
        return AuthenticationToken(user=authenticated_user, token=jwt_token)

    except HTTPException:
        raise
    except Exception as login_error:
        auth_logger.error(f"Authentication error: {login_error}", exc_info=True)
        raise HTTPException(
            detail=f"Failed to login: {str(login_error)}",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
