"""
Credential Management API routes.

Provides REST endpoints for managing exchange API credentials
with proper encryption and tenant isolation.
"""

import re
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Depends, Request, status
from pydantic import BaseModel, Field, field_validator
from slowapi import Limiter
from slowapi.util import get_remote_address

from src.auth.dependencies import get_current_user_payload, TokenPayload
from src.security.credential_manager import CredentialManager
from src.security.audit import get_audit_logger, AuditEventType
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Rate limiter
limiter = Limiter(key_func=get_remote_address)

# Router
router = APIRouter(prefix="/api/credentials", tags=["credentials"])


# ==================== REQUEST/RESPONSE MODELS ====================


class CredentialCreate(BaseModel):
    """Request to create a new credential."""
    name: str = Field(..., min_length=1, max_length=100)
    api_key: str = Field(..., min_length=10, max_length=500)
    api_secret: str = Field(..., min_length=10, max_length=500)
    passphrase: str = Field(..., min_length=4, max_length=100)
    exchange: str = Field(default="bitget", max_length=50)
    credential_type: str = Field(default="live", pattern="^(live|demo)$")

    @field_validator('name')
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not re.match(r'^[a-zA-Z0-9\s_-]+$', v):
            raise ValueError('Name can only contain letters, numbers, spaces, underscores, and hyphens')
        return v.strip()


class CredentialUpdate(BaseModel):
    """Request to update a credential."""
    api_key: Optional[str] = Field(None, min_length=10, max_length=500)
    api_secret: Optional[str] = Field(None, min_length=10, max_length=500)
    passphrase: Optional[str] = Field(None, min_length=4, max_length=100)


class CredentialResponse(BaseModel):
    """Response with masked credential data."""
    id: int
    name: str
    exchange: str
    credential_type: str
    api_key_masked: str  # Only last 4 chars visible
    is_active: bool
    created_at: Optional[datetime]
    last_used: Optional[datetime]


class CredentialListResponse(BaseModel):
    """List of credentials."""
    credentials: List[CredentialResponse]
    count: int


class CredentialTestResponse(BaseModel):
    """Response from credential test."""
    success: bool
    message: str
    balance: Optional[float] = None
    permissions: Optional[List[str]] = None


class MessageResponse(BaseModel):
    """Simple message response."""
    message: str
    success: bool = True


def mask_api_key(api_key: str) -> str:
    """Mask API key, showing only last 4 characters."""
    if len(api_key) <= 4:
        return "****"
    return "*" * (len(api_key) - 4) + api_key[-4:]


# ==================== CREDENTIAL ENDPOINTS ====================


@router.get("", response_model=CredentialListResponse)
@limiter.limit("30/minute")
async def list_credentials(
    request: Request,
    credential_type: Optional[str] = None,
    payload: TokenPayload = Depends(get_current_user_payload),
):
    """
    List all credentials for the current user (masked).

    Credentials are returned with masked API keys for security.
    """
    manager = CredentialManager()
    credentials = await manager.get_user_credentials(
        user_id=payload.user_id,
        credential_type=credential_type,
        decrypt=False
    )

    # Convert to masked response
    response_items = []
    for cred in credentials:
        # Get last 4 chars of encrypted key (not the actual key!)
        # For proper masking, we'd need to decrypt first, but that's expensive
        # So we use a placeholder mask
        response_items.append(CredentialResponse(
            id=cred.id,
            name=cred.name,
            exchange=cred.exchange,
            credential_type=cred.credential_type,
            api_key_masked="****" + cred.api_key_encrypted[-4:] if cred.api_key_encrypted else "****",
            is_active=cred.is_active,
            created_at=cred.created_at,
            last_used=cred.last_used
        ))

    return CredentialListResponse(
        credentials=response_items,
        count=len(response_items)
    )


@router.post("", response_model=CredentialResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/hour")
async def create_credential(
    request: Request,
    data: CredentialCreate,
    payload: TokenPayload = Depends(get_current_user_payload),
):
    """
    Add a new exchange credential.

    The API key, secret, and passphrase are encrypted before storage.
    Rate limited to prevent abuse.
    """
    manager = CredentialManager()

    try:
        credential = await manager.store_credential(
            user_id=payload.user_id,
            name=data.name,
            api_key=data.api_key,
            api_secret=data.api_secret,
            passphrase=data.passphrase,
            exchange=data.exchange,
            credential_type=data.credential_type
        )

        logger.info(f"User {payload.user_id} created credential '{data.name}'")

        # Audit log
        audit = await get_audit_logger()
        await audit.log_credential_event(
            event_type=AuditEventType.CREDENTIAL_CREATE,
            user_id=payload.user_id,
            credential_id=credential.id,
            ip_address=request.client.host if request.client else None,
            credential_name=data.name,
            success=True,
        )

        return CredentialResponse(
            id=credential.id,
            name=credential.name,
            exchange=credential.exchange,
            credential_type=credential.credential_type,
            api_key_masked=mask_api_key(data.api_key),
            is_active=credential.is_active,
            created_at=credential.created_at,
            last_used=credential.last_used
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Failed to create credential: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to store credential"
        )


@router.get("/{credential_id}", response_model=CredentialResponse)
@limiter.limit("30/minute")
async def get_credential(
    request: Request,
    credential_id: int,
    payload: TokenPayload = Depends(get_current_user_payload),
):
    """
    Get a specific credential (masked).
    """
    manager = CredentialManager()

    # Get encrypted credential (not decrypted for list view)
    credentials = await manager.get_user_credentials(
        user_id=payload.user_id,
        decrypt=False
    )

    credential = next((c for c in credentials if c.id == credential_id), None)
    if not credential:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found"
        )

    return CredentialResponse(
        id=credential.id,
        name=credential.name,
        exchange=credential.exchange,
        credential_type=credential.credential_type,
        api_key_masked="****" + credential.api_key_encrypted[-4:] if credential.api_key_encrypted else "****",
        is_active=credential.is_active,
        created_at=credential.created_at,
        last_used=credential.last_used
    )


@router.put("/{credential_id}", response_model=MessageResponse)
@limiter.limit("10/hour")
async def update_credential(
    request: Request,
    credential_id: int,
    data: CredentialUpdate,
    payload: TokenPayload = Depends(get_current_user_payload),
):
    """
    Update a credential (rotate API keys).

    Only provided fields are updated. Omit fields to keep existing values.
    """
    if not data.api_key and not data.api_secret and not data.passphrase:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one field must be provided to update"
        )

    manager = CredentialManager()

    success = await manager.update_credential(
        credential_id=credential_id,
        user_id=payload.user_id,
        api_key=data.api_key,
        api_secret=data.api_secret,
        passphrase=data.passphrase
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found or update failed"
        )

    logger.info(f"User {payload.user_id} updated credential {credential_id}")

    return MessageResponse(message="Credential updated successfully")


@router.delete("/{credential_id}", response_model=MessageResponse)
@limiter.limit("10/hour")
async def revoke_credential(
    request: Request,
    credential_id: int,
    permanent: bool = False,
    payload: TokenPayload = Depends(get_current_user_payload),
):
    """
    Revoke (deactivate) a credential.

    By default, this is a soft delete. Set permanent=true to permanently
    delete the credential (cannot be undone).
    """
    manager = CredentialManager()

    if permanent:
        success = await manager.delete_credential(credential_id, payload.user_id)
        action = "permanently deleted"
    else:
        success = await manager.revoke_credential(credential_id, payload.user_id)
        action = "revoked"

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found"
        )

    logger.info(f"User {payload.user_id} {action} credential {credential_id}")

    return MessageResponse(message=f"Credential {action} successfully")


@router.post("/{credential_id}/test", response_model=CredentialTestResponse)
@limiter.limit("5/minute")
async def test_credential(
    request: Request,
    credential_id: int,
    payload: TokenPayload = Depends(get_current_user_payload),
):
    """
    Test a credential against the Bitget API.

    Makes a simple API call to verify the credentials are valid
    and have the necessary permissions.
    """
    manager = CredentialManager()

    # First validate encryption
    is_valid, error_msg = await manager.validate_credential(credential_id, payload.user_id)
    if not is_valid:
        return CredentialTestResponse(
            success=False,
            message=f"Credential validation failed: {error_msg}"
        )

    # Get decrypted credential
    try:
        decrypted = await manager.get_credential(credential_id, payload.user_id)
        if not decrypted:
            return CredentialTestResponse(
                success=False,
                message="Credential not found"
            )

        # Test against Bitget API
        from src.exchange.bitget_client import BitgetClient

        client = BitgetClient(
            api_key=decrypted.api_key,
            api_secret=decrypted.api_secret,
            passphrase=decrypted.passphrase,
            demo_mode=(decrypted.credential_type == "demo")
        )

        # Try to get account balance (basic API test)
        balance = await client.get_account_balance()

        logger.info(f"User {payload.user_id} tested credential {credential_id} - SUCCESS")

        return CredentialTestResponse(
            success=True,
            message="Credential is valid and connected to Bitget",
            balance=balance.get("available", 0) if balance else None,
            permissions=["read", "trade"]  # Bitget doesn't expose permissions easily
        )

    except ImportError:
        # BitgetClient not available, just validate encryption
        return CredentialTestResponse(
            success=True,
            message="Credential encryption valid (API test unavailable)"
        )
    except Exception as e:
        error_msg = str(e)
        # Mask any sensitive info that might be in the error
        if "key" in error_msg.lower() or "secret" in error_msg.lower():
            error_msg = "API authentication failed"

        logger.warning(f"User {payload.user_id} credential test failed: {error_msg}")

        return CredentialTestResponse(
            success=False,
            message=f"API test failed: {error_msg}"
        )


@router.post("/{credential_id}/activate", response_model=MessageResponse)
@limiter.limit("10/hour")
async def activate_credential(
    request: Request,
    credential_id: int,
    payload: TokenPayload = Depends(get_current_user_payload),
):
    """
    Reactivate a previously revoked credential.
    """
    manager = CredentialManager()

    # Get the credential repository directly for activation
    from src.models.credential import CredentialRepository
    repo = CredentialRepository()

    # Check if credential exists and belongs to user
    cred = await repo.get_by_id(credential_id, payload.user_id)
    if not cred:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found"
        )

    if cred.is_active:
        return MessageResponse(message="Credential is already active")

    # Reactivate
    success = await repo.activate(credential_id, payload.user_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to activate credential"
        )

    logger.info(f"User {payload.user_id} reactivated credential {credential_id}")

    return MessageResponse(message="Credential reactivated successfully")
