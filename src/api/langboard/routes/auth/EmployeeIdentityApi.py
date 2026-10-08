"""Public verification keys for native employee identity proofs."""

from fastapi import HTTPException
from langboard_shared.core.routing import AppRouter, JsonResponse
from ...mcp_tools.EmployeeIdentityMcp import employee_identity_jwks


@AppRouter.api.get("/auth/employee-identity/jwks", tags=["Auth.OIDC"], response_model=None)
def get_employee_identity_jwks() -> JsonResponse:
    try:
        return JsonResponse(content=employee_identity_jwks())
    except (OSError, ValueError, RuntimeError, TypeError) as error:
        raise HTTPException(status_code=503, detail="Employee identity signer unavailable") from error
