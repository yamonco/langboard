from typing import Callable
from fastapi import HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from ..logger import Logger
from .ApiErrorCode import ApiErrorCode
from .ApiException import ApiErrorCodeException
from .JsonResponse import JsonResponse


class AppExceptionHandlingRoute(APIRoute):
    """Handles exceptions that occur during the route handling process inherited from :class:`fastapi.routing.APIRoute`."""

    def get_route_handler(self) -> Callable:
        original_route_handler = super().get_route_handler()

        async def route_handler(request: Request) -> Response:
            try:
                return await original_route_handler(request)
            except RequestValidationError as e:
                return self.handle_validation_error(e)
            except ApiErrorCodeException as e:
                return self.handle_api_error_code_exception(e)
            except HTTPException as e:
                return JsonResponse(content={"detail": e.detail}, status_code=e.status_code, headers=e.headers)
            except Exception as e:
                return self.handle_generic_exception(e)

        return route_handler

    def handle_validation_error(self, exc: RequestValidationError) -> Response:
        errors: dict[str, dict] = {}
        raw_errors = exc.errors()
        for raw_error in raw_errors:
            error_type = raw_error["type"]
            if error_type not in errors:
                errors[error_type] = {}
            if len(raw_error["loc"]) <= 1:
                continue

            where = raw_error["loc"][0]
            fields = raw_error["loc"][1:]
            if where not in errors[error_type]:
                errors[error_type][where] = []
            errors[error_type][where].extend(fields)
        return JsonResponse(
            content={**ApiErrorCode.VA0000.to_dict(), "errors": errors}, status_code=status.HTTP_400_BAD_REQUEST
        )

    def handle_api_error_code_exception(self, exc: ApiErrorCodeException) -> Response:
        return JsonResponse(
            content=exc.detail,
            status_code=exc.status_code,
        )

    def handle_generic_exception(self, exc: Exception) -> Response:
        Logger.main.exception(exc)
        return JsonResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={**ApiErrorCode.OP0000.to_dict(), "status": False},
        )
